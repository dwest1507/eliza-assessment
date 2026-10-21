"""The offline re-score: saved reports scored again from their stored answers.

A saved generation report (`edgar_eval.generation.GenerationReport.to_dict`) stores each
answer and Jev's verdicts on its claims, so a corrected measurement is applied to it
offline, in place, with no Answer Call and no Jev call. A re-score fixes a measurement
and changes no choice, so it is allowed on the holdout. It does three things:

- **The figure check** (`rescore_figures`), redone against each case's Answer Context,
  prepared again through the report's Arm at the setting it records.
- **The Coverage Gap claims** (`rescore_gap_claims`): Jev's stored verdicts on cited
  sentences stating one of the case's expected Coverage Gaps are dropped, as the harness
  now keeps those sentences from Jev (`edgar_eval.answer_checks.split_gap_claims`).
- **The uncited claims** (`rescore_uncited_claims`): the stored uncited claims the claim
  split (`edgar_eval.answer_checks.claims`) no longer makes are dropped. It never adds a
  claim the split newly makes, since that would rewrite a round's recorded claims rather
  than fix a measurement.

A Brief Suite report (`edgar_eval.brief_suite.BriefSuiteReport.to_dict`) gets the last
two in every run's report, and each case's verdict is recomputed (`rescore_brief_suite`).

The scores that rest on what changed are recomputed by the harness's own rules, so the
two can't drift apart: an answer's pass (`edgar_eval.generation.answer_passes`), its
Contradicted Claims (`ContradictionCheck`), its Faithfulness
(`edgar_eval.judge.faithfulness_score`), a summary's mean (`mean_score`) and a Brief Suite
case's verdict (`edgar_eval.brief_suite.case_passes`).

`make eval-rescore` runs it:

    python -m edgar_eval.rescore [--split dev|holdout|all] [--all] [REPORT ...]

With no REPORT it re-scores the current round's reports in `data/derived/eval/`: the
shipped run (`generation-<split>.json`), the Control Run (`generation-control-<split>.json`)
and the Brief Suite (`brief-suite.json`). Other reports, such as the comparisons a round
recorded, are re-scored only when named (a path, or a name in that directory), and
`--all` re-scores every saved generation and Brief Suite report.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from pathlib import Path
from statistics import fmean
from typing import TextIO

from edgar_eval.answer_checks import (
    CitationCheck,
    Claim,
    CoverageGapCheck,
    claims,
    split_gap_claims,
)
from edgar_eval.brief_suite import case_passes
from edgar_eval.generation import (
    ContradictionCheck,
    FactValues,
    answer_passes,
    check_answer_figures,
    corpus_fact_values,
    mean_score,
)
from edgar_eval.judge import faithfulness_score
from edgar_eval.retrieval import Arm, Prepare, conversation
from edgar_rag.golden_set import (
    DEFAULT_BRIEF_SUITE,
    DEFAULT_GOLDEN_SET,
    GOLDEN_SET_FILES,
    GOLDEN_SET_V1,
    GOLDEN_SET_V2,
    GoldenCase,
    load_brief_suite,
    load_golden_set,
)
from edgar_rag.paths import DERIVED_DIR, REPO_ROOT
from edgar_rag.retrieval import (
    CONTEXT_BUDGET_TOKENS,
    DEFAULT_INDEX,
    index_chunk_tokens,
    prepare_answer_context,
)

__all__ = [
    "DEFAULT_EVAL_DIR",
    "index_for",
    "main",
    "named_report",
    "rescore_brief_suite",
    "rescore_figures",
    "rescore_gap_claims",
    "rescore_uncited_claims",
    "round_reports",
    "saved_reports",
    "stored_contradictions",
]

DEFAULT_EVAL_DIR = DERIVED_DIR / "eval"
"""Where the harnesses write their reports."""


# --- Generation reports -------------------------------------------------------------------


def rescore_figures(
    report: dict,
    cases: Iterable[GoldenCase],
    index: str | Path,
    *,
    fact_values: FactValues,
    prepare: Prepare = prepare_answer_context,
) -> dict:
    """A saved generation report with its figure check redone from its stored answers,
    and its figures-exact scores recomputed. Nothing else changes.

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
        case["figures"] = asdict(
            check_answer_figures(
                case["answer"], context.sources, fact_values, context.financial_facts
            )
        )

    def figures_exact(group: Iterable[dict]) -> float:
        return fmean(not c["figures"]["unmatched"] for c in group)

    rescored["overall"]["figures_exact"] = figures_exact(rescored["cases"])
    for kind, summary in rescored["by_type"].items():
        summary["figures_exact"] = figures_exact(
            c for c in rescored["cases"] if c["question_type"] == kind
        )
    return rescored


