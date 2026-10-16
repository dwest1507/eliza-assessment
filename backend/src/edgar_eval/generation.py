"""The generation harness: answer Golden Set cases end to end and score the answers.

Each case's conversation goes through the full pipeline: `prepare_answer_context`, with
the ranker of the retrieval Arm under test (the Shipped Arm by default), then one Answer
Call to the generator under test. The answer is then scored three ways:

- **In code** (`edgar_eval.answer_checks`): citation validity, figure exactness,
  Coverage Gap statements, and the answer's structure (assumption 8).
- **By Jev** (`edgar_eval.judge`), pinned to an exact version: Fact Recall against the
  case's Required Facts, and Faithfulness of each claim to the Sources it cites.
- **Cost and latency**, from the Answer Call's logged record: its token usage priced
  per model (`PRICES`), and its latency to the first text and to the end.

`make eval-generation` runs it on the dev split with the default generator, prints the
scores and writes them, with every answer, as JSON under `data/derived/eval/`:

    python -m edgar_eval.generation [--split dev|holdout|all] [--model MODEL] [--arm ARM]
        [--json PATH]

It calls the generator and Jev, so it needs `OPENAI_API_KEY` and `JEV_API_KEY`, and it
costs money: about a cent per case with `gpt-6-luna`.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
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
from edgar_eval.judge import Evidence, Judgments
from edgar_eval.retrieval import Arm, Prepare, conversation
from edgar_rag.answer_model import DEFAULT_ANSWER_LOG, AnswerCall, AnswerModel
from edgar_rag.golden_set import DEFAULT_GOLDEN_SET, GoldenCase, load_golden_set
from edgar_rag.retrieval import DEFAULT_INDEX, prepare_answer_context

__all__ = [
    "PRICES",
    "CaseResult",
    "GenerationReport",
    "Judge",
    "Price",
    "Summary",
    "answer_cost",
    "company_names",
    "evaluate",
    "main",
]

DEFAULT_SECTORS = Path(__file__).resolve().parents[3] / "data" / "reference" / "sectors.csv"


@dataclass(frozen=True)
class Price:
    """A model's list price in US dollars per million tokens."""

    input: float
    output: float


PRICES: dict[str, Price] = {
    "gpt-6-luna": Price(input=0.10, output=0.50),
    "gpt-6.1-sol": Price(input=2.00, output=10.00),
}
"""Standard-tier list prices per million tokens (developers.openai.com/api/docs/pricing,
2026-10-16). Reasoning tokens are billed as output and are already counted in the output
tokens. Every input token is priced at the full rate, ignoring cached input, so a cost
is an upper bound. The Anthropic models join with the generator comparison."""


def answer_cost(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """One Answer Call's cost in US dollars, or None if the model has no price or the
    provider reported no usage."""
    price = PRICES.get(model)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * price.input + output_tokens * price.output) / 1_000_000


class Judge(Protocol):
    """What the harness needs from a judge: `edgar_eval.judge.JevJudge`, or a fake."""

    def judge(
        self,
        answer: str,
        required_facts: Sequence[str],
        claims: Sequence[Claim],
        sources: dict[str, Evidence],
    ) -> Judgments: ...


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

    @property
    def fact_recall(self) -> float | None:
        return self.judgments.fact_recall

    @property
    def faithfulness(self) -> float | None:
        return self.judgments.faithfulness


@dataclass(frozen=True)
class Summary:
    """Scores over a group of cases. A score is None when no case in the group has
    anything to score for it (no Required Fact, no expected Coverage Gap)."""

    cases: int
    citations_valid: float
    """Share of answers whose every tag is a listed Source and every unit cites one."""
    figures_exact: float
    """Share of answers whose every figure matches a Financial Fact or a cited passage."""
    coverage_gaps_stated: float | None
    """Share of answers with expected Coverage Gaps that state every one of them."""
    structure_followed: float
    """Share of answers in the PE-analyst structure of assumption 8."""
    mean_words: float
    fact_recall: float | None
    """Mean share of Required Facts stated, over cases with Required Facts."""
    faithfulness: float | None
    """Mean share of claims supported by their cited Sources, over answers with claims."""
    mean_cost_usd: float | None
    total_cost_usd: float | None
    mean_latency_s: float
    max_latency_s: float
    mean_first_token_s: float | None
    mean_input_tokens: float | None
    mean_output_tokens: float | None
    judge_cost_usd: float


@dataclass(frozen=True)
class GenerationReport:
    model: str
    judge_model: str
    prompt_version: str
    overall: Summary
    by_type: dict[str, Summary]
    cases: tuple[CaseResult, ...]
    errors: dict[str, str]
    """Cases that could not be answered or judged, with the error."""
    arm: str | None = None
    """The retrieval Arm the Answer Contexts came from."""

    def to_dict(self) -> dict:
        """The report as plain JSON-ready data, with each case's derived scores."""
        data = asdict(self)
        for case, result in zip(data["cases"], self.cases, strict=True):
            case["fact_recall"] = result.fact_recall
            case["faithfulness"] = result.faithfulness
            case["judgments"]["judge_cost_usd"] = result.judgments.cost_usd
        return data


