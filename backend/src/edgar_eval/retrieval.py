"""The retrieval harness: run Golden Set cases through each Arm and score the Sources.

Each case's conversation (its scripted history, then its question) goes to an Arm, which
returns the (Filing ID, Section) pairs of the Sources it would put in the Answer Call,
best first. The ranking is scored against the case's expected pairs with hit@k,
recall@k and MRR, overall and per question type. Multi-turn cases are scored on their
final turn. Cases with no expected pair (a Company missing from the Corpus, General
Electric today) have nothing to find and are listed as unscored.

For an Arm that prepares the whole Answer Context (every Arm in `edgar_eval.arms`), the
harness also records **Evidence Reached** per Required Fact: whether the fact's evidence
quote appears, whitespace aside, in the text of the context's Sources. The Golden Set
labels relevance by Section, so a change of Arm, chunk size or context budget barely
moves hit@k; Evidence Reached shows whether the passages that state the facts reach the
prompt (ADR 0010). `evidence_reached` is its one definition, which the generation harness
calls too.

For each fact not reached, the report records its Filing and Section and whether
retrieval searched there, as the context's Query Scope records the places searched: a
**planning miss** when the Section plan left that Section of that Filing out, a
**ranking miss** when it was searched but its passage did not rank into the budget. The
printout groups each Arm's unreached must-state facts by the two.

**The gate** (ADR 0011): every challenger Arm is compared with the Shipped Arm on
Evidence Reached, paired fact by fact, by McNemar's exact test, one-sided, under the
selection rules' thresholds (`edgar_eval.selection.AHEAD_P` and `BEHIND_P`). hit@k,
recall@k and MRR are reported beside it, never gated on.

**The screen** (ADR 0011), run before any paid Answer Call: a candidate (an Arm, or a
chunk size and context budget) goes on to paid generation only if Evidence Reached does
not put it behind the shipped choice (one-sided p < `BEHIND_P`). If more than
`MAX_CHALLENGERS` pass, the ones with the highest share of Evidence Reached go on, the
cheapest first on a tie: the fewest mean tokens of Source text per Answer Context (the
Answer Call's input), then the earliest listed. The report lists every candidate screened
and why it was kept or dropped. `evaluate` screens the Arms it scores; `screen` takes any
candidates, such as each chunk size and context budget's report (`make eval-settings`).

**The one-call rule** (2026-10-17, `docs/assumptions.md` #1): the Answer Call is the only
API call a question may make. Every Arm records whether it makes another at query time
(`Arm.query_api_call`), such as a hosted embedding of the question. Such an Arm is scored
and gated like any other, unconstrained, but the screen never sends it to a paid run, and
its reports label it "available if the one-call limit is lifted"
(`edgar_eval.selection.UNCONSTRAINED`).

`make eval-retrieval` runs every Arm in `edgar_eval.arms.ARMS` on the dev split, prints
the scores and writes them as JSON under `data/derived/eval/`. The index (and so its
chunk size) and the context budget can be chosen per run, and the report records both:

    python -m edgar_eval.retrieval [--split dev|holdout|all] [--index PATH]
        [--context-budget TOKENS] [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from itertools import zip_longest
from pathlib import Path
from statistics import fmean
from typing import Any, Literal, TextIO

from edgar_eval.metrics import (
    McNemarResult,
    Pair,
    Verdict,
    hit_at_k,
    mcnemar_exact,
    recall_at_k,
    reciprocal_rank,
)
from edgar_eval.selection import BEHIND_P, UNCONSTRAINED, one_sided_verdict
from edgar_rag.golden_set import (
    DEFAULT_GOLDEN_SET,
    GoldenCase,
    RequiredFact,
    Tier,
    load_golden_set,
    normalise_whitespace,
)
from edgar_rag.retrieval import (
    CONTEXT_BUDGET_TOKENS,
    DEFAULT_INDEX,
    AnswerContext,
    Message,
    count_tokens,
    index_chunk_tokens,
)

DEFAULT_KS = (5, 10, 20)
GATING_METRIC = "evidence reached"
MAX_CHALLENGERS = 3
"""At most this many candidates per rule pass the screen to paid Answer Calls (ADR
0011)."""

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
    query_api_call: bool = False
    """True for an Arm that makes an API call at query time besides the Answer Call,
    such as embedding the question with a hosted model. Under the one-call rule it can't
    ship: it is reported, but never screened on to a paid run nor chosen."""

    @property
    def shippable(self) -> bool:
        """Whether the Arm could ship under the one-call rule."""
        return not self.query_api_call


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
    evidence_reached: tuple[bool, ...] | None = None
    """Evidence Reached per Required Fact, in the case's fact order: whether the fact's
    evidence quote is in the Sources' text; None for an Arm measured by retrieval
    only."""
    source_tokens: int | None = None
    """Tokens of Source text in the Answer Context; None for an Arm measured by
    retrieval only."""
    unreached: tuple[UnreachedFact, ...] | None = None
    """Each Required Fact whose evidence did not reach the Answer Context, in the case's
    fact order, with where it is and whether retrieval searched there; None for an Arm
    measured by retrieval only."""

    def misses(self, kind: Miss) -> int:
        """How many must-state facts missed this way."""
        return sum(u.tier == "must_state" and u.miss == kind for u in self.unreached or ())


Miss = Literal["planning", "ranking"]


@dataclass(frozen=True)
class UnreachedFact:
    """A Required Fact whose evidence quote did not reach the Answer Context."""

    fact: int
    """Its position in the case's fact order, from 0."""
    tier: Tier
    filing_id: str
    section: str
    """The Filing and Section its evidence quote is in, as the case labels it."""
    searched: bool
    """Whether retrieval searched that Section of that Filing (or the whole Filing) for
    its Company: if not, the Section plan left it out (a planning miss); if so, its
    passage was not ranked into the budget (a ranking miss)."""

    @property
    def miss(self) -> Miss:
        return "ranking" if self.searched else "planning"


