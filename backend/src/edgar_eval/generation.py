"""The generation harness: answer Golden Set cases end to end and score the answers.

Each case's conversation goes through the full pipeline: `prepare_answer_context`, with
the ranker of the retrieval Arm under test (the Shipped Arm by default), then one Answer
Call to the generator under test. The answer is then scored three ways:

- **In code** (`edgar_eval.answer_checks`): citation validity, figure exactness,
  Coverage Gap statements, and the answer's structure (assumption 8).
- **By Jev** (`edgar_eval.judge`), pinned to an exact version: whether the answer
  states each of the case's Required Facts, and Faithfulness of each claim to the
  Sources it cites. Fact Recall is scored on the must-state facts only; detail recall,
  on the details, is reported beside it and decides nothing. Any claim Jev
  judges contradicted by its Sources, a Contradicted Claim, fails the answer
  (`ContradictionCheck`), beside the citation and Coverage Gap checks in code, whatever
  its Faithfulness.
  A judgment Jev fails to make is recorded in its case, which keeps its code checks
  and other judgments; the score that depends on it is missing for that case, and the
  report counts and lists every failed judgment.
- **Cost and latency**, from the Answer Call's logged record: its token usage priced
  at the model's price in `edgar_eval.generators.GENERATORS`, and its latency to the
  first text and to the end.

An answer the model stopped at the Answer Call's token cap (its stop reason is
`token_cap`) is truncated: it fails, its Fact Recall is 0, its Faithfulness is still
judged on what it wrote, and the run counts it.

`make eval-generation` runs it on the dev split with the default generator, prints the
scores and writes them, with every answer, as JSON under `data/derived/eval/`:

    python -m edgar_eval.generation [--split dev|holdout|all] [--model MODEL] [--arm ARM]
        [--index PATH] [--context-budget TOKENS] [--json PATH]

`--index` chooses the index, and so the chunk size, and `--context-budget` the tokens of
Sources per Answer Call (ADR 0010); the report records both, and names the setting
(`chunks-600-budget-32000`) for the selection rule.

`--model` takes a generator from `edgar_eval.generators.GENERATORS`, which says which
provider answers with it. It calls the generator and Jev, so it needs `JEV_API_KEY` and
the key of the generator's provider (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`), and it
costs money:
about a third of a cent per case with `gpt-6-luna`, Jev included.

`--rescore REPORT...` (`make eval-rescore`) instead redoes the figure check of saved
reports from their stored answers, in place, with no Answer Call and no Jev call
(`rescore_figures`). A changed check is a fixed measurement, not a new choice, so
rescoring is allowed on the holdout.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from statistics import fmean
from typing import Protocol, TextIO

from edgar_eval.answer_checks import (
    CitationCheck,
    Claim,
    CoverageGapCheck,
    FigureCheck,
    StructureCheck,
    check_citations,
    check_coverage_gaps,
    check_figures,
    check_structure,
    claims,
)
from edgar_eval.generators import answer_cost, answer_model
from edgar_eval.judge import Evidence, Judgments
from edgar_eval.retrieval import Arm, Prepare, conversation
from edgar_rag.answer_model import DEFAULT_ANSWER_LOG, AnswerCall, AnswerModel, StopReason
from edgar_rag.corpus import DEFAULT_SECTOR_TABLE
from edgar_rag.golden_set import DEFAULT_GOLDEN_SET, GoldenCase, Tier, load_golden_set
from edgar_rag.retrieval import (
    CONTEXT_BUDGET_TOKENS,
    DEFAULT_INDEX,
    Source,
    index_chunk_tokens,
    prepare_answer_context,
)

__all__ = [
    "CaseResult",
    "ContradictionCheck",
    "GenerationReport",
    "Judge",
    "Summary",
    "company_names",
    "evaluate",
    "main",
    "rescore_figures",
]


class Judge(Protocol):
    """What the harness needs from a judge: `edgar_eval.judge.JevJudge`, or a fake. A
    judgment it cannot make goes in `Judgments.failures`; it raises only when no score
    from it could stand, such as a response from another Jev version."""

    def judge(
        self,
        answer: str,
        required_facts: Sequence[str],
        claims: Sequence[Claim],
        sources: dict[str, Evidence],
    ) -> Judgments: ...


@dataclass(frozen=True)
class ContradictionCheck:
    """The answer's Contradicted Claims: claims Jev judged contradicted by the Sources
    they cite. Any one fails the answer, whatever its Faithfulness, so a wrong figure is
    not averaged away."""

    claims: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.claims)

    @property
    def passed(self) -> bool:
        return not self.claims


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    question_type: str
    answer: str
    model: str
    prompt_version: str
    sources: int
    input_tokens: int | None
    output_tokens: int | None
    latency_s: float
    first_token_s: float | None
    cost_usd: float | None
    citations: CitationCheck
    figures: FigureCheck
    coverage_gaps: CoverageGapCheck | None
    """None when the case expects no Coverage Gap."""
    judgments: Judgments
    structure: StructureCheck
    fact_tiers: tuple[Tier, ...] = ()
    """Each judged Required Fact's tier, in the order of `judgments.facts`. Empty means
    every fact is must-state, as in version 1."""
    stop_reason: StopReason | None = None
    """Why the model stopped, from the Answer Call's record."""
    raw_stop_reason: str | None = None

    @property
    def truncated(self) -> bool:
        """Whether the answer was cut off at the Answer Call's token cap."""
        return self.stop_reason == "token_cap"

    @property
    def passed(self) -> bool:
        """Whether the answer passes: not truncated, every citation valid, every
        expected Coverage Gap stated, and no Contradicted Claim."""
        gaps = self.coverage_gaps is None or self.coverage_gaps.passed
        return not self.truncated and self.citations.passed and gaps and self.contradictions.passed

    @property
    def fact_recall(self) -> float | None:
        """The share of must-state Required Facts stated, or None if the case has none
        or their judgment failed. A truncated answer's is 0: a cut-off answer can't
        score as complete."""
        recall = self._recall("must_state")
        return 0.0 if self.truncated and recall is not None else recall

    @property
    def detail_recall(self) -> float | None:
        """The share of detail Required Facts stated, or None if the case has none or
        their judgment failed."""
        return self._recall("detail")

    def _recall(self, tier: Tier) -> float | None:
        if self.judgments.fact_recall is None:  # no fact, or their judgment failed
            return None
        tiers = self.fact_tiers or ("must_state",) * len(self.judgments.facts)
        stated = [f.stated for f, t in zip(self.judgments.facts, tiers, strict=True) if t == tier]
        return sum(stated) / len(stated) if stated else None

    @property
    def faithfulness(self) -> float | None:
        return self.judgments.faithfulness

    @property
    def contradictions(self) -> ContradictionCheck:
        return ContradictionCheck(
            tuple(c.claim for c in self.judgments.claims if c.verdict == "contradicted")
        )


