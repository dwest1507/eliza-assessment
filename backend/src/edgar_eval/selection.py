"""The selection rules: which retrieval Arm, and which generator, ships, decided by the
generation harness's scores on paired cases.

Each score is compared case by case with the one-sided exact sign test, under one pair
of thresholds for every rule (ADR 0011): a challenger is **ahead** on a score at
one-sided p < `AHEAD_P` (0.10) and **behind** at one-sided p < `BEHIND_P` (0.20). The
scores are Fact Recall, Faithfulness, Coverage Gaps and Contradicted Claims, the last
paired per case on "has no Contradicted Claim"; the last three are the guardrails.

Each score pairs only the cases both sides scored: a case one side could not score (its
judgment failed, or it was not answered) is left out of that score's test, never counted
as a zero. Each score's comparison reports the cases it paired and left out, the wins and
losses, both one-sided p-values, and the mean paired difference with a 95% bootstrap
interval (`edgar_eval.metrics.bootstrap_interval`: a fixed seed, 10,000 resamples), shown
but never decided on.

**Fact Recall fact by fact** (ADR 0015, amending ADR 0011 for the Arm and settings
rules): for each case both sides scored, the must-state Required Facts each side states
are counted, and the total difference over cases, challenger minus shipped, is tested by
a one-sided case-cluster bootstrap (`edgar_eval.metrics.cluster_bootstrap_test`: whole
cases resampled 10,000 times from a fixed seed, centred under the null), ahead at
p < `AHEAD_P`. A fact counts as stated at the report's fact cut-off, a truncated answer
states none, and a case whose Fact Recall judgment failed is left out. Each comparison
reports it (`stated_facts`) under every rule, with the paired facts split by where their
evidence reached (challenger only, shipped only, both, neither).

- **Arms** (user story 54): the Shipped Arm stays unless a challenger is **ahead on Fact
  Recall fact by fact** and **behind on no guardrail**, Fact Recall case by case among
  them.
- **Generators** (user story 55): the shipped generator stays unless a challenger is
  **ahead on Fact Recall or on Coverage Gaps** and **behind on none of Fact Recall and
  the guardrails**.

- **Settings** (ADR 0010): a chunk size and context budget replace the shipped ones under
  the Arm rule, fact by fact as well. Each setting's report is named by its setting
  (`chunks-600-budget-32000`).

Under any rule, when several challengers qualify, the **cheapest** wins: the lowest
mean answer cost, then the earliest listed.

**The one-call rule** (2026-10-17): the Answer Call is a question's only API call, so a
challenger whose Arm makes another at query time (`Arm.query_api_call` in
`edgar_eval.retrieval`: the hosted `dense` and `hybrid`) is never chosen and never
answers a paid run. It is still compared when its report is given, unconstrained: its
comparison says whether it would qualify, and is labelled `UNCONSTRAINED`, "available if
the one-call limit is lifted".

`RULES` states the rules, and is the only place they differ. Choice files written under
version 1's two-sided p < 0.05 rule, and #73's under ADR 0011's per-case rule, are
records and are not recomputed.

**The Control Run** (ADR 0011). Every comparison also takes a Control Run: the shipped
choice run again, compared with the shipped run under the same rule (fact by fact under
the Arm and settings rules). If it comes out ahead of the shipped run on any of the
rule's ahead metrics, the noise is larger than
the thresholds assume: the choice is **inconclusive**, the shipped choice stands whatever
its challengers scored, and the output says why.

**One shipped run and one Control Run per round.** A round is the same code (a digest of
the backend's source), prompt and Golden Set version on one split, which every Golden
Set report records (`edgar_eval.generation.current_round`). The `arms`, `generators` and
`settings` commands of a round share its shipped run, `generation-<split>.json` (the
Shipped Arm, the shipped generator, the shipped chunk size and context budget), and its
Control Run, `generation-control-<split>.json`: each command reuses them when they are of
the shipped setup and of this round, and otherwise runs them again first.

    python -m edgar_eval.selection arms [--split dev] [--reuse]
    python -m edgar_eval.selection generators [--split dev] [--reuse] [--model MODEL... | --all]
    python -m edgar_eval.selection settings [--split dev] [--reuse] --setting CHUNKS:BUDGET...
    python -m edgar_eval.selection compare SHIPPED.json CHALLENGER.json...
        [--control CONTROL.json] [--rule arms|generators|settings] [--json PATH]

**The screen** (ADR 0011): before any paid Answer Call, the `arms` and `settings`
commands score every candidate with the retrieval harness, which is free, and answer only
through the candidates whose Evidence Reached is not behind the shipped choice's
(one-sided p < `BEHIND_P`), at most three, the most Evidence Reached first and the
cheapest on a tie (`edgar_eval.retrieval.screen`). The choice file records the screen,
with every candidate screened and why it was kept or dropped.

`arms` runs the retrieval harness on the split for every Arm in `edgar_eval.arms.ARMS`,
writing `data/derived/eval/retrieval-<split>.json` with its screen, then the generation
harness once per challenger Arm the screen keeps, writing
`generation-arms-<split>-<arm>.json`. `generators` runs it on the Shipped Arm once per
other model in the default comparison, `edgar_eval.generators.COMPARISON`, writing
`generation-<split>-<model>.json` (the name `make eval-generation` uses); `--model`
(repeatable) names other rows of `edgar_eval.generators.GENERATORS` instead, and `--all`
runs every row (`make eval-generators` passes `--model` for each of `MODELS="..."`, and
`--all` for `MODELS=`, empty). `settings` runs the retrieval harness on the Shipped Arm
for the shipped setting and each `--setting`, a chunk size and context budget such as
`450:32000`, writing `retrieval-<split>-chunks<N>-budget<B>.json`, then the generation
harness once per setting the screen keeps, writing
`generation-<split>-chunks<N>-budget<B>.json` (the names `make eval-retrieval` and
`make eval-generation` use with `CHUNK_TOKENS=<N> CONTEXT_BUDGET=<B>`), and builds the
index of another chunk size, `data/derived/edgar_rag-chunks<N>.sqlite`, when missing.
With `--reuse`, a challenger's report already written is read instead of rerun (for
`arms` and `settings`, the retrieval reports too); the shipped run and Control Run are
reused by round, with or without it. All three call the
generators and Jev, so they cost money. `compare` applies a rule to generation reports
already written, the first being the shipped choice, with `--control` the Control Run's
(without one, as for version 1's reports, it says the noise is not shown). All print the
comparison and write it, with the choice, to `--json` (by default
`data/derived/eval/<arm|generator|settings>-choice-<split>.json`).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Any, Literal, TextIO

from edgar_eval.metrics import (
    Interval,
    McNemarResult,
    Verdict,
    bootstrap_interval,
    cluster_bootstrap_test,
    sign_test,
)
from edgar_rag.paths import DERIVED_DIR

__all__ = [
    "AHEAD_P",
    "BEHIND_P",
    "RULES",
    "UNCONSTRAINED",
    "Candidate",
    "Choice",
    "Comparison",
    "EvidenceGroup",
    "FactComparison",
    "FactOutcome",
    "Rule",
    "RuleName",
    "ScoreComparison",
    "choose",
    "main",
    "one_sided_verdict",
    "sign_test",
]

_EVAL_DIR = DERIVED_DIR / "eval"
_INDEX_DIR = DERIVED_DIR
"""Where an index of another chunk size is, or is built: `edgar_rag-chunks<N>.sqlite`,
the name `make eval-generation CHUNK_TOKENS=<N>` uses."""

RuleName = Literal["arms", "generators", "settings"]
Score = Literal[
    "fact_recall", "stated_facts", "faithfulness", "coverage_gaps", "contradicted_claims"
]

UNCONSTRAINED = "available if the one-call limit is lifted"
"""How a report labels an Arm that makes an API call at query time: it can't ship, but
it shows what lifting the one-call limit would offer. The retrieval harness's screen
uses it too."""

AHEAD_P = 0.10
"""A challenger is ahead on a score when the one-sided sign test gives p below this."""
BEHIND_P = 0.20
"""A challenger is behind on a score when the one-sided sign test gives p below this: a
looser cut-off, so a drop is flagged sooner. Both are fixed before any run on Golden Set
version 2 and are the same for every rule (ADR 0011)."""


def one_sided_verdict(test: McNemarResult) -> Verdict:
    """`ahead` at one-sided p < AHEAD_P, `behind` at one-sided p < BEHIND_P, else
    `indistinguishable` (both cannot hold at once): the verdict of every rule, and of
    the retrieval harness's gate on Evidence Reached."""
    if test.p_ahead < AHEAD_P:
        return "ahead"
    if test.p_behind < BEHIND_P:
        return "behind"
    return "indistinguishable"