def unreached_facts(
    context: AnswerContext, facts: Sequence[RequiredFact], reached: Sequence[bool]
) -> tuple[UnreachedFact, ...]:
    """The facts not reached, each with whether its Section was among the places the
    Answer Context records retrieval searched."""
    searched = {(p.filing_id, p.section) for p in context.query_scope.searched}
    return tuple(
        UnreachedFact(
            fact=i,
            tier=f.tier,
            filing_id=f.filing_id,
            section=f.section,
            searched=bool({(f.filing_id, f.section), (f.filing_id, None)} & searched),
        )
        for i, (f, hit) in enumerate(zip(facts, reached, strict=True))
        if not hit
    )


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
    query_api_call: bool = False
    """Whether the Arm makes an API call at query time (`Arm.query_api_call`)."""
    shippable: bool = True
    """Whether it could ship under the one-call rule."""

    def evidence(self) -> EvidenceRun | None:
        """The Arm's Evidence Reached, for the gate and the screen; None for an Arm
        measured by retrieval only."""
        if any(c.evidence_reached is None for c in self.cases):
            return None
        return EvidenceRun(
            name=self.name,
            evidence={c.case_id: c.evidence_reached or () for c in self.cases},
            mean_source_tokens=self.overall.mean_source_tokens,
            shippable=self.shippable,
        )


@dataclass(frozen=True)
class EvidenceRun:
    """One candidate's Evidence Reached on the cases it scored, as the gate and the
    screen compare it."""

    name: str
    evidence: Mapping[str, Sequence[bool]]
    """Per case id, Evidence Reached per Required Fact, in the case's fact order."""
    mean_source_tokens: float | None = None
    """Mean tokens of Source text per Answer Context: the screen's cost."""
    shippable: bool = True
    """False for a candidate that makes an API call at query time: the screen never
    sends it on."""

    @property
    def facts(self) -> int:
        return sum(len(reached) for reached in self.evidence.values())

    @property
    def facts_reached(self) -> int:
        return sum(sum(reached) for reached in self.evidence.values())

    @classmethod
    def from_report(cls, report: Mapping[str, Any], name: str | None = None) -> EvidenceRun:
        """The Shipped Arm's Evidence Reached from a saved retrieval report (its JSON),
        named `name` or by the report's chunk size and context budget, as the settings
        rule names a setting (`chunks-600-budget-32000`)."""
        arm = next(a for a in report["arms"].values() if a["shipped"])
        if any(c.get("evidence_reached") is None for c in arm["cases"]):
            raise ValueError("the report records no Evidence Reached per Required Fact")
        chunks = report.get("chunk_tokens") or "unknown"
        return cls(
            name=name or f"chunks-{chunks}-budget-{report['context_budget']}",
            evidence={c["case_id"]: tuple(c["evidence_reached"]) for c in arm["cases"]},
            mean_source_tokens=arm["overall"].get("mean_source_tokens"),
        )