@dataclass(frozen=True)
class Summary:
    """Scores over a group of cases. A score is None when no case in the group has
    anything to score for it (no Required Fact, no expected Coverage Gap)."""

    cases: int
    citations_valid: float
    """Share of answers whose every tag is a listed Source and every unit cites one."""
    figures_exact: float
    """Share of answers whose every figure matches a cited Filing's Financial Fact or
    appears in a cited passage."""
    coverage_gaps_stated: float | None
    """Share of answers with expected Coverage Gaps that state every one of them."""
    structure_followed: float
    """Share of answers in the PE-analyst structure of assumption 8."""
    mean_words: float
    fact_recall: float | None
    """Mean share of must-state Required Facts stated, over cases with any."""
    detail_recall: float | None
    """Mean share of detail Required Facts stated, over cases with any. Reported, never
    decided on."""
    faithfulness: float | None
    """Mean share of claims supported by their cited Sources, over answers with claims."""
    answers_contradicted: int
    """Answers with at least one Contradicted Claim, each of which fails."""
    mean_cost_usd: float | None
    total_cost_usd: float | None
    mean_latency_s: float
    max_latency_s: float
    mean_first_token_s: float | None
    mean_input_tokens: float | None
    mean_output_tokens: float | None
    judge_cost_usd: float
    truncated: int = 0
    """Answers cut off at the Answer Call's token cap."""
    judgments_failed: int = 0
    """Jev judgments that failed, each leaving its case's score missing (`JudgmentFailure`)."""