def rescore_gap_claims(report: dict, cases: Iterable[GoldenCase]) -> dict:
    """A saved generation report with Jev's stored verdicts on its Coverage Gap claims
    dropped, as the harness now keeps those claims from Jev
    (`edgar_eval.answer_checks.split_gap_claims`, ADR 0013's 2026-10-17 note).

    Each dropped claim moves to its case's `gap_claims`, so a reviewer still sees it, and
    the scores that rest on the claims judged are recomputed: the case's Faithfulness,
    Contradicted Claims and pass, and the Faithfulness and answers contradicted of each
    summary that holds it. A field the report never had is not added, except
    `gap_claims`. Jev's instructions do not change, so no claim is judged again and no
    Jev call is made; a Faithfulness judgment that failed stays failed."""
    by_id = {c.id: c for c in cases}
    rescored = json.loads(json.dumps(report))
    changed: set[str] = set()
    for case in rescored["cases"]:
        judgments = case["judgments"]
        stored = [
            Claim(c["claim"], tuple(c["tags"]), c.get("heading", ""), c.get("table_header", ""))
            for c in judgments["claims"]
        ]
        _, kept = split_gap_claims(stored, by_id[case["case_id"]].expected_coverage_gaps)
        case["gap_claims"] = case.get("gap_claims", []) + [asdict(c) for c in kept]
        if not kept:
            continue
        judgments["claims"] = [
            judged
            for judged, claim in zip(judgments["claims"], stored, strict=True)
            if claim not in kept
        ]
        case["faithfulness"] = _faithfulness(case)
        contradictions = _contradictions(case)
        if "contradictions" in case:
            case["contradictions"] = asdict(contradictions) | {
                "count": contradictions.count,
                "passed": contradictions.passed,
            }
        if "passed" in case:
            case["passed"] = _passed(case, contradictions)
        changed.add(case["question_type"])
    _resummarise(rescored, changed)
    return rescored


def rescore_uncited_claims(report: dict) -> dict:
    """A saved generation report with the uncited claims the claim split
    (`edgar_eval.answer_checks.claims`) no longer makes dropped from its stored verdicts,
    as when the claim exemption comes to recognise a refusal.

    Each stored answer is split again. A stored claim that cites no Source was never sent
    to Jev, only counted unsupported, so dropping one makes no Jev call; it is dropped
    when the split of the same answer no longer makes it as an uncited claim, and kept
    otherwise. Cited claims are never touched, and no claim is added: a claim the split
    newly makes would rewrite a round's recorded claims, not fix a measurement. The
    Faithfulness of each changed case, and of the summaries holding it, is recomputed;
    an uncited claim is never contradicted, so nothing else changes."""
    rescored = json.loads(json.dumps(report))
    changed: set[str] = set()
    for case in rescored["cases"]:
        stored = case["judgments"]["claims"]
        made = Counter(c.text for c in claims(case["answer"]) if not c.tags)
        kept = []
        for judged in stored:
            if not judged["tags"]:
                if not made[judged["claim"]]:
                    continue
                made[judged["claim"]] -= 1
            kept.append(judged)
        if len(kept) == len(stored):
            continue
        case["judgments"]["claims"] = kept
        case["faithfulness"] = _faithfulness(case)
        changed.add(case["question_type"])
    _resummarise(rescored, changed)
    return rescored