def compare_evidence(challenger: EvidenceRun, shipped: EvidenceRun) -> Comparison:
    """The gate: McNemar's exact test on Evidence Reached, paired fact by fact over the
    cases both scored, with the one-sided verdict of the selection rules' thresholds."""
    a: list[bool] = []
    b: list[bool] = []
    for case_id, reached in shipped.evidence.items():
        if case_id not in challenger.evidence:
            continue
        if len(challenger.evidence[case_id]) != len(reached):
            raise ValueError(f"{case_id} has a different number of Required Facts on each side")
        a += challenger.evidence[case_id]
        b += reached
    result = mcnemar_exact(a, b)
    return Comparison(
        arm=challenger.name,
        shipped_arm=shipped.name,
        metric=GATING_METRIC,
        result=result,
        facts=len(a),
        verdict=one_sided_verdict(result),
    )


@dataclass(frozen=True)
class Comparison:
    arm: str
    shipped_arm: str
    metric: str
    result: McNemarResult
    """McNemar's exact test on the discordant facts: `challenger_only` facts only the
    challenger reached, `shipped_only` facts only the shipped choice reached."""
    facts: int = 0
    """The Required Facts paired."""
    verdict: Verdict = "indistinguishable"
    """One-sided, under the selection rules' thresholds: the gate's verdict."""


@dataclass(frozen=True)
class Screened:
    """One candidate as the screen saw it."""

    name: str
    facts: int
    facts_reached: int
    mean_source_tokens: float | None
    gained: int
    """Facts only this candidate reached."""
    lost: int
    """Facts only the shipped choice reached."""
    p_behind: float
    """One-sided exact p-value that the candidate is behind on Evidence Reached."""
    kept: bool
    reason: str
    shippable: bool = True
    """False for a candidate that makes an API call at query time, dropped whatever it
    reached."""


@dataclass(frozen=True)
class Screen:
    """Which candidates go on to paid Answer Calls, and why each was kept or dropped."""

    shipped: str
    limit: int
    kept: tuple[str, ...]
    """The candidates that go on, in the order they ranked."""
    candidates: tuple[Screened, ...]
    """Every candidate screened, in the order given."""


def screen(
    shipped: EvidenceRun, candidates: Sequence[EvidenceRun], limit: int = MAX_CHALLENGERS
) -> Screen:
    """Screen candidates on Evidence Reached before any paid Answer Call (ADR 0011). A
    candidate that makes an API call at query time is gated like the others but never
    goes on, nor takes a place among those that do (the one-call rule)."""
    gates = {c.name: compare_evidence(c, shipped) for c in candidates}
    passing = [c for c in candidates if c.shippable and gates[c.name].result.p_behind >= BEHIND_P]
    ranked = sorted(
        passing,
        key=lambda c: (
            -(c.facts_reached / c.facts if c.facts else 0.0),
            c.mean_source_tokens if c.mean_source_tokens is not None else float("inf"),
            candidates.index(c),
        ),
    )
    rank = {c.name: n for n, c in enumerate(ranked, start=1)}
    kept = tuple(c.name for c in ranked[:limit])

    def reason(c: EvidenceRun) -> str:
        p = gates[c.name].result.p_behind
        if not c.shippable:
            verdict = gates[c.name].verdict
            return (
                f"dropped: makes an API call at query time, so it can't ship ({verdict} "
                f"on Evidence Reached, p behind = {p:.3f}; {UNCONSTRAINED})"
            )
        if c.name not in rank:
            return f"dropped: behind on Evidence Reached (p behind = {p:.3f} < {BEHIND_P:.2f})"
        place = f"{rank[c.name]} of {len(ranked)} not behind on Evidence Reached"
        if c.name in kept:
            return f"kept: not behind (p behind = {p:.3f}), {place}"
        return f"dropped: not behind (p behind = {p:.3f}), but {place}; only {limit} go on"

    return Screen(
        shipped=shipped.name,
        limit=limit,
        kept=kept,
        candidates=tuple(
            Screened(
                name=c.name,
                facts=c.facts,
                facts_reached=c.facts_reached,
                mean_source_tokens=c.mean_source_tokens,
                gained=gates[c.name].result.challenger_only,
                lost=gates[c.name].result.shipped_only,
                p_behind=gates[c.name].result.p_behind,
                kept=c.name in kept,
                reason=reason(c),
                shippable=c.shippable,
            )
            for c in candidates
        ),
    )


