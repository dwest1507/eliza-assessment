"""The retrieval harness: run Golden Set cases through each Arm and score the Sources.

Each case's conversation (its scripted history, then its question) goes to an Arm, which
returns the (Filing ID, Section) pairs of the Sources it would put in the Answer Call,
best first. The ranking is scored against the case's expected pairs with hit@k,
recall@k and MRR, overall and per question type. Multi-turn cases are scored on their
final turn. Cases with no expected pair (a Company missing from the Corpus, General
Electric today) have nothing to find and are listed as unscored.

For an Arm that prepares the whole Answer Context (every Arm in `edgar_eval.arms`), the
harness also counts **evidence reached**: the case's Required Facts whose evidence quote
appears, whitespace aside, in the text of the context's Sources. The Golden Set labels
relevance by Section, so a change of chunk size or context budget barely moves hit@k;
evidence reached shows whether the passages that state the facts reach the prompt (ADR
0010).

Every challenger Arm is compared with the Shipped Arm, case by case, by McNemar's exact
test on the gating metric (hit@`gate_k`).

`make eval-retrieval` runs every Arm in `edgar_eval.arms.ARMS` on the dev split, prints
the scores and writes them as JSON under `data/derived/eval/`. The index (and so its
chunk size) and the context budget can be chosen per run, and the report records both:

    python -m edgar_eval.retrieval [--split dev|holdout|all] [--index PATH]
        [--context-budget TOKENS] [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from itertools import zip_longest
from pathlib import Path
from statistics import fmean
from typing import TextIO

from edgar_eval.metrics import (
    McNemarResult,
    Pair,
    hit_at_k,
    mcnemar_exact,
    recall_at_k,
    reciprocal_rank,
)
from edgar_rag.golden_set import DEFAULT_GOLDEN_SET, GoldenCase, load_golden_set
from edgar_rag.retrieval import (
    CONTEXT_BUDGET_TOKENS,
    DEFAULT_INDEX,
    AnswerContext,
    Message,
    count_tokens,
    index_chunk_tokens,
)

DEFAULT_KS = (5, 10, 20)
DEFAULT_GATE_K = 10

Retrieve = Callable[..., list[Pair]]
"""`retrieve(messages, index, context_budget=...)`: the Sources' (Filing ID, Section)
pairs."""
Prepare = Callable[..., AnswerContext]
"""`prepare(messages, index, context_budget=...)`: the Answer Context."""


@dataclass(frozen=True)
class Arm:
    """One way of choosing an Answer Call's Sources."""

    name: str
    description: str
    retrieve: Retrieve
    """The conversation (ending with the question), the index and the context budget
    (keyword `context_budget`) in; the Sources' (Filing ID, Section) pairs out, best
    first, one per Source."""
    shipped: bool = False
    """True for the Arm the product uses, which every challenger is compared with."""
    prepare: Prepare | None = None
    """The Answer Context the Arm gives the Answer Call, from the same arguments as
    `retrieve`; None for an Arm measured by retrieval only. When there is one, the
    retrieval harness scores the Sources of the context it prepares."""


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    question_type: str
    sources: int
    """How many Sources the Arm returned: all of them reach the Answer Call."""
    first_hit_rank: int | None
    hit: dict[int, bool]
    recall: dict[int, float]
    hit_all: bool
    recall_all: float
    facts: int = 0
    """How many Required Facts the case has."""
    facts_reached: int | None = None
    """How many of them have their evidence quote in the Sources' text; None for an Arm
    measured by retrieval only."""
    source_tokens: int | None = None
    """Tokens of Source text in the Answer Context; None for an Arm measured by
    retrieval only."""