@dataclass(frozen=True)
class GenerationReport:
    model: str
    judge_model: str
    prompt_version: str
    overall: Summary
    by_type: dict[str, Summary]
    cases: tuple[CaseResult, ...]
    errors: dict[str, str]
    """Cases that could not be answered, with the error. A judgment that failed is
    recorded in its case's judgments instead, and the case is kept."""
    arm: str | None = None
    """The retrieval Arm the Answer Contexts came from."""
    context_budget: int = CONTEXT_BUDGET_TOKENS
    """Tokens of Sources each Answer Call was allowed (ADR 0010)."""
    chunk_tokens: int | None = None
    """The chunk size of the index the Sources came from, when known (ADR 0010)."""

    @property
    def settings(self) -> str:
        """The chunk size and context budget, as the selection rule names a setting."""
        return f"chunks-{self.chunk_tokens or 'unknown'}-budget-{self.context_budget}"

    def to_dict(self) -> dict:
        """The report as plain JSON-ready data, with each case's derived scores."""
        data = asdict(self) | {"settings": self.settings}
        for case, result in zip(data["cases"], self.cases, strict=True):
            case["fact_recall"] = result.fact_recall
            case["detail_recall"] = result.detail_recall
            case["faithfulness"] = result.faithfulness
            contradictions = result.contradictions
            case["contradictions"] = asdict(contradictions) | {
                "count": contradictions.count,
                "passed": contradictions.passed,
            }
            case["truncated"] = result.truncated
            case["passed"] = result.passed
            case["judgments"]["judge_cost_usd"] = result.judgments.cost_usd
        return data


FactValues = Callable[[str], Sequence[int]]
"""The values, in whole US dollars, of the Financial Facts the Filing with this Filing ID
reports."""


def evaluate(
    cases: Sequence[GoldenCase],
    model: AnswerModel,
    judge: Judge,
    index: str | Path,
    *,
    names: dict[str, tuple[str, ...]],
    fact_values: FactValues,
    log_path: str | Path | None = DEFAULT_ANSWER_LOG,
    workers: int = 4,
    prepare: Prepare = prepare_answer_context,
    arm: str | None = None,
    context_budget: int = CONTEXT_BUDGET_TOKENS,
    chunk_tokens: int | None = None,
) -> GenerationReport:
    """Answer every case with the model, score each answer, and summarise the scores
    overall and per question type. Cases run `workers` at a time. `prepare` is the
    retrieval Arm's (`arm`) way of preparing the Answer Context, allowed
    `context_budget` tokens of Sources; `chunk_tokens` is recorded as the index's chunk
    size."""

    def run(case: GoldenCase) -> CaseResult | str:
        try:
            return _run_case(
                case,
                model,
                judge,
                Path(index),
                names,
                fact_values,
                log_path,
                prepare,
                context_budget,
            )
        except Exception as error:  # noqa: BLE001 - a failed case is reported, not fatal
            return f"{type(error).__name__}: {error}"

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        outcomes = list(pool.map(run, cases))
    results = tuple(r for r in outcomes if isinstance(r, CaseResult))
    errors = {c.id: r for c, r in zip(cases, outcomes, strict=True) if isinstance(r, str)}
    by_type: dict[str, list[CaseResult]] = {}
    for result in results:
        by_type.setdefault(result.question_type, []).append(result)
    return GenerationReport(
        model=model.model,
        judge_model=results[0].judgments.model if results else "",
        prompt_version=results[0].prompt_version if results else "",
        overall=_summarise(results),
        by_type={kind: _summarise(group) for kind, group in sorted(by_type.items())},
        cases=results,
        errors=errors,
        arm=arm,
        context_budget=context_budget,
        chunk_tokens=chunk_tokens,
    )