@dataclass(frozen=True)
class RetrievalReport:
    ks: tuple[int, ...]
    gating_metric: str
    case_ids: tuple[str, ...]
    """The scored cases, in Golden Set order."""
    unscored: tuple[str, ...]
    arms: dict[str, ArmScores]
    comparisons: tuple[Comparison, ...] = field(default=())
    """Each challenger Arm against the Shipped Arm on Evidence Reached (the gate); none
    for an Arm measured by retrieval only."""
    screen: Screen | None = None
    """The challenger Arms screened on Evidence Reached; None when the Shipped Arm is
    measured by retrieval only."""
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
    context_budget: int = CONTEXT_BUDGET_TOKENS,
    chunk_tokens: int | None = None,
) -> RetrievalReport:
    """Score every Arm on the cases, each Answer Context allowed `context_budget` tokens
    of Sources, gate each challenger against the Shipped Arm on Evidence Reached and
    screen them. `chunk_tokens` is recorded in the report as the index's chunk size."""
    shipped = [arm for arm in arms if arm.shipped]
    if len(shipped) != 1:
        raise ValueError(f"exactly one Arm must be shipped, not {len(shipped)}")
    ks = tuple(sorted(set(ks)))
    scored = [c for c in cases if c.expected_sources]
    scores = {arm.name: _score_arm(arm, scored, Path(index), ks, context_budget) for arm in arms}

    base = scores[shipped[0].name].evidence()
    challengers = [
        run for arm in arms if not arm.shipped and (run := scores[arm.name].evidence()) is not None
    ]
    return RetrievalReport(
        ks=ks,
        gating_metric=GATING_METRIC,
        case_ids=tuple(c.id for c in scored),
        unscored=tuple(c.id for c in cases if not c.expected_sources),
        arms=scores,
        comparisons=tuple(compare_evidence(c, base) for c in challengers) if base else (),
        screen=screen(base, challengers) if base else None,
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


def evidence_reached(context: AnswerContext, facts: Sequence[RequiredFact]) -> tuple[bool, ...]:
    """Evidence Reached for each Required Fact, in the facts' order: whether its evidence
    quote is in the text of the Answer Context's Sources, both compared after collapsing
    whitespace. The one definition both the retrieval and the generation harness use."""
    text = normalise_whitespace("\n".join(s.text for s in context.sources))
    return tuple(normalise_whitespace(f.evidence) in text for f in facts)


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
        query_api_call=arm.query_api_call,
        shippable=arm.shippable,
        overall=_summarise(case_scores, ks),
        by_type={kind: _summarise(group, ks) for kind, group in by_type.items()},
        cases=case_scores,
    )


def _score_case(
    arm: Arm, case: GoldenCase, index: Path, ks: tuple[int, ...], context_budget: int
) -> CaseScore:
    reached = tokens = unreached = None
    if arm.prepare is not None:
        context = arm.prepare(conversation(case), index, context_budget=context_budget)
        ranked = source_ranking(context)
        reached = evidence_reached(context, case.required_facts)
        unreached = unreached_facts(context, case.required_facts, reached)
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
        facts_reached=None if reached is None else sum(reached),
        evidence_reached=reached,
        source_tokens=tokens,
        unreached=unreached,
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
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=DEFAULT_GOLDEN_SET,
        help="a Golden Set file (default: version 2; name data/eval/golden_set.json for 1)",
    )
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
        context_budget=args.context_budget,
        chunk_tokens=index_chunk_tokens(args.index) if args.index.exists() else None,
    )
    print_report(report, args.split, out)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        data = {"split": args.split, "golden_set_version": golden.version} | report.to_dict()
        args.json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"\nWritten to {args.json.resolve()}", file=out)
    return 0