def _run_arms(split: str, reuse: bool, out: TextIO) -> tuple[list[Path], dict | None]:
    from edgar_eval import generation, retrieval
    from edgar_eval.arms import ARMS

    screened = _EVAL_DIR / f"retrieval-{split}.json"
    report = json.loads(screened.read_text(encoding="utf-8")) if screened.exists() else {}
    if not (reuse and report.get("screen")):
        print("\n== The screen: every Arm through the retrieval harness ==", file=out, flush=True)
        retrieval.main(["--split", split, "--json", str(screened)], out=out)
        report = json.loads(screened.read_text(encoding="utf-8"))
    else:
        kept_names = ", ".join(report["screen"]["kept"]) or "none"
        print(f"\nThe screen, reused from {screened}: go on: {kept_names}", file=out)
    screen = report["screen"]
    kept = set(screen["kept"])
    paths = []
    # A screen saved before the one-call rule may keep an Arm that can't ship: never paid.
    for arm in (a for a in ARMS if not a.shipped and a.shippable and a.name in kept):
        path = _EVAL_DIR / f"generation-arms-{split}-{arm.name}.json"
        if not (reuse and path.exists()):
            print(f"\n== Arm {arm.name} ==", file=out, flush=True)
            generation.main(["--split", split, "--arm", arm.name, "--json", str(path)], out=out)
        paths.append(path)
    return paths, screen


