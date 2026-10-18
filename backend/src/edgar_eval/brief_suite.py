"""The Brief Suite run: each case answered several times, and a pass/fail verdict per case.

The Brief Suite (`edgar_rag.golden_set.load_brief_suite`) is a must-pass check, not an
estimate (ADR 0012). It runs through the generation harness (`edgar_eval.generation`),
scored by the same checks and the same Jev judgments, `BRIEF_SUITE_RUNS` times. Each run
is one `evaluate` over every case, and every run's report is kept.

A case passes when every must-state Required Fact is stated in at least `PASS_RUNS` of
`BRIEF_SUITE_RUNS` runs (the same share of another run count, rounded up) and no run has
a Contradicted Claim. A run that could not be answered, whose Fact Recall judgment
failed, or whose answer was cut off at the token cap states no fact, so it counts
against the case. Details are reported and never fail it.

Cases are reported one by one, never averaged: for each, the verdict, every Required
Fact with the runs that stated it and the runs whose Answer Context its evidence quote
reached (Evidence Reached, which tells a retrieval miss from a generation miss), and the
Contradicted Claims of each run.

`make eval-brief` runs it (`python -m edgar_eval.generation --brief-suite`). It makes
`BRIEF_SUITE_RUNS` paid Answer Calls per case, so the generation harness prints
`estimate_cost` before the first one.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO

from edgar_eval.generation import (
    CaseResult,
    GenerationReport,
    Judge,
    evaluate,
    rescore_gap_claims,
    stored_contradictions,
)
from edgar_eval.generators import answer_cost
from edgar_eval.judge import JEV_USD_PER_MILLION_INPUT_TOKENS
from edgar_rag.answer_model import AnswerModel
from edgar_rag.golden_set import GoldenCase, Tier

__all__ = [
    "BRIEF_SUITE_RUNS",
    "ESTIMATED_JUDGE_TOKENS",
    "ESTIMATED_OUTPUT_TOKENS",
    "ESTIMATED_PROMPT_TOKENS",
    "PASS_RUNS",
    "BriefCaseVerdict",
    "BriefSuiteReport",
    "CostEstimate",
    "FactVerdict",
    "RunClaims",
    "RunError",
    "estimate_cost",
    "evaluate_brief_suite",
    "print_brief_suite_report",
    "required_runs",
    "rescore_brief_gap_claims",
]

BRIEF_SUITE_RUNS = 5
"""How many times each Brief Suite case is answered in a run of the suite."""

PASS_RUNS = 4
"""Of `BRIEF_SUITE_RUNS` runs, how many must state each must-state Required Fact."""


def required_runs(runs: int) -> int:
    """How many of `runs` runs must state a must-state fact: `PASS_RUNS` of
    `BRIEF_SUITE_RUNS`, the same share of any other run count, rounded up."""
    return math.ceil(runs * PASS_RUNS / BRIEF_SUITE_RUNS)


@dataclass(frozen=True)
class FactVerdict:
    """One Required Fact over every run of its case."""

    fact: str
    tier: Tier
    runs: int
    stated_runs: int
    """Runs whose answer Jev judged to state the fact."""
    evidence_reached_runs: int
    """Runs whose Answer Context held the fact's evidence quote (Evidence Reached)."""

    @property
    def passed(self) -> bool:
        """A must-state fact passes when stated in enough runs; a detail always does."""
        return self.tier != "must_state" or self.stated_runs >= required_runs(self.runs)


@dataclass(frozen=True)
class RunClaims:
    """The Contradicted Claims of one run's answer (runs count from 1)."""

    run: int
    claims: tuple[str, ...]


@dataclass(frozen=True)
class RunError:
    """A run in which the case could not be answered or judged."""

    run: int
    error: str


@dataclass(frozen=True)
class BriefCaseVerdict:
    case_id: str
    question: str
    runs: int
    facts: tuple[FactVerdict, ...]
    contradicted: tuple[RunClaims, ...]
    """The runs whose answer has a Contradicted Claim, with those claims."""
    truncated_runs: tuple[int, ...]
    """The runs whose answer stopped at the token cap; they state no fact."""
    errors: tuple[RunError, ...]
    """The runs in which the case could not be answered at all."""
    judgment_failures: tuple[RunError, ...] = ()
    """The Jev judgments that failed, by run. A failed Fact Recall judgment states no
    fact; a failed Faithfulness judgment leaves its claims unjudged, so a contradiction
    among them would not be seen."""

    @property
    def answered_runs(self) -> int:
        return self.runs - len(self.errors)

    @property
    def missed(self) -> tuple[FactVerdict, ...]:
        """The must-state facts stated in too few runs."""
        return tuple(f for f in self.facts if not f.passed)

    @property
    def passed(self) -> bool:
        """Every must-state fact stated in enough runs, no run with a Contradicted Claim,
        and enough runs answered at all (which matters for a case with no fact)."""
        return (
            not self.missed
            and not self.contradicted
            and self.answered_runs >= required_runs(self.runs)
        )