def _run_case(
    case: GoldenCase,
    model: AnswerModel,
    judge: Judge,
    index: Path,
    names: dict[str, tuple[str, ...]],
    fact_values: FactValues,
    log_path: str | Path | None,
    prepare: Prepare = prepare_answer_context,
    context_budget: int = CONTEXT_BUDGET_TOKENS,
) -> CaseResult:
    context = prepare(conversation(case), index, context_budget=context_budget)
    call = AnswerCall(context, model, log_path=log_path)
    answer = "".join(call)
    record = call.record
    assert record is not None
    if not record.completed:
        raise RuntimeError("the Answer Call stopped before the end of its stream")

    passages = {s.number: s.text for s in context.sources}
    evidence = {s.tag: Evidence(s.tag, s.label, s.text) for s in context.sources}
    covered = {s.ticker: names.get(s.ticker, (s.ticker,)) for s in context.sources}
    gaps = case.expected_coverage_gaps
    return CaseResult(
        case_id=case.id,
        question_type=case.question_type,
        answer=answer,
        model=record.model,
        prompt_version=record.prompt_version,
        sources=record.sources,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        latency_s=record.latency_s,
        first_token_s=record.first_token_s,
        cost_usd=answer_cost(record.model, record.input_tokens, record.output_tokens),
        citations=check_citations(answer, passages),
        figures=_check_figures(answer, context.sources, fact_values),
        coverage_gaps=check_coverage_gaps(answer, gaps, names) if gaps else None,
        judgments=judge.judge(
            answer, [f.fact for f in case.required_facts], claims(answer), evidence
        ),
        structure=check_structure(answer, covered),
        fact_tiers=tuple(f.tier for f in case.required_facts),
        stop_reason=record.stop_reason,
        raw_stop_reason=record.raw_stop_reason,
    )


def _check_figures(answer: str, sources: Sequence[Source], fact_values: FactValues) -> FigureCheck:
    """The figure check against the turn's Sources: their passages, and the Financial
    Facts of each one's Filing."""
    return check_figures(
        answer,
        {s.number: s.text for s in sources},
        {s.number: fact_values(s.filing_id) for s in sources},
    )