def _run_generators(
    split: str, reuse: bool, out: TextIO, only: Sequence[str] = ()
) -> tuple[list[Path], None]:
    from edgar_eval import generation
    from edgar_eval.generators import GENERATORS

    _check_generators(only)
    models = [g.model for g in GENERATORS[1:] if not only or g.model in only]
    paths = []
    for model in models:
        path = _EVAL_DIR / f"generation-{split}-{model}.json"
        if not (reuse and path.exists()):
            print(f"\n== Generator {model} ==", file=out, flush=True)
            generation.main(["--split", split, "--model", model, "--json", str(path)], out=out)
        paths.append(path)
    return paths, None


def _check_generators(only: Sequence[str]) -> None:
    """Refuse a model not in the table of compared generators."""
    from edgar_eval.generators import GENERATORS, generator

    unknown = [m for m in only if generator(m) is None]
    if unknown:
        listed = ", ".join(g.model for g in GENERATORS)
        raise SystemExit(f"error: not compared generators: {', '.join(unknown)} (one of {listed})")


def _run_settings(
    split: str, reuse: bool, out: TextIO, settings: Sequence[tuple[int, int]] = ()
) -> tuple[list[Path], dict]:
    from edgar_eval import generation, retrieval
    from edgar_eval.arms import ARMS
    from edgar_eval.retrieval import EvidenceRun, print_screen, screen
    from edgar_rag.retrieval import CHUNK_TOKENS, CONTEXT_BUDGET_TOKENS

    if not settings:
        raise SystemExit("error: name each setting to compare: --setting CHUNKS:BUDGET")
    shipped = (CHUNK_TOKENS, CONTEXT_BUDGET_TOKENS)
    index = {chunks: _index_args(chunks, CHUNK_TOKENS) for chunks, _ in (shipped, *settings)}
    arm = next(a.name for a in ARMS if a.shipped)
    runs = []
    for chunks, budget in (shipped, *settings):  # the screen: the shipped setting first
        path = _EVAL_DIR / f"retrieval-{split}-chunks{chunks}-budget{budget}.json"
        if not (reuse and path.exists()):
            print(f"\n== The screen: chunks-{chunks}-budget-{budget} ==", file=out, flush=True)
            argv = ["--split", split, "--arm", arm, *index[chunks]]
            retrieval.main([*argv, "--context-budget", str(budget), "--json", str(path)], out=out)
        runs.append(EvidenceRun.from_report(json.loads(path.read_text(encoding="utf-8"))))
    result = screen(runs[0], runs[1:])
    print_screen(result, out)
    paths = []
    for chunks, budget in settings:
        if f"chunks-{chunks}-budget-{budget}" not in result.kept:
            continue
        path = _EVAL_DIR / f"generation-{split}-chunks{chunks}-budget{budget}.json"
        if not (reuse and path.exists()):
            print(f"\n== Setting chunks-{chunks}-budget-{budget} ==", file=out, flush=True)
            argv = ["--split", split, *index[chunks]]
            argv += ["--context-budget", str(budget), "--json", str(path)]
            generation.main(argv, out=out)
        paths.append(path)
    return paths, asdict(result)


def _index_args(chunks: int, shipped_chunks: int) -> list[str]:
    """The harness arguments for an index of `chunks`-token chunks: none for the shipped
    index, else the index of that chunk size, built when missing."""
    if chunks == shipped_chunks:
        return []
    index_path = _INDEX_DIR / f"edgar_rag-chunks{chunks}.sqlite"
    if not index_path.exists():
        _build_index(chunks, index_path)
    return ["--index", str(index_path)]


def _build_index(chunks: int, path: Path) -> None:
    """Build an index of another chunk size, as `make index` builds the shipped one."""
    from edgar_rag.corpus import load_corpus
    from edgar_rag.retrieval import build_index

    build_index(load_corpus(), path, chunk_tokens=chunks)