@dataclass(frozen=True)
class BriefSuiteReport:
    runs: int
    cases: tuple[BriefCaseVerdict, ...]
    run_reports: tuple[GenerationReport, ...]
    """Each run's generation report, with every answer and its scores."""

    @property
    def model(self) -> str:
        return self.run_reports[0].model if self.run_reports else ""

    @property
    def judge_model(self) -> str:
        return next((r.judge_model for r in self.run_reports if r.judge_model), "")

    @property
    def prompt_version(self) -> str:
        return next((r.prompt_version for r in self.run_reports if r.prompt_version), "")

    @property
    def passed(self) -> int:
        return sum(c.passed for c in self.cases)

    def to_dict(self) -> dict:
        """The report as plain JSON-ready data, with each case's and fact's verdict."""
        first = self.run_reports[0] if self.run_reports else None
        cases = []
        for case in self.cases:
            data = asdict(case) | {
                "passed": case.passed,
                "missed": [f.fact for f in case.missed],
            }
            for fact, verdict in zip(data["facts"], case.facts, strict=True):
                fact["passed"] = verdict.passed
            cases.append(data)
        return {
            "runs": self.runs,
            "pass_runs": required_runs(self.runs),
            "model": self.model,
            "judge_model": self.judge_model,
            "prompt_version": self.prompt_version,
            "arm": first.arm if first else None,
            "settings": first.settings if first else None,
            "cases_passed": self.passed,
            "cases": cases,
            "run_reports": [r.to_dict() for r in self.run_reports],
        }


def evaluate_brief_suite(
    cases: Sequence[GoldenCase],
    model: AnswerModel,
    judge: Judge,
    index: str | Path,
    *,
    runs: int = BRIEF_SUITE_RUNS,
    **settings,
) -> BriefSuiteReport:
    """Answer every case `runs` times through `edgar_eval.generation.evaluate` (one
    evaluate per run, with `settings` passed on) and give each case its verdict."""
    if runs < 1:
        raise ValueError("the Brief Suite needs at least one run")
    reports = tuple(evaluate(cases, model, judge, index, **settings) for _ in range(runs))
    return BriefSuiteReport(
        runs=runs,
        cases=tuple(_verdict(case, reports) for case in cases),
        run_reports=reports,
    )


def _verdict(case: GoldenCase, reports: Sequence[GenerationReport]) -> BriefCaseVerdict:
    results: list[tuple[int, CaseResult]] = []
    errors = []
    for run, report in enumerate(reports, start=1):
        result = next((r for r in report.cases if r.case_id == case.id), None)
        if result is None:
            errors.append(RunError(run, report.errors.get(case.id, "no result")))
        else:
            results.append((run, result))
    facts = tuple(
        FactVerdict(
            fact=fact.fact,
            tier=fact.tier,
            runs=len(reports),
            stated_runs=sum(_stated(r, i) for _, r in results),
            evidence_reached_runs=sum(_reached(r, i) for _, r in results),
        )
        for i, fact in enumerate(case.required_facts)
    )
    return BriefCaseVerdict(
        case_id=case.id,
        question=case.question,
        runs=len(reports),
        facts=facts,
        contradicted=tuple(
            RunClaims(run, r.contradictions.claims)
            for run, r in results
            if not r.contradictions.passed
        ),
        truncated_runs=tuple(run for run, r in results if r.truncated),
        errors=tuple(errors),
        judgment_failures=tuple(
            RunError(run, f"{failure.judgment}: {failure.error}")
            for run, r in results
            for failure in r.judgments.failures
        ),
    )


def rescore_brief_gap_claims(report: dict, cases: Sequence[GoldenCase]) -> dict:
    """A saved Brief Suite report (`BriefSuiteReport.to_dict`) with Jev's stored verdicts
    on its Coverage Gap claims dropped from every run's report
    (`edgar_eval.generation.rescore_gap_claims`), and each case's Contradicted Claims,
    verdict and the cases passed recomputed from them. No Answer Call and no Jev call."""
    rescored = json.loads(json.dumps(report))
    rescored["run_reports"] = [rescore_gap_claims(r, cases) for r in rescored["run_reports"]]
    for case in rescored["cases"]:
        case["contradicted"] = [
            {"run": run, "claims": claims}
            for run, r in enumerate(rescored["run_reports"], start=1)
            for result in r["cases"]
            if result["case_id"] == case["case_id"] and (claims := stored_contradictions(result))
        ]
        case["passed"] = (
            not case["missed"]
            and not case["contradicted"]
            and case["runs"] - len(case["errors"]) >= rescored["pass_runs"]
        )
    rescored["cases_passed"] = sum(c["passed"] for c in rescored["cases"])
    return rescored