def _summarise(results: Sequence[CaseResult]) -> Summary:
    def mean(values: Iterable[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return fmean(present) if present else None

    costs = [r.cost_usd for r in results]
    priced = None if not results or None in costs else costs
    return Summary(
        cases=len(results),
        citations_valid=mean(r.citations.passed for r in results) or 0.0,
        figures_exact=mean(r.figures.passed for r in results) or 0.0,
        coverage_gaps_stated=mean(
            r.coverage_gaps.passed if r.coverage_gaps else None for r in results
        ),
        structure_followed=mean(r.structure.passed for r in results) or 0.0,
        mean_words=mean(r.structure.words for r in results) or 0.0,
        fact_recall=mean(r.fact_recall for r in results),
        detail_recall=mean(r.detail_recall for r in results),
        faithfulness=mean(r.faithfulness for r in results),
        answers_contradicted=sum(not r.contradictions.passed for r in results),
        mean_cost_usd=fmean(priced) if priced else None,
        total_cost_usd=sum(priced) if priced else None,
        mean_latency_s=mean(r.latency_s for r in results) or 0.0,
        max_latency_s=max((r.latency_s for r in results), default=0.0),
        mean_first_token_s=mean(r.first_token_s for r in results),
        mean_input_tokens=mean(r.input_tokens for r in results),
        mean_output_tokens=mean(r.output_tokens for r in results),
        judge_cost_usd=sum(r.judgments.cost_usd for r in results),
        truncated=sum(r.truncated for r in results),
        judgments_failed=sum(len(r.judgments.failures) for r in results),
    )


def rescore_figures(
    report: dict,
    cases: Iterable[GoldenCase],
    index: str | Path,
    *,
    fact_values: FactValues,
    prepare: Prepare = prepare_answer_context,
) -> dict:
    """A saved report (`GenerationReport.to_dict`) with its figure check redone from its
    stored answers, and its figures-exact scores recomputed. Nothing else changes.

    A report stores each answer but not its Sources, so each case's Answer Context is
    prepared again through `prepare`, the Arm the report was answered through, at the
    context budget the report records (ADR 0010). That is deterministic and makes no
    Answer Call and no Jev call; it raises ValueError when the report was answered from
    an index of another chunk size, or when a case's Sources no longer number what they
    did, since its answer then cites Sources it was never given.
    """
    chunk_tokens = report.get("chunk_tokens")
    if chunk_tokens is not None and chunk_tokens != index_chunk_tokens(index):
        raise ValueError(
            f"the report was answered from {chunk_tokens}-token chunks, and {index} holds "
            f"{index_chunk_tokens(index)}-token chunks"
        )
    budget = report.get("context_budget", CONTEXT_BUDGET_TOKENS)
    by_id = {c.id: c for c in cases}
    rescored = json.loads(json.dumps(report))
    for case in rescored["cases"]:
        context = prepare(conversation(by_id[case["case_id"]]), Path(index), context_budget=budget)
        if len(context.sources) != case["sources"]:
            raise ValueError(
                f"{case['case_id']}: the Answer Context now has {len(context.sources)} "
                f"Sources, not the {case['sources']} the answer was given"
            )
        case["figures"] = asdict(_check_figures(case["answer"], context.sources, fact_values))

    def figures_exact(group: Iterable[dict]) -> float:
        return fmean(not c["figures"]["unmatched"] for c in group)

    rescored["overall"]["figures_exact"] = figures_exact(rescored["cases"])
    for kind, summary in rescored["by_type"].items():
        summary["figures_exact"] = figures_exact(
            c for c in rescored["cases"] if c["question_type"] == kind
        )
    return rescored


# --- Inputs the harness reads from the repository -----------------------------------------

_SUFFIX = re.compile(
    r"(?:,?\s+(?:(?:&|and)\s+)?(?:Inc|Incorporated|Corp|Corporation|Company|Co|Group|Holdings"
    r"|plc|Ltd)\.?)+$",
    re.I,
)
_EXTRA_NAMES = {
    "GE": ("GE Capital", "General Electric"),
    "JPM": ("JPMorgan", "JP Morgan", "J.P. Morgan"),
    "BAC": ("BofA",),
    "XOM": ("Exxon", "ExxonMobil"),
    "GOOG": ("Google", "Alphabet"),
    "META": ("Meta", "Facebook"),
}


def company_names(path: str | Path = DEFAULT_SECTOR_TABLE) -> dict[str, tuple[str, ...]]:
    """Each Company's ticker, its name from the Sector table with and without its legal
    suffix, and the aliases an answer commonly uses, for the Coverage Gap check."""
    names: dict[str, tuple[str, ...]] = {}
    with Path(path).open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker, name = row["ticker"], row["company"]
            short = _SUFFIX.sub("", name).strip()
            names[ticker] = tuple(
                dict.fromkeys((ticker, name, short, *_EXTRA_NAMES.get(ticker, ())))
            )
    return names


def _missing_company_names(cases: Iterable[GoldenCase]) -> dict[str, tuple[str, ...]]:
    """The Companies missing from the Corpus that the Golden Set's Coverage Gaps name."""
    return {
        name: (name,)
        for case in cases
        for gap in case.expected_coverage_gaps
        if gap.kind == "missing_company"
        for name in gap.companies
    }


@cache
def _all_fact_values() -> dict[str, tuple[int, ...]]:
    from edgar_rag.corpus import load_corpus
    from edgar_rag.financial_facts import extract_financial_facts

    values: dict[str, list[int]] = {}
    for filing in load_corpus():
        if filing.coverage == "tracked":
            for fact in extract_financial_facts(filing):
                values.setdefault(fact.filing_id, []).append(fact.value)
    return {filing_id: tuple(v) for filing_id, v in values.items()}


def corpus_fact_values(filing_id: str) -> tuple[int, ...]:
    """The values of every Financial Fact the Corpus yields for the Filing. Financial
    Facts are extracted for Tracked Companies only (ADR 0001)."""
    return _all_fact_values().get(filing_id, ())


# --- Command line -------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    model: AnswerModel | None = None,
    judge: Judge | None = None,
    fact_values: FactValues | None = None,
    arms: Sequence[Arm] | None = None,
    out: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description="Score generated answers on the Golden Set.")
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
    parser.add_argument(
        "--model", help="a model in GENERATORS (default: OPENAI_MODEL, else the shipped one)"
    )
    parser.add_argument("--arm", help="the retrieval Arm (default: the Shipped Arm)")
    parser.add_argument("--case", action="append", metavar="ID", help="only these cases")
    parser.add_argument("--workers", type=int, default=4, help="cases answered at once")
    parser.add_argument(
        "--index", type=Path, default=DEFAULT_INDEX, help="the index, and so the chunk size"
    )
    parser.add_argument(
        "--context-budget",
        type=int,
        default=CONTEXT_BUDGET_TOKENS,
        metavar="TOKENS",
        help="tokens of Sources per Answer Call (ADR 0010)",
    )
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    parser.add_argument("--log", type=Path, default=DEFAULT_ANSWER_LOG, help="Answer Call log")
    parser.add_argument("--json", type=Path, help="also write the report as JSON here")
    parser.add_argument(
        "--rescore",
        type=Path,
        nargs="+",
        metavar="REPORT",
        help="redo the figure check of saved reports from their answers, in place, "
        "with no Answer Call and no Jev call",
    )
    args = parser.parse_args(argv)

    if arms is None:
        from edgar_eval.arms import ARMS

        arms = ARMS
    by_name = {a.name: a for a in arms}
    if args.arm and args.arm not in by_name:
        parser.error(f"no such Arm: {args.arm} (one of {', '.join(by_name)})")
    arm = by_name[args.arm] if args.arm else next(a for a in arms if a.shipped)
    if arm.prepare is None:
        parser.error(f"the {arm.name} Arm cannot prepare an Answer Context")
    golden = load_golden_set(args.golden_set)
    if args.rescore:
        for path in args.rescore:
            report = json.loads(path.read_text(encoding="utf-8"))
            saved_arm = by_name[report["arm"]] if report.get("arm") else arm
            rescored = rescore_figures(
                report,
                golden.cases,
                args.index,
                fact_values=fact_values or corpus_fact_values,
                prepare=saved_arm.prepare or prepare_answer_context,
            )
            path.write_text(json.dumps(rescored, indent=2) + "\n", encoding="utf-8")
            was, now = report["overall"]["figures_exact"], rescored["overall"]["figures_exact"]
            failing = [c["case_id"] for c in rescored["cases"] if c["figures"]["unmatched"]]
            print(
                f"{path}: figures exact {was:.2f} → {now:.2f}; "
                f"not exact: {', '.join(failing) or 'none'}",
                file=out,
            )
        return 0
    cases = golden.cases if args.split == "all" else golden.split(args.split)
    if args.case:
        unknown = set(args.case) - {c.id for c in cases}
        if unknown:
            parser.error(f"no such case in the {args.split} split: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c.id in args.case]
    if model is None:
        model = answer_model(args.model)
    if judge is None:
        from edgar_eval.judge import JevJudge

        judge = JevJudge()

    report = evaluate(
        cases,
        model,
        judge,
        args.index,
        names=company_names() | _missing_company_names(golden.cases),
        fact_values=fact_values or corpus_fact_values,
        log_path=args.log,
        workers=args.workers,
        prepare=arm.prepare,
        arm=arm.name,
        context_budget=args.context_budget,
        chunk_tokens=index_chunk_tokens(args.index) if args.index.exists() else None,
    )
    _print_report(report, args.split, out)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        data = {"split": args.split, "golden_set_version": golden.version} | report.to_dict()
        args.json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"\nWritten to {args.json.resolve()}", file=out)
    return 1 if report.errors else 0


_COLUMNS = (
    ("cases", lambda s: str(s.cases)),
    ("citations", lambda s: _share(s.citations_valid)),
    ("figures", lambda s: _share(s.figures_exact)),
    ("gaps", lambda s: _share(s.coverage_gaps_stated)),
    ("structure", lambda s: _share(s.structure_followed)),
    ("words", lambda s: f"{s.mean_words:.0f}"),
    ("recall", lambda s: _share(s.fact_recall)),
    ("detail", lambda s: _share(s.detail_recall)),
    ("faithful", lambda s: _share(s.faithfulness)),
    ("contradicted", lambda s: str(s.answers_contradicted)),
    ("$/answer", lambda s: "–" if s.mean_cost_usd is None else f"{s.mean_cost_usd:.4f}"),
    ("latency s", lambda s: f"{s.mean_latency_s:.1f}"),
    ("first s", lambda s: "–" if s.mean_first_token_s is None else f"{s.mean_first_token_s:.1f}"),
)


def _share(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}"


def _print_report(report: GenerationReport, split: str, out: TextIO) -> None:
    print(
        f"Generation on the {split} split: {report.overall.cases} cases answered by "
        f"{report.model} (prompt {report.prompt_version}) on the {report.arm or '?'} Arm "
        f"({report.settings}), judged by {report.judge_model}",
        file=out,
    )
    headers = ["", *(name for name, _ in _COLUMNS)]
    rows = [("overall", report.overall), *report.by_type.items()]
    table = [headers] + [[name, *(f(s) for _, f in _COLUMNS)] for name, s in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(headers))]
    for row in table:
        cells = [c.rjust(w) for c, w in zip(row, widths, strict=True)]
        print("  ".join([row[0].ljust(widths[0])] + cells[1:]), file=out)
    o = report.overall
    total = "–" if o.total_cost_usd is None else f"${o.total_cost_usd:.4f}"
    print(
        f"\nAnswers cost {total} in all; the longest took {o.max_latency_s:.1f} s. "
        f"Jev judging cost ${o.judge_cost_usd:.4f}.",
        file=out,
    )
    print(f"Judgments failed: {o.judgments_failed}", file=out)
    for r in report.cases:
        for failure in r.judgments.failures:
            what = "Fact Recall" if failure.judgment == "fact_recall" else "Faithfulness"
            noun = "Required Fact" if failure.judgment == "fact_recall" else "claim"
            count = len(failure.items)
            print(
                f"  {r.case_id}: {what} of {count} {noun}{'' if count == 1 else 's'}, "
                f"left missing: {failure.error}",
                file=out,
            )
    for label, failing in (
        ("Truncated at the token cap", [r.case_id for r in report.cases if r.truncated]),
        ("Citations invalid", [r.case_id for r in report.cases if not r.citations.passed]),
        ("Figures not exact", [r.case_id for r in report.cases if not r.figures.passed]),
        (
            "Coverage Gaps not stated",
            [r.case_id for r in report.cases if r.coverage_gaps and not r.coverage_gaps.passed],
        ),
    ):
        print(f"{label}: {', '.join(failing) or 'none'}", file=out)
    print(f"Answers with a Contradicted Claim: {o.answers_contradicted} of {o.cases}", file=out)
    for r in report.cases:
        if not r.contradictions.passed:
            print(
                f"Contradicted Claims in {r.case_id}: {' | '.join(r.contradictions.claims)}",
                file=out,
            )
    for r in report.cases:
        if not r.structure.passed:
            print(
                f"Structure not followed in {r.case_id}: {'; '.join(r.structure.problems)}",
                file=out,
            )
    for case_id, error in report.errors.items():
        print(f"Error in {case_id}: {error}", file=out)


if __name__ == "__main__":
    raise SystemExit(main())