def _setting(value: str) -> tuple[int, int]:
    """A `--setting` value, `CHUNKS:BUDGET` (`450:32000`)."""
    try:
        chunks, budget = (int(part) for part in value.split(":"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not CHUNKS:BUDGET: {value}") from None
    return chunks, budget


_SHIPPED_RUN = "generation-{split}.json"
_CONTROL_RUN = "generation-control-{split}.json"


def _round_runs(split: str, out: TextIO) -> tuple[Path, Path]:
    """The round's shipped run and Control Run: the shipped setup (the Shipped Arm, the
    shipped generator, the shipped chunk size and context budget) answering the split
    twice. A report already written is reused when it is of the shipped setup and of
    this round (the same code, prompt and Golden Set version, `generation.current_round`);
    otherwise it is run again, so the comparisons of one round pay for the shipped
    choice twice, not once per comparison."""
    from edgar_eval import generation
    from edgar_eval.arms import ARMS
    from edgar_eval.generators import GENERATORS
    from edgar_rag.retrieval import CHUNK_TOKENS, CONTEXT_BUDGET_TOKENS

    setup = {
        "model": GENERATORS[0].model,
        "arm": next(a.name for a in ARMS if a.shipped),
        "settings": f"chunks-{CHUNK_TOKENS}-budget-{CONTEXT_BUDGET_TOKENS}",
        "split": split,
    }
    expected = setup | generation.current_round()
    paths = []
    for label, name in (("shipped run", _SHIPPED_RUN), ("Control Run", _CONTROL_RUN)):
        path = _EVAL_DIR / name.format(split=split)
        if _recorded(path, expected):
            print(f"Reusing the {label} of this round: {path}", file=out, flush=True)
        else:
            print(f"\n== The {label} ({setup['arm']}, {setup['model']}) ==", file=out, flush=True)
            argv = ["--split", split, "--model", setup["model"], "--json", str(path)]
            generation.main(argv, out=out)
        paths.append(path)
    return paths[0], paths[1]


def _recorded(path: Path, expected: Mapping[str, Any]) -> bool:
    """Whether the report at `path` exists and records every field of `expected`."""
    if not path.exists():
        return False
    report = json.loads(path.read_text(encoding="utf-8"))
    return all(report.get(k) == v for k, v in expected.items())


@dataclass(frozen=True)
class Rule:
    """What one selection rule decides by. A challenger qualifies when the sign test
    puts it `ahead` on at least one of `ahead_on_any` and `behind` on none of
    `behind_on_none`. The thresholds are not the rule's: every rule uses `AHEAD_P` and
    `BEHIND_P`."""

    ahead_on_any: tuple[Score, ...]
    behind_on_none: tuple[Score, ...]
    named_by: str
    """The generation report field that names a candidate (falling back to its model)."""
    run: Callable[..., tuple[list[Path], dict | None]]
    """Runs the generation harness once per challenger on a split (reusing reports
    already written when asked) and returns their reports, with the screen that chose
    the challengers (None for a rule that does not screen); the shipped run and Control
    Run come from the round (`_round_runs`). The Arm and settings rules' screen every
    candidate on Evidence Reached first (ADR 0011) and answer only through the ones it
    keeps. The generator rule's also takes `only`, the models to limit the run to; the
    settings rule's `settings`, the (chunk size, context budget) pairs to compare."""
    choice_file: str
    """The default file the choice is written to, before `-<split>.json`."""


RULES: dict[RuleName, Rule] = {
    "arms": Rule(
        ahead_on_any=("stated_facts",),
        behind_on_none=("fact_recall", "faithfulness", "coverage_gaps", "contradicted_claims"),
        named_by="arm",
        run=_run_arms,
        choice_file="arm-choice",
    ),
    "generators": Rule(
        ahead_on_any=("fact_recall", "coverage_gaps"),
        behind_on_none=("fact_recall", "faithfulness", "coverage_gaps", "contradicted_claims"),
        named_by="model",
        run=_run_generators,
        choice_file="generator-choice",
    ),
    "settings": Rule(
        ahead_on_any=("stated_facts",),
        behind_on_none=("fact_recall", "faithfulness", "coverage_gaps", "contradicted_claims"),
        named_by="settings",
        run=_run_settings,
        choice_file="settings-choice",
    ),
}
"""The only place the rules differ. Under the Arm and settings rules Fact Recall is
ahead by the fact-level test (`stated_facts`, ADR 0015) and the per-case sign test on it
is a guardrail; the generator rule decides Fact Recall per case, as ADR 0011 states."""

_UNRECORDED_CUTOFF = 0.5
"""The fact cut-off of a generation report saved before it recorded one
(`edgar_eval.judge.FACT_CUTOFF`'s note)."""


@dataclass(frozen=True)
class FactOutcome:
    """One must-state Required Fact in one answer."""

    stated: bool
    """Whether the answer counts as stating it: Jev's probability at least the report's
    fact cut-off, and never in a truncated answer."""
    reached: bool | None
    """Evidence Reached: whether its evidence quote was in the Answer Context; None in a
    report saved before it was recorded."""


@dataclass(frozen=True)
class Candidate:
    """One Arm's (or generator's) per-case scores from a generation run."""

    name: str
    fact_recall: Mapping[str, float | None]
    faithfulness: Mapping[str, float | None]
    coverage_gaps: Mapping[str, bool | None]
    """Whether each case stated every expected Coverage Gap; None with none expected."""
    cost_usd: float | None
    """Mean answer cost; None when a case had no price."""
    contradicted_claims: Mapping[str, bool | None] = field(default_factory=dict)
    """Whether each case's answer has no Contradicted Claim; None when that is unknown
    (its Faithfulness judgment failed, or a version 1 report, which did not record it)."""
    query_api_call: bool = False
    """Whether the candidate's Arm makes an API call at query time: if so it is never
    chosen (the one-call rule)."""
    facts: Mapping[str, tuple[FactOutcome, ...] | None] = field(default_factory=dict)
    """Each case's must-state Required Facts, in the case's order; None when the case
    has none or its Fact Recall judgment failed, so it is left out of the fact-level
    test as it is of the per-case one."""

    @classmethod
    def from_report(cls, report: Mapping[str, Any], rule: RuleName = "arms") -> Candidate:
        """A candidate from a generation harness report (its JSON), named as the rule
        names candidates: by its Arm or by its model."""
        cases = report["cases"]
        costs = [c.get("cost_usd") for c in cases]
        name = report.get(RULES[rule].named_by) or report["model"]
        return cls(
            name=name,
            fact_recall={c["case_id"]: c.get("fact_recall") for c in cases},
            faithfulness={c["case_id"]: c.get("faithfulness") for c in cases},
            coverage_gaps={
                c["case_id"]: None
                if c.get("coverage_gaps") is None
                else not c["coverage_gaps"]["missing"]
                for c in cases
            },
            cost_usd=fmean(costs) if costs and None not in costs else None,
            contradicted_claims={c["case_id"]: _no_contradiction(c) for c in cases},
            query_api_call=_query_api_call(report),
            facts={
                c["case_id"]: _must_state_facts(c, report.get("fact_cutoff", _UNRECORDED_CUTOFF))
                for c in cases
            },
        )


def _must_state_facts(case: Mapping[str, Any], cutoff: float) -> tuple[FactOutcome, ...] | None:
    """A report's case's must-state Required Facts, or None when it has none, its Fact
    Recall judgment failed, or it records no judgment. A truncated answer states none,
    as the harness scores it (`CaseResult.facts_stated`), read from the case's record."""
    judgments = case.get("judgments")
    if judgments is None or "facts" not in judgments:
        return None
    if any(f["judgment"] == "fact_recall" for f in judgments.get("failures", ())):
        return None
    judged = judgments["facts"]
    tiers = case.get("fact_tiers") or ["must_state"] * len(judged)
    reached = case.get("evidence_reached") or [None] * len(judged)
    truncated = bool(case.get("truncated"))
    facts = tuple(
        FactOutcome(stated=not truncated and fact["probability"] >= cutoff, reached=r)
        for fact, tier, r in zip(judged, tiers, reached, strict=True)
        if tier == "must_state"
    )
    return facts or None


def _query_api_call(report: Mapping[str, Any]) -> bool:
    """Whether a generation report's Arm makes an API call at query time: as the report
    records it, or, for a report saved before the one-call rule, as the Arm table says."""
    if "query_api_call" in report:
        return bool(report["query_api_call"])
    from edgar_eval.arms import ARMS

    return any(a.query_api_call for a in ARMS if a.name == report.get("arm"))


def _no_contradiction(case: Mapping[str, Any]) -> bool | None:
    """Whether a report's case has no Contradicted Claim, or None if that is unknown."""
    contradictions = case.get("contradictions")
    if contradictions is None:  # a version 1 report
        return None
    if contradictions["count"]:
        return False
    failures = case.get("judgments", {}).get("failures", ())
    return None if any(f["judgment"] == "faithfulness" for f in failures) else True


@dataclass(frozen=True)
class ScoreComparison:
    """One score of a challenger against the shipped choice, case by case."""

    paired: int
    """The cases both sides scored, which the test pairs."""
    left_out: int
    """The cases only one side scored, left out of the test. Cases neither side scored
    (nothing to score, such as no expected Coverage Gap) are in neither count."""
    wins: int
    """Paired cases the challenger scored higher."""
    losses: int
    """Paired cases the shipped choice scored higher."""
    p_ahead: float
    """One-sided exact p-value that the challenger is ahead."""
    p_behind: float
    """One-sided exact p-value that the challenger is behind."""
    verdict: Verdict
    """`ahead` at p_ahead < AHEAD_P, `behind` at p_behind < BEHIND_P, else
    `indistinguishable` (both cannot hold at once)."""
    difference: Interval | None
    """The mean paired difference, challenger minus shipped (a pass/fail score as 1 or
    0), with its 95% bootstrap interval; None with no pair. Shown, never decided on."""
    p_value: float
    """The two-sided exact p-value version 1 decided by, kept for comparison with its
    records; never decided on."""


@dataclass(frozen=True)
class EvidenceGroup:
    """The paired must-state facts of one evidence status, and how many each side
    stated."""

    facts: int
    challenger_stated: int
    shipped_stated: int


EVIDENCE_STATUSES = ("challenger_only", "shipped_only", "both", "neither", "unrecorded")
"""Where a paired fact's evidence reached: the challenger's Answer Context only, the
shipped choice's only, both, neither, or unrecorded (a report saved before Evidence
Reached was recorded, on either side). Each paired fact is in exactly one."""


@dataclass(frozen=True)
class FactComparison:
    """Fact Recall fact by fact (ADR 0015): the must-state Required Facts each side
    states, summed over the cases both sides scored, tested by the case-cluster
    bootstrap (`edgar_eval.metrics.cluster_bootstrap_test`)."""

    paired: int
    """The cases both sides scored."""
    left_out: int
    """The cases only one side scored (the other's judgment failed, or it has no
    answer), left out."""
    facts: int
    """The must-state facts of the paired cases."""
    challenger_stated: int
    shipped_stated: int
    total_difference: int
    """The statistic: challenger_stated minus shipped_stated."""
    p_ahead: float
    """One-sided bootstrap p-value that the challenger is ahead."""
    p_behind: float
    """One-sided bootstrap p-value that the challenger is behind; shown, the per-case
    sign test being the guardrail."""
    verdict: Verdict
    """`ahead` at p_ahead < AHEAD_P, `behind` at p_behind < BEHIND_P, else
    `indistinguishable`."""
    difference: Interval | None
    """The mean difference in facts stated per paired case, with its 95% bootstrap
    interval; None with no pair. Shown, never decided on."""
    by_evidence: dict[str, EvidenceGroup]
    """The paired facts by evidence status (`EVIDENCE_STATUSES`), each counted once."""
    resamples: int
    seed: int


@dataclass(frozen=True)
class Comparison:
    """A challenger against the shipped choice, case by case."""

    cases: int
    """Cases both answered."""
    fact_recall: ScoreComparison
    """Fact Recall case by case, by the sign test."""
    stated_facts: FactComparison
    """Fact Recall fact by fact (ADR 0015): the Arm and settings rules' ahead metric."""
    faithfulness: ScoreComparison
    coverage_gaps: ScoreComparison
    contradicted_claims: ScoreComparison
    """Paired per case on "has no Contradicted Claim"."""
    qualifies: bool
    """Whether the challenger qualifies under the rule it was compared by, on its scores
    alone: unconstrained by the one-call rule."""
    shippable: bool = True
    """False for a challenger whose Arm makes an API call at query time: never chosen,
    whether or not it qualifies."""


@dataclass(frozen=True)
class Choice:
    rule: RuleName
    shipped: str
    chosen: str
    comparisons: dict[str, Comparison]
    costs: dict[str, float | None]
    control: Comparison | None = None
    """The Control Run (the shipped choice run again) against the shipped run, under the
    same rule; None for a comparison made without one, as version 1's were."""
    inconclusive: bool = False
    """Whether the Control Run came out ahead of the shipped run on one of the rule's
    ahead metrics: the noise is larger than the thresholds assume, so the shipped
    choice stands whatever its challengers scored."""
    reason: str | None = None
    """Why the choice is inconclusive; None when it is not."""


_SCORES = ("fact_recall", "faithfulness", "coverage_gaps", "contradicted_claims")
"""The scores compared case by case with the sign test."""


def _compare_score(
    challenger: Mapping[str, float | bool | None], shipped: Mapping[str, float | bool | None]
) -> ScoreComparison:
    scored_a = {c for c, v in challenger.items() if v is not None}
    scored_b = {c for c, v in shipped.items() if v is not None}
    both = sorted(scored_a & scored_b)
    a = [float(challenger[c]) for c in both]  # type: ignore[arg-type]
    b = [float(shipped[c]) for c in both]  # type: ignore[arg-type]
    test = sign_test(a, b)
    verdict = one_sided_verdict(test)
    return ScoreComparison(
        paired=len(both),
        left_out=len(scored_a ^ scored_b),
        wins=test.challenger_only,
        losses=test.shipped_only,
        p_ahead=test.p_ahead,
        p_behind=test.p_behind,
        verdict=verdict,
        difference=bootstrap_interval([x - y for x, y in zip(a, b, strict=True)]),
        p_value=test.p_value,
    )


def _compare_facts(
    challenger: Mapping[str, tuple[FactOutcome, ...] | None],
    shipped: Mapping[str, tuple[FactOutcome, ...] | None],
) -> FactComparison:
    scored_a = {c for c, v in challenger.items() if v is not None}
    scored_b = {c for c, v in shipped.items() if v is not None}
    both = sorted(scored_a & scored_b)
    groups = {status: [0, 0, 0] for status in EVIDENCE_STATUSES}
    differences = []
    for case in both:
        mine, theirs = challenger[case], shipped[case]
        assert mine is not None and theirs is not None
        if len(mine) != len(theirs):
            raise ValueError(f"{case}: the two reports have different must-state facts")
        for a, b in zip(mine, theirs, strict=True):
            group = groups[_evidence_status(a.reached, b.reached)]
            group[0] += 1
            group[1] += a.stated
            group[2] += b.stated
        differences.append(sum(a.stated for a in mine) - sum(b.stated for b in theirs))
    test = cluster_bootstrap_test(differences)
    verdict: Verdict = "indistinguishable"
    if test.p_ahead < AHEAD_P:
        verdict = "ahead"
    elif test.p_behind < BEHIND_P:
        verdict = "behind"
    return FactComparison(
        paired=len(both),
        left_out=len(scored_a ^ scored_b),
        facts=sum(g[0] for g in groups.values()),
        challenger_stated=sum(g[1] for g in groups.values()),
        shipped_stated=sum(g[2] for g in groups.values()),
        total_difference=test.total,
        p_ahead=test.p_ahead,
        p_behind=test.p_behind,
        verdict=verdict,
        difference=bootstrap_interval([float(d) for d in differences]),
        by_evidence={s: EvidenceGroup(*g) for s, g in groups.items()},
        resamples=test.resamples,
        seed=test.seed,
    )


def _evidence_status(challenger: bool | None, shipped: bool | None) -> str:
    if challenger is None or shipped is None:
        return "unrecorded"
    if challenger and shipped:
        return "both"
    if challenger:
        return "challenger_only"
    return "shipped_only" if shipped else "neither"


def compare(challenger: Candidate, shipped: Candidate, rule: RuleName = "arms") -> Comparison:
    scores: dict[str, Any] = {
        f: _compare_score(getattr(challenger, f), getattr(shipped, f)) for f in _SCORES
    }
    scores["stated_facts"] = _compare_facts(challenger.facts, shipped.facts)
    spec = RULES[rule]
    return Comparison(
        cases=len(set(challenger.fact_recall) & set(shipped.fact_recall)),
        **scores,
        qualifies=any(scores[f].verdict == "ahead" for f in spec.ahead_on_any)
        and all(scores[f].verdict != "behind" for f in spec.behind_on_none),
        shippable=not challenger.query_api_call,
    )


_LABELS: dict[Score, str] = {
    "fact_recall": "Fact Recall",
    "stated_facts": "Fact Recall fact by fact",
    "faithfulness": "Faithfulness",
    "coverage_gaps": "Coverage Gaps",
    "contradicted_claims": "No Contradicted Claim",
}


def choose(
    shipped: Candidate,
    challengers: Sequence[Candidate],
    rule: RuleName = "arms",
    *,
    control: Candidate | None = None,
) -> Choice:
    """Apply a selection rule. With a `control` (the shipped choice run again, ADR
    0011), the choice is inconclusive, and the shipped choice stands, when the Control
    Run is ahead of the shipped run on any of the rule's ahead metrics. A challenger
    that makes an API call at query time is never chosen (the one-call rule)."""
    comparisons = {c.name: compare(c, shipped, rule) for c in challengers}
    checked = compare(control, shipped, rule) if control is not None else None
    noisy = [
        _LABELS[f]
        for f in RULES[rule].ahead_on_any
        if checked and getattr(checked, f).verdict == "ahead"
    ]
    reason = (
        f"the Control Run, {shipped.name} run again, is ahead of the shipped run on "
        f"{' and '.join(noisy)}: the noise is larger than the thresholds assume, so "
        f"{shipped.name} stands"
        if noisy
        else None
    )
    qualifying = [
        (c.cost_usd if c.cost_usd is not None else float("inf"), n, c.name)
        for n, c in enumerate(challengers)
        if comparisons[c.name].qualifies and comparisons[c.name].shippable
    ]
    return Choice(
        rule=rule,
        shipped=shipped.name,
        chosen=min(qualifying)[2] if qualifying and not noisy else shipped.name,
        comparisons=comparisons,
        costs={c.name: c.cost_usd for c in (shipped, *challengers)},
        control=checked,
        inconclusive=bool(noisy),
        reason=reason,
    )


# --- Command line -------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description="Choose between Arms by the selection rule.")
    commands = parser.add_subparsers(dest="command", required=True)
    arms = commands.add_parser("arms", help="run every Arm through the generation harness")
    generators = commands.add_parser("generators", help="run every generator through the harness")
    settings = commands.add_parser("settings", help="run each named setting through the harness")
    for command in (arms, generators, settings):
        command.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
        command.add_argument(
            "--reuse", action="store_true", help="read challenger reports already written"
        )
        command.add_argument("--json", type=Path)
    chosen = generators.add_mutually_exclusive_group()
    chosen.add_argument(
        "--model",
        action="append",
        default=[],
        help="run this generator instead of the default comparison (repeatable)",
    )
    chosen.add_argument("--all", action="store_true", help="run every compared generator")
    settings.add_argument(
        "--setting",
        action="append",
        type=_setting,
        default=[],
        metavar="CHUNKS:BUDGET",
        help="a chunk size and context budget to compare, such as 450:32000 (repeatable)",
    )
    reports = commands.add_parser("compare", help="compare generation reports")
    reports.add_argument("reports", type=Path, nargs="+", help="the shipped choice's first")
    reports.add_argument("--control", type=Path, help="the Control Run's report")
    reports.add_argument("--rule", choices=tuple(RULES), default="arms")
    reports.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    rule: RuleName
    screen: dict | None = None
    if args.command == "compare":
        rule, paths, control, target = args.rule, args.reports, args.control, args.json
    else:
        rule = args.command
        options: dict[str, Any] = {}
        if rule == "generators":
            from edgar_eval.generators import COMPARISON

            _check_generators(args.model)  # before any paid run
            # No --model: the default comparison; --all: every row (no limit).
            options = {"only": () if args.all else args.model or COMPARISON}
        elif rule == "settings":
            if not args.setting:
                parser.error("name each setting to compare: --setting CHUNKS:BUDGET")
            options = {"settings": args.setting}
        shipped_path, control = _round_runs(args.split, out)
        challengers, screen = RULES[rule].run(args.split, args.reuse, out, **options)
        paths = [shipped_path, *challengers]
        target = args.json or _EVAL_DIR / f"{RULES[rule].choice_file}-{args.split}.json"
    data = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    candidates = [Candidate.from_report(d, rule) for d in data]
    control_candidate = (
        Candidate.from_report(json.loads(control.read_text(encoding="utf-8")), rule)
        if control
        else None
    )
    choice = choose(candidates[0], candidates[1:], rule, control=control_candidate)
    _print(choice, out)
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "split": data[0].get("split"),
            "reports": [str(p) for p in paths],
            "control_report": str(control) if control else None,
        }
        if screen is not None:
            record["screen"] = screen
        target.write_text(json.dumps(record | asdict(choice), indent=2) + "\n", encoding="utf-8")
        print(f"\nWritten to {target.resolve()}", file=out)
    return 0


def _print_scores(c: Comparison, out: TextIO) -> None:
    for score in _SCORES:
        label, r = _LABELS[score], getattr(c, score)
        d = r.difference
        shift = (
            f"; mean difference {d.mean:+.3f}, 95% interval [{d.low:+.3f}, {d.high:+.3f}]"
            if d
            else ""
        )
        print(
            f"  {label}: {r.verdict} ({r.wins} cases higher, {r.losses} lower, "
            f"p ahead = {r.p_ahead:.3f}, p behind = {r.p_behind:.3f}; "
            f"{r.paired} cases paired, {r.left_out} left out{shift})",
            file=out,
        )
        if score == "fact_recall":
            _print_facts(c.stated_facts, out)


def _print_facts(f: FactComparison, out: TextIO) -> None:
    d = f.difference
    shift = f"; per case {d.mean:+.3f}, 95% interval [{d.low:+.3f}, {d.high:+.3f}]" if d else ""
    print(
        f"  {_LABELS['stated_facts']}: {f.verdict} ({f.challenger_stated} of {f.facts} "
        f"must-state facts stated against {f.shipped_stated}, {f.total_difference:+d}, "
        f"p ahead = {f.p_ahead:.3f}, p behind = {f.p_behind:.3f}; {f.paired} cases paired, "
        f"{f.left_out} left out{shift})",
        file=out,
    )
    groups = ", ".join(
        f"{status.replace('_', ' ')} {g.challenger_stated} / {g.shipped_stated} of {g.facts}"
        for status, g in f.by_evidence.items()
        if g.facts
    )
    if groups:
        print(f"    stated by evidence reached (challenger / shipped): {groups}", file=out)


def _print(choice: Choice, out: TextIO) -> None:
    ahead = " or ".join(_LABELS[s] for s in RULES[choice.rule].ahead_on_any)
    print(
        f"\nEach challenger against {choice.shipped}, case by case by the one-sided exact "
        "sign test, and fact by fact by the case-cluster bootstrap (ahead at p < "
        f"{AHEAD_P:.2f}, behind at p < {BEHIND_P:.2f}; ahead on {ahead} qualifies):",
        file=out,
    )
    if choice.control is not None:
        print(
            f"\nControl Run ({choice.shipped} run again, {choice.control.cases} cases): "
            "within noise unless ahead of the shipped run",
            file=out,
        )
        _print_scores(choice.control, out)
    else:
        print("\nNo Control Run: the noise of this comparison is not shown.", file=out)
    for name, c in choice.comparisons.items():
        cost = choice.costs[name]
        print(f"\n{name} ({c.cases} cases, ${cost or 0:.4f} per answer)", file=out)
        _print_scores(c, out)
        print(f"  Qualifies: {'yes' if c.qualifies else 'no'}", file=out)
        if not c.shippable:
            print(
                f"  Can't ship: its Arm makes an API call at query time ({UNCONSTRAINED})",
                file=out,
            )
    if choice.inconclusive:
        print(f"\nInconclusive: {choice.reason}.", file=out)
    print(f"\nChosen: {choice.chosen}", file=out)


if __name__ == "__main__":
    raise SystemExit(main())