def stored_contradictions(case: dict) -> list[str]:
    """A saved case's Contradicted Claims, read from its stored verdicts."""
    return list(_contradictions(case).claims)


def _contradictions(case: dict) -> ContradictionCheck:
    """A saved case's Contradicted Claims, by the harness's rule."""
    return ContradictionCheck.from_verdicts(
        (c["claim"], c["verdict"]) for c in case["judgments"]["claims"]
    )


def _faithfulness(case: dict) -> float | None:
    """A saved case's Faithfulness, from its stored verdicts, by the harness's rule."""
    judgments = case["judgments"]
    return faithfulness_score(
        [c["verdict"] for c in judgments["claims"]],
        failed=any(f["judgment"] == "faithfulness" for f in judgments.get("failures", ())),
    )


def _passed(case: dict, contradictions: ContradictionCheck) -> bool:
    """Whether a saved case's answer passes, by the harness's rule."""
    citations, gaps = case["citations"], case["coverage_gaps"]
    return answer_passes(
        truncated=case.get("truncated", False),
        citations=CitationCheck(tuple(citations["unknown_tags"]), tuple(citations["uncited"])),
        coverage_gaps=None
        if gaps is None
        else CoverageGapCheck(tuple(gaps.get("stated", ())), tuple(gaps["missing"])),
        contradictions=contradictions,
    )


def _resummarise(report: dict, kinds: set[str]) -> None:
    """Recompute, from its cases, the Faithfulness and (when the report records it) the
    answers contradicted of the overall summary and of each question type's in `kinds`,
    the types whose cases changed. Nothing is recomputed when none did."""

    def summarise(summary: dict, group: list[dict]) -> None:
        summary["faithfulness"] = mean_score(map(_faithfulness, group))
        if "answers_contradicted" in summary:
            summary["answers_contradicted"] = sum(not _contradictions(c).passed for c in group)

    if kinds:
        summarise(report["overall"], report["cases"])
    for kind in kinds:
        summarise(
            report["by_type"][kind], [c for c in report["cases"] if c["question_type"] == kind]
        )


# --- Brief Suite reports ------------------------------------------------------------------


def rescore_brief_suite(report: dict, cases: Sequence[GoldenCase]) -> dict:
    """A saved Brief Suite report with Jev's stored verdicts on its Coverage Gap claims,
    and the uncited claims the claim split no longer makes, dropped from every run's
    report (`rescore_gap_claims`, `rescore_uncited_claims`), and each case's Contradicted
    Claims and verdict, and the cases passed, recomputed from them. No Answer Call and no
    Jev call."""
    rescored = json.loads(json.dumps(report))
    rescored["run_reports"] = [
        rescore_uncited_claims(rescore_gap_claims(r, cases)) for r in rescored["run_reports"]
    ]
    for case in rescored["cases"]:
        case["contradicted"] = [
            {"run": run, "claims": claims}
            for run, r in enumerate(rescored["run_reports"], start=1)
            for result in r["cases"]
            if result["case_id"] == case["case_id"] and (claims := stored_contradictions(result))
        ]
        case["passed"] = case_passes(
            missed=bool(case["missed"]),
            contradicted=bool(case["contradicted"]),
            answered_runs=case["runs"] - len(case["errors"]),
            runs=case["runs"],
        )
    rescored["cases_passed"] = sum(c["passed"] for c in rescored["cases"])
    return rescored


# --- Which reports ------------------------------------------------------------------------