@dataclass(frozen=True)
class Summary:
    """Mean scores over a group of cases."""

    cases: int
    hit: dict[int, float]
    recall: dict[int, float]
    hit_all: float
    """Share of cases with an expected pair anywhere among the Sources."""
    recall_all: float
    """Share of expected pairs found anywhere among the Sources."""
    mrr: float
    mean_sources: float
    facts: int = 0
    """Required Facts of the cases."""
    facts_reached: int | None = None
    """Required Facts whose evidence quote reaches the Answer Context's Sources."""
    mean_source_tokens: float | None = None
    """Mean tokens of Source text per Answer Context."""


@dataclass(frozen=True)
class ArmScores:
    name: str
    shipped: bool
    overall: Summary
    by_type: dict[str, Summary]
    cases: tuple[CaseScore, ...]


@dataclass(frozen=True)
class Comparison:
    arm: str
    shipped_arm: str
    metric: str
    result: McNemarResult


@dataclass(frozen=True)
class RetrievalReport:
    ks: tuple[int, ...]
    gate_k: int
    gating_metric: str
    case_ids: tuple[str, ...]
    """The scored cases, in Golden Set order."""
    unscored: tuple[str, ...]
    arms: dict[str, ArmScores]
    comparisons: tuple[Comparison, ...] = field(default=())
    context_budget: int = CONTEXT_BUDGET_TOKENS
    """Tokens of Source text each Answer Context was allowed (ADR 0010)."""
    chunk_tokens: int | None = None
    """The chunk size of the index scored, when known (ADR 0010)."""

    def to_dict(self) -> dict:
        """The report as plain JSON-ready data."""
        return asdict(self)


def evaluate(
    cases: Sequence[GoldenCase],
    arms: Sequence[Arm],
    index: str | Path,
    ks: Sequence[int] = DEFAULT_KS,
    gate_k: int = DEFAULT_GATE_K,
    context_budget: int = CONTEXT_BUDGET_TOKENS,
    chunk_tokens: int | None = None,
) -> RetrievalReport:
    """Score every Arm on the cases, each Answer Context allowed `context_budget` tokens
    of Sources, and compare each challenger with the Shipped Arm. `chunk_tokens` is
    recorded in the report as the index's chunk size."""
    shipped = [arm for arm in arms if arm.shipped]
    if len(shipped) != 1:
        raise ValueError(f"exactly one Arm must be shipped, not {len(shipped)}")
    ks = tuple(sorted(set(ks) | {gate_k}))
    scored = [c for c in cases if c.expected_sources]
    scores = {arm.name: _score_arm(arm, scored, Path(index), ks, context_budget) for arm in arms}

    base = scores[shipped[0].name]
    comparisons = tuple(
        Comparison(
            arm=arm.name,
            shipped_arm=base.name,
            metric=f"hit@{gate_k}",
            result=mcnemar_exact(
                [c.hit[gate_k] for c in scores[arm.name].cases],
                [c.hit[gate_k] for c in base.cases],
            ),
        )
        for arm in arms
        if not arm.shipped
    )
    return RetrievalReport(
        ks=ks,
        gate_k=gate_k,
        gating_metric=f"hit@{gate_k}",
        case_ids=tuple(c.id for c in scored),
        unscored=tuple(c.id for c in cases if not c.expected_sources),
        arms=scores,
        comparisons=comparisons,
        context_budget=context_budget,
        chunk_tokens=chunk_tokens,
    )


def conversation(case: GoldenCase) -> list[Message]:
    """The case's scripted history followed by its question: the final turn to score."""
    return [Message(m.role, m.content) for m in case.history] + [Message("user", case.question)]


def source_ranking(context: AnswerContext) -> list[Pair]:
    """The Answer Context's text Sources as ranked (Filing ID, Section) pairs.

    Each Company in scope is retrieved separately with its own share of the context
    budget, and its Sources are numbered after the previous Company's. Ranking them by
    number would put the last Company's best Source behind every other Company's worst,
    so the ranking takes each Company's next-best Source in turn instead.

    Facts Sources are left out: they are Financial Facts looked up by rule, not text
    retrieved by an Arm, and the Golden Set labels Sections.
    """
    per_company: dict[str, list[Pair]] = {}
    for source in (s for s in context.sources if s.kind == "text"):
        per_company.setdefault(source.ticker, []).append((source.filing_id, source.section))
    return [
        pair for turn in zip_longest(*per_company.values()) for pair in turn if pair is not None
    ]