FactValues = Callable[[Iterable[str]], list[int]]
"""The Financial Facts' values, in whole US dollars, of the given tickers."""


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
) -> GenerationReport:
    """Answer every case with the model, score each answer, and summarise the scores
    overall and per question type. Cases run `workers` at a time. `prepare` is the
    retrieval Arm's (`arm`) way of preparing the Answer Context."""

    def run(case: GoldenCase) -> CaseResult | str:
        try:
            return _run_case(case, model, judge, Path(index), names, fact_values, log_path, prepare)
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
) -> CaseResult:
    context = prepare(conversation(case), index)
    call = AnswerCall(context, model, log_path=log_path)
    answer = "".join(call)
    record = call.record
    assert record is not None
    if not record.completed:
        raise RuntimeError("the Answer Call stopped before the end of its stream")

    tickers = {c.ticker for c in context.query_scope.companies} | {
        s.ticker for s in context.sources
    }
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
        figures=check_figures(answer, passages, fact_values(tickers)),
        coverage_gaps=check_coverage_gaps(answer, gaps, names) if gaps else None,
        judgments=judge.judge(
            answer, [f.fact for f in case.required_facts], claims(answer), evidence
        ),
        structure=check_structure(answer, covered),
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
        faithfulness=mean(r.faithfulness for r in results),
        mean_cost_usd=fmean(priced) if priced else None,
        total_cost_usd=sum(priced) if priced else None,
        mean_latency_s=mean(r.latency_s for r in results) or 0.0,
        max_latency_s=max((r.latency_s for r in results), default=0.0),
        mean_first_token_s=mean(r.first_token_s for r in results),
        mean_input_tokens=mean(r.input_tokens for r in results),
        mean_output_tokens=mean(r.output_tokens for r in results),
        judge_cost_usd=sum(r.judgments.cost_usd for r in results),
    )


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


def company_names(path: str | Path = DEFAULT_SECTORS) -> dict[str, tuple[str, ...]]:
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
                values.setdefault(fact.ticker, []).append(fact.value)
    return {ticker: tuple(v) for ticker, v in values.items()}


def corpus_fact_values(tickers: Iterable[str]) -> list[int]:
    """The values of every Financial Fact the Corpus yields for the tickers. Financial
    Facts are extracted for Tracked Companies only (ADR 0001)."""
    facts = _all_fact_values()
    return [v for ticker in tickers for v in facts.get(ticker, ())]


# --- Command line -------------------------------------------------------------------------


def answer_model(name: str | None) -> AnswerModel:
    """The generator to test, by model id. OpenAI models only, until the Anthropic
    implementation joins for the generator comparison."""
    from edgar_answer.openai_model import MODEL_ENV_VAR, OpenAIAnswerModel

    name = name or os.environ.get(MODEL_ENV_VAR)
    if name and not name.startswith("gpt-"):
        raise SystemExit(f"error: no answer model implementation for {name!r} yet")
    return OpenAIAnswerModel(name)


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
    parser.add_argument("--model", help="the generator's model id (default: OPENAI_MODEL)")
    parser.add_argument("--arm", help="the retrieval Arm (default: the Shipped Arm)")
    parser.add_argument("--case", action="append", metavar="ID", help="only these cases")
    parser.add_argument("--workers", type=int, default=4, help="cases answered at once")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    parser.add_argument("--log", type=Path, default=DEFAULT_ANSWER_LOG, help="Answer Call log")
    parser.add_argument("--json", type=Path, help="also write the report as JSON here")
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
    ("faithful", lambda s: _share(s.faithfulness)),
    ("$/answer", lambda s: "–" if s.mean_cost_usd is None else f"{s.mean_cost_usd:.4f}"),
    ("latency s", lambda s: f"{s.mean_latency_s:.1f}"),
    ("first s", lambda s: "–" if s.mean_first_token_s is None else f"{s.mean_first_token_s:.1f}"),
)


def _share(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}"


def _print_report(report: GenerationReport, split: str, out: TextIO) -> None:
    print(
        f"Generation on the {split} split: {report.overall.cases} cases answered by "
        f"{report.model} (prompt {report.prompt_version}) on the {report.arm or '?'} Arm, "
        f"judged by {report.judge_model}",
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
    for label, failing in (
        ("Citations invalid", [r.case_id for r in report.cases if not r.citations.passed]),
        ("Figures not exact", [r.case_id for r in report.cases if not r.figures.passed]),
        (
            "Coverage Gaps not stated",
            [r.case_id for r in report.cases if r.coverage_gaps and not r.coverage_gaps.passed],
        ),
    ):
        print(f"{label}: {', '.join(failing) or 'none'}", file=out)
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