def _stated(result: CaseResult, i: int) -> bool:
    """Whether the run's answer states the case's i-th Required Fact, by the harness's
    rule (`CaseResult.facts_stated`: a truncated answer states none). One whose Fact
    Recall judgment failed judged no fact, and so states none either."""
    stated = result.facts_stated
    return stated is not None and stated[i]


def _reached(result: CaseResult, i: int) -> bool:
    return bool(result.evidence_reached) and result.evidence_reached[i]


# --- The cost estimate --------------------------------------------------------------------

ESTIMATED_PROMPT_TOKENS = 4_000
"""Input tokens an Answer Call spends beyond its Sources (the instructions, the question,
earlier turns and Source labels), with room for tokenizers that count more. Version 1's
saved reports average 21k to 34k input tokens against a 32k context budget."""

ESTIMATED_OUTPUT_TOKENS = 2_000
"""Output tokens per Answer Call: above version 1's averages (0.5k to 1.7k)."""

ESTIMATED_JUDGE_TOKENS = 8_000
"""Jev input tokens per answer beyond the context budget (the answer, its facts and
claims). Version 1 averaged about $0.0012 of Jev per answer, under 30k tokens."""


@dataclass(frozen=True)
class CostEstimate:
    """A paid run's estimated cost in US dollars: an upper bound, not a forecast."""

    model: str
    answers: int
    answer_usd: float | None
    """None when the model has no price in `edgar_eval.generators.GENERATORS`."""
    judge_usd: float

    @property
    def total_usd(self) -> float | None:
        return None if self.answer_usd is None else self.answer_usd + self.judge_usd

    def line(self) -> str:
        total = "–" if self.total_usd is None else f"${self.total_usd:.2f}"
        answers = "unpriced" if self.answer_usd is None else f"${self.answer_usd:.2f}"
        return (
            f"Estimated cost: up to {total} for {self.answers} Answer Calls with {self.model} "
            f"(answers {answers}, Jev judging ${self.judge_usd:.2f})"
        )


def estimate_cost(model: str, answers: int, context_budget: int) -> CostEstimate:
    """The estimated cost of `answers` Answer Calls with `model` at `context_budget`
    tokens of Sources each, and of Jev judging them."""
    one = answer_cost(model, context_budget + ESTIMATED_PROMPT_TOKENS, ESTIMATED_OUTPUT_TOKENS)
    judge = (context_budget + ESTIMATED_JUDGE_TOKENS) * JEV_USD_PER_MILLION_INPUT_TOKENS / 1e6
    return CostEstimate(
        model=model,
        answers=answers,
        answer_usd=None if one is None else one * answers,
        judge_usd=judge * answers,
    )


# --- The printed report -------------------------------------------------------------------


def print_brief_suite_report(report: BriefSuiteReport, out: TextIO) -> None:
    """Each case's verdict, one by one: its missed must-state facts, every Required Fact
    with the runs that stated it and that its evidence reached, and its Contradicted
    Claims. Never an average over cases."""
    first = report.run_reports[0] if report.run_reports else None
    need = required_runs(report.runs)
    print(
        f"Brief Suite: {_count(len(report.cases), 'case')}, {report.runs} runs each, answered by "
        f"{report.model} (prompt {report.prompt_version}) on the "
        f"{(first.arm if first else None) or '?'} Arm ({first.settings if first else '?'}), "
        f"judged by {report.judge_model}",
        file=out,
    )
    print(
        f"A case passes when every must-state Required Fact is stated in at least {need} of "
        f"{report.runs} runs and no run has a Contradicted Claim.",
        file=out,
    )
    for case in report.cases:
        print(f"\n{case.case_id}: {'PASS' if case.passed else 'FAIL'}", file=out)
        if case.missed:
            print(f"  Must-state facts stated in fewer than {need} of {case.runs} runs:", file=out)
            for fact in case.missed:
                print(f"    {_fact_line(fact)}", file=out)
        for run in case.contradicted:
            print(f"  Contradicted Claims in run {run.run}: {' | '.join(run.claims)}", file=out)
        if case.truncated_runs:
            runs = ", ".join(map(str, case.truncated_runs))
            print(f"  Cut off at the token cap in runs {runs}", file=out)
        for error in case.errors:
            print(f"  Not answered in run {error.run}: {error.error}", file=out)
        for failure in case.judgment_failures:
            print(f"  Jev judgment failed in run {failure.run}: {failure.error}", file=out)
        print("  Required Facts:", file=out)
        for fact in case.facts:
            print(f"    {fact.tier:<10}  {_fact_line(fact)}", file=out)
    print(f"\n{report.passed} of {len(report.cases)} cases pass.", file=out)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _fact_line(fact: FactVerdict) -> str:
    return (
        f"stated in {fact.stated_runs} of {fact.runs} runs, evidence reached in "
        f"{fact.evidence_reached_runs} of {fact.runs}: {fact.fact}"
    )