_SPACE = re.compile(r"\s+")


def _squeezed(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def _score_arm(
    arm: Arm, cases: Sequence[GoldenCase], index: Path, ks: tuple[int, ...], context_budget: int
) -> ArmScores:
    case_scores = tuple(_score_case(arm, case, index, ks, context_budget) for case in cases)
    by_type: dict[str, list[CaseScore]] = {}
    for score in case_scores:
        by_type.setdefault(score.question_type, []).append(score)
    return ArmScores(
        name=arm.name,
        shipped=arm.shipped,
        overall=_summarise(case_scores, ks),
        by_type={kind: _summarise(group, ks) for kind, group in by_type.items()},
        cases=case_scores,
    )


def _score_case(
    arm: Arm, case: GoldenCase, index: Path, ks: tuple[int, ...], context_budget: int
) -> CaseScore:
    reached = tokens = None
    if arm.prepare is not None:
        context = arm.prepare(conversation(case), index, context_budget=context_budget)
        ranked = source_ranking(context)
        text = _squeezed("\n".join(s.text for s in context.sources))
        reached = sum(_squeezed(f.evidence) in text for f in case.required_facts)
        tokens = sum(count_tokens(s.text) for s in context.sources)
    else:
        ranked = list(arm.retrieve(conversation(case), index, context_budget=context_budget))
    expected = {(s.filing_id, s.section) for s in case.expected_sources}
    rr = reciprocal_rank(ranked, expected)
    return CaseScore(
        case_id=case.id,
        question_type=case.question_type,
        sources=len(ranked),
        first_hit_rank=round(1 / rr) if rr else None,
        hit={k: hit_at_k(ranked, expected, k) for k in ks},
        recall={k: recall_at_k(ranked, expected, k) for k in ks},
        hit_all=hit_at_k(ranked, expected, None),
        recall_all=recall_at_k(ranked, expected, None),
        facts=len(case.required_facts),
        facts_reached=reached,
        source_tokens=tokens,
    )


def _summarise(scores: Sequence[CaseScore], ks: tuple[int, ...]) -> Summary:
    return Summary(
        cases=len(scores),
        hit={k: fmean(s.hit[k] for s in scores) for k in ks},
        recall={k: fmean(s.recall[k] for s in scores) for k in ks},
        hit_all=fmean(s.hit_all for s in scores),
        recall_all=fmean(s.recall_all for s in scores),
        mrr=fmean(1 / s.first_hit_rank if s.first_hit_rank else 0.0 for s in scores),
        mean_sources=fmean(s.sources for s in scores),
        facts=sum(s.facts for s in scores),
        facts_reached=None
        if any(s.facts_reached is None for s in scores)
        else sum(s.facts_reached or 0 for s in scores),
        mean_source_tokens=None
        if any(s.source_tokens is None for s in scores)
        else fmean(s.source_tokens or 0 for s in scores),
    )


def main(
    argv: list[str] | None = None,
    *,
    arms: Sequence[Arm] | None = None,
    out: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description="Score retrieval Arms on the Golden Set.")
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
    parser.add_argument(
        "--arm", action="append", metavar="NAME", help="only these Arms (and the shipped one)"
    )
    parser.add_argument("--k", type=int, nargs="+", default=list(DEFAULT_KS), metavar="K")
    parser.add_argument("--gate-k", type=int, default=DEFAULT_GATE_K, metavar="K")
    parser.add_argument(
        "--index", type=Path, default=DEFAULT_INDEX, help="the index, and so the chunk size"
    )
    parser.add_argument(
        "--context-budget",
        type=int,
        default=CONTEXT_BUDGET_TOKENS,
        metavar="TOKENS",
        help="tokens of Sources per Answer Context (ADR 0010)",
    )
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    parser.add_argument("--json", type=Path, help="also write the report as JSON here")
    args = parser.parse_args(argv)
    if arms is None:
        from edgar_eval.arms import ARMS

        arms = ARMS

    if args.arm:
        unknown = set(args.arm) - {arm.name for arm in arms}
        if unknown:
            parser.error(f"no such Arm: {', '.join(sorted(unknown))}")
        arms = [arm for arm in arms if arm.shipped or arm.name in args.arm]
    golden = load_golden_set(args.golden_set)
    try:
        golden.require_frozen()
    except ValueError as error:
        parser.error(str(error))
    cases = golden.cases if args.split == "all" else golden.split(args.split)
    report = evaluate(
        cases,
        arms,
        args.index,
        ks=args.k,
        gate_k=args.gate_k,
        context_budget=args.context_budget,
        chunk_tokens=index_chunk_tokens(args.index) if args.index.exists() else None,
    )
    _print_report(report, args.split, out)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        data = {"split": args.split, "golden_set_version": golden.version} | report.to_dict()
        args.json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"\nWritten to {args.json.resolve()}", file=out)
    return 0