def print_report(report: RetrievalReport, split: str, out: TextIO) -> None:
    """The scores of every Arm, its unreached evidence, the gate and the screen."""
    print(
        f"Retrieval on the {split} split: {len(report.case_ids)} cases scored, "
        f"{len(report.unscored)} with no expected Source ({', '.join(report.unscored)})",
        file=out,
    )
    chunks = f"{report.chunk_tokens}-token chunks" if report.chunk_tokens else "chunks"
    print(f"Settings: {chunks}, a context budget of {report.context_budget} tokens", file=out)
    print(
        f"Gating metric: {report.gating_metric}, one-sided (hit@k, recall@k and MRR "
        "reported, not gated on)",
        file=out,
    )
    headers = (
        ["", "cases"]
        + [f"hit@{k}" for k in report.ks]
        + ["hit@all"]
        + [f"recall@{k}" for k in report.ks]
        + ["recall@all", "MRR", "Sources", "tokens", "evidence"]
    )
    for scores in report.arms.values():
        label = " (shipped)" if scores.shipped else ""
        if not scores.shippable:
            label = f" (makes an API call at query time: {UNCONSTRAINED})"
        print(f"\nArm {scores.name}{label}", file=out)
        rows = [("overall", scores.overall)] + sorted(scores.by_type.items())
        table = [headers] + [_row(name, summary, report.ks) for name, summary in rows]
        widths = [max(len(row[i]) for row in table) for i in range(len(headers))]
        for row in table:
            cells = [cell.rjust(width) for cell, width in zip(row, widths, strict=True)]
            print("  ".join([row[0].ljust(widths[0])] + cells[1:]), file=out)
        missed = [
            f"{c.case_id} ({c.facts - (c.facts_reached or 0)} of {c.facts})"
            for c in scores.cases
            if c.facts_reached is not None and c.facts_reached < c.facts
        ]
        print(f"Evidence not reached: {', '.join(missed) or 'none'}", file=out)
        if any(c.unreached is not None for c in scores.cases):
            for kind, where in (("planning", "not searched"), ("ranking", "searched")):
                by_case = [f"{c.case_id}: {n}" for c in scores.cases if (n := c.misses(kind))]
                print(
                    f"{kind.capitalize()} misses (must-state, Section {where}): "
                    f"{sum(c.misses(kind) for c in scores.cases)} ({', '.join(by_case)})",
                    file=out,
                )
    for comparison in report.comparisons:
        r = comparison.result
        print(
            f"\n{comparison.arm} vs {comparison.shipped_arm} on {comparison.metric}: "
            f"{comparison.verdict} ({r.challenger_only} facts only {comparison.arm} reached, "
            f"{r.shipped_only} only {comparison.shipped_arm} reached, of {comparison.facts}; "
            f"p ahead = {r.p_ahead:.3f}, p behind = {r.p_behind:.3f})",
            file=out,
        )
    if report.screen:
        print_screen(report.screen, out)


def print_screen(result: Screen, out: TextIO) -> None:
    """Every candidate screened, and why it was kept or dropped."""
    print(
        f"\nScreen on Evidence Reached against {result.shipped} (behind at one-sided "
        f"p < {BEHIND_P:.2f}; at most {result.limit} go on to paid Answer Calls):",
        file=out,
    )
    for c in result.candidates:
        tokens = "" if c.mean_source_tokens is None else f", {c.mean_source_tokens:,.0f} tokens"
        print(
            f"  {c.name}: {c.facts_reached} of {c.facts} facts reached ({c.gained} gained, "
            f"{c.lost} lost{tokens}): {c.reason}",
            file=out,
        )
    print(f"Go on: {', '.join(result.kept) or 'none'}", file=out)


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