def round_reports(eval_dir: Path = DEFAULT_EVAL_DIR, split: str = "dev") -> list[Path]:
    """The current round's saved reports in `eval_dir`, those that exist: the shipped run,
    the Control Run and the Brief Suite. A round's comparison reports are left out, so
    they stand as recorded unless named."""
    names = (f"generation-{split}.json", f"generation-control-{split}.json", "brief-suite.json")
    return [eval_dir / name for name in names if (eval_dir / name).exists()]


def saved_reports(eval_dir: Path = DEFAULT_EVAL_DIR) -> list[Path]:
    """Every saved generation report in `eval_dir`, the prompt iterations' included, and
    every saved Brief Suite report."""
    return [
        *sorted(eval_dir.glob("generation-*.json")),
        *sorted(eval_dir.glob("prompt-iterations/generation-*.json")),
        *sorted(eval_dir.glob("brief-suite*.json")),
    ]


def named_report(name: str, eval_dir: Path) -> Path | None:
    """A report named on the command line: a path as given, from the repository root, or
    a name in `eval_dir`."""
    for path in (Path(name), REPO_ROOT / name, eval_dir / name):
        if path.is_file():
            return path
    return None


# --- Command line -------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    fact_values: FactValues | None = None,
    arms: Sequence[Arm] | None = None,
    out: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(
        description="Re-score saved generation and Brief Suite reports from their stored "
        "answers, in place, with no Answer Call and no Jev call."
    )
    parser.add_argument(
        "reports",
        nargs="*",
        metavar="REPORT",
        help="reports to re-score: a path, or a name in --dir (default: the current "
        "round's shipped run, Control Run and Brief Suite)",
    )
    parser.add_argument("--all", action="store_true", help="re-score every saved report in --dir")
    parser.add_argument(
        "--split",
        choices=("dev", "holdout", "all"),
        default="dev",
        help="the split whose round reports are re-scored by default",
    )
    parser.add_argument(
        "--dir", type=Path, default=DEFAULT_EVAL_DIR, help="where the reports are saved"
    )
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="the shipped index")
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=DEFAULT_GOLDEN_SET,
        help="a Golden Set file (default: version 2); each report is re-scored against "
        "the version it records",
    )
    parser.add_argument(
        "--brief-suite",
        type=Path,
        default=DEFAULT_BRIEF_SUITE,
        metavar="PATH",
        help="the Brief Suite file a Brief Suite report was answered from",
    )
    args = parser.parse_args(argv)
    if args.all and args.reports:
        parser.error("name reports or pass --all, not both")
    if args.all:
        paths = saved_reports(args.dir)
    elif args.reports:
        found = {name: named_report(name, args.dir) for name in args.reports}
        missing = [name for name, path in found.items() if path is None]
        if missing:
            parser.error(f"no such report: {', '.join(missing)}")
        paths = [path for path in found.values() if path is not None]
    else:
        paths = round_reports(args.dir, args.split)
    if not paths:
        print(f"No saved generation or Brief Suite reports to re-score in {args.dir}.", file=out)
        return 0

    if arms is None:
        from edgar_eval.arms import ARMS

        arms = ARMS
    by_name = {a.name: a for a in arms}
    shipped = next(a for a in arms if a.shipped)
    golden = load_golden_set(args.golden_set)
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        if "run_reports" in report:
            # The suite's cases replace version 1 cases, whichever Golden Set file is named.
            golden_sets = dict.fromkeys((GOLDEN_SET_V1, GOLDEN_SET_V2, args.golden_set))
            suite = load_brief_suite(args.brief_suite, golden_sets)
            rescored = rescore_brief_suite(report, suite.cases)
            path.write_text(json.dumps(rescored, indent=2) + "\n", encoding="utf-8")
            runs = (report["run_reports"], rescored["run_reports"])
            print(
                f"{path}: {_gap_claims_line(*runs)}; {_uncited_claims_line(*runs)}; "
                f"cases passed {report['cases_passed']} → {rescored['cases_passed']}",
                file=out,
            )
            continue
        saved_arm = by_name[report["arm"]] if report.get("arm") else shipped
        # Each report against its own Golden Set version (version 1 if it records none,
        # as reports from before the version was recorded): the file named if it is that
        # version, else that version's own file.
        version = report.get("golden_set_version", 1)
        own = golden if golden.version == version else None
        own_cases = (own or load_golden_set(GOLDEN_SET_FILES[version])).cases
        rescored = rescore_figures(
            report,
            own_cases,
            index_for(args.index, report.get("chunk_tokens")),
            fact_values=fact_values or corpus_fact_values,
            prepare=saved_arm.prepare or prepare_answer_context,
        )
        rescored = rescore_uncited_claims(rescore_gap_claims(rescored, own_cases))
        path.write_text(json.dumps(rescored, indent=2) + "\n", encoding="utf-8")
        was, now = report["overall"]["figures_exact"], rescored["overall"]["figures_exact"]
        failing = [c["case_id"] for c in rescored["cases"] if c["figures"]["unmatched"]]
        print(
            f"{path}: figures exact {was:.2f} → {now:.2f}; "
            f"not exact: {', '.join(failing) or 'none'}; "
            f"{_gap_claims_line([report], [rescored])}; "
            f"{_uncited_claims_line([report], [rescored])}",
            file=out,
        )
    return 0