def _print_report(report: RetrievalReport, split: str, out: TextIO) -> None:
    print(
        f"Retrieval on the {split} split: {len(report.case_ids)} cases scored, "
        f"{len(report.unscored)} with no expected Source ({', '.join(report.unscored)})",
        file=out,
    )
    chunks = f"{report.chunk_tokens}-token chunks" if report.chunk_tokens else "chunks"
    print(f"Settings: {chunks}, a context budget of {report.context_budget} tokens", file=out)
    print(f"Gating metric: {report.gating_metric}", file=out)
    headers = (
        ["", "cases"]
        + [f"hit@{k}" for k in report.ks]
        + ["hit@all"]
        + [f"recall@{k}" for k in report.ks]
        + ["recall@all", "MRR", "Sources", "tokens", "evidence"]
    )
    for scores in report.arms.values():
        print(f"\nArm {scores.name}{' (shipped)' if scores.shipped else ''}", file=out)
        rows = [("overall", scores.overall)] + sorted(scores.by_type.items())
        table = [headers] + [_row(name, summary, report.ks) for name, summary in rows]
        widths = [max(len(row[i]) for row in table) for i in range(len(headers))]
        for row in table:
            cells = [cell.rjust(width) for cell, width in zip(row, widths, strict=True)]
            print("  ".join([row[0].ljust(widths[0])] + cells[1:]), file=out)
        missed = [c.case_id for c in scores.cases if not c.hit[report.gate_k]]
        print(f"Missed at {report.gating_metric}: {', '.join(missed) or 'none'}", file=out)
    for comparison in report.comparisons:
        r = comparison.result
        print(
            f"\n{comparison.arm} vs {comparison.shipped_arm} on {comparison.metric}: "
            f"{r.verdict} ({r.challenger_only} cases only {comparison.arm} hit, "
            f"{r.shipped_only} only {comparison.shipped_arm} hit, exact p = {r.p_value:.3f})",
            file=out,
        )


def _row(name: str, s: Summary, ks: tuple[int, ...]) -> list[str]:
    return (
        [name, str(s.cases)]
        + [f"{s.hit[k]:.2f}" for k in ks]
        + [f"{s.hit_all:.2f}"]
        + [f"{s.recall[k]:.2f}" for k in ks]
        + [f"{s.recall_all:.2f}", f"{s.mrr:.2f}", f"{s.mean_sources:.1f}"]
        + ["–" if s.mean_source_tokens is None else f"{s.mean_source_tokens:,.0f}"]
        + ["–" if s.facts_reached is None else f"{s.facts_reached} of {s.facts}"]
    )


if __name__ == "__main__":
    raise SystemExit(main())