def index_for(index: Path, chunk_tokens: int | None) -> Path:
    """The index a saved report's Answer Contexts are rebuilt from: `index`, or, for a
    report answered from chunks of another size, the index of that size beside it
    (`edgar_rag-chunks450.sqlite`, as `make eval-generation CHUNK_TOKENS=450` builds it)
    when it exists. Without it, `rescore_figures` refuses the report."""
    if chunk_tokens is None or not index.exists() or chunk_tokens == index_chunk_tokens(index):
        return index
    other = index.with_name(f"{index.stem}-chunks{chunk_tokens}{index.suffix}")
    return other if other.exists() else index


def _gap_claims_line(before: Sequence[dict], after: Sequence[dict]) -> str:
    """What a re-score changed in saved generation reports (a Brief Suite's runs, or one
    report): the Coverage Gap claims it kept from Jev, and the Contradicted Claims and
    answers contradicted before and after."""

    def counts(reports: Sequence[dict]) -> tuple[int, int, int]:
        cases = [c for r in reports for c in r["cases"]]
        return (
            sum(len(c.get("gap_claims", ())) for c in cases),
            sum(_contradictions(c).count for c in cases),
            sum(not _contradictions(c).passed for c in cases),
        )

    (kept_was, claims_was, answers_was), (kept, claims_now, answers_now) = map(
        counts, (before, after)
    )
    noun = "claim" if kept - kept_was == 1 else "claims"
    return (
        f"{kept - kept_was} Coverage Gap {noun} kept from Jev; Contradicted Claims "
        f"{claims_was} → {claims_now}, answers contradicted {answers_was} → {answers_now}"
    )


def _uncited_claims_line(before: Sequence[dict], after: Sequence[dict]) -> str:
    """What a re-score's claim split changed in saved generation reports (a Brief Suite's
    runs, or one report): the uncited claims it dropped, and the Faithfulness before and
    after (for a Brief Suite, the mean of its runs')."""

    def counts(reports: Sequence[dict]) -> tuple[int, str]:
        uncited = sum(
            not claim["tags"]
            for r in reports
            for c in r["cases"]
            for claim in c["judgments"]["claims"]
        )
        faithfulness = mean_score(r["overall"]["faithfulness"] for r in reports)
        return uncited, "–" if faithfulness is None else f"{faithfulness:.2f}"

    (was, faithful_was), (now, faithful_now) = counts(before), counts(after)
    noun = "claim" if was - now == 1 else "claims"
    return (
        f"{was - now} uncited {noun} no longer made dropped; "
        f"Faithfulness {faithful_was} → {faithful_now}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
