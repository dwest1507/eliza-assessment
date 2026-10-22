"""The selection rules: which retrieval Arm, which generator, which chunk size and
context budget, and which prompt candidate ships, decided by the generation harness's
scores on paired cases.

Each score is compared case by case with the one-sided exact sign test, under one pair
of thresholds for every rule (ADR 0011): a challenger is **ahead** on a score at
one-sided p < `AHEAD_P` (0.10) and **behind** at one-sided p < `BEHIND_P` (0.20). The
scores are Fact Recall, Faithfulness, Coverage Gaps, Contradicted Claims (paired per case
on "has no Contradicted Claim") and structure followed (the structure check, per case);
Faithfulness, Coverage Gaps and Contradicted Claims are every rule's guardrails, and
structure the prompt rules' only. Each comparison also counts the cases failing the
figure check on each side (`figures`), the `prompt-fix` rule's ahead metric.

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
- **Prompts** (ADR 0017), for a change meant to raise the facts stated (a prompt version,
  a retrieval change such as the legal proceedings route): the Arm rule, **ahead on Fact
  Recall fact by fact** and **behind on no guardrail**, with structure followed added to
  the guardrails.
- **Prompt-fix** (ADR 0017), for a correctness change (the figures prompt): it qualifies
  when **fewer cases fail the figure check** than in the shipped run, a count, not a
  test, and it is **behind on none** of the prompt rule's guardrails nor on Fact Recall
  fact by fact.

The prompt rules have no command of their own: `compare --rule prompts|prompt-fix`
applies them offline to the round's shipped run, a candidate's report (written by `make
eval-generation NAME=...`, which records `name`) and the Control Run. A candidate is
named by its report's `name`, else its prompt version; a challenger whose name another
already has takes its report's file name beside it (`v7 (generation-dev-x)`).

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
        [--control CONTROL.json] [--rule arms|generators|settings|prompts|prompt-fix]
        [--json PATH]

**Several runs a side** (ADR 0017's note of 2026-10-21). One run of a setup can differ
from another by more than the thresholds assume (#160's Control Run stated 12 more
must-state facts than its shipped run), so `compare` also reads a side answered by
several runs of one setup, its reports joined by `+`:

    python -m edgar_eval.selection compare generation-dev.json+generation-dev-run2.json \
        generation-dev-v16.json+generation-dev-v16-run2.json \
        --control generation-control-dev.json+generation-control-dev-run2.json --rule prompts

Each case's score on a side is then the mean over the runs that scored it (a pass/fail
score the share of runs passing), each must-state fact is stated by the share of the
side's runs stating it, so facts stated and figure failures are a mean per run, and the
cost is the runs' mean (`Candidate.from_reports`). The tests, thresholds and rules are
unchanged: the sign test pairs the per-case means, the fact-level test resamples whole
cases of mean differences, and the Control Check compares the Control Run's runs with
the shipped run's. The runs of one side must record one setup (`_SETUP`); a second run
may carry its own `name` (`NAME=v16-run2`), the side taking its first run's. The choice
file records each side's run count (`runs`, `control_runs`) and reports
(`run_reports`), and `capped` names each run (`v15 (shipped run 2)`, `v16 (run 2)`).

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
comparison and every answer of each run that stopped at the token cap (`capped`), and
write them, with the choice and the prompt and code versions each side's report records
(`versions`), to `--json` (by default
`data/derived/eval/<arm|generator|settings>-choice-<split>.json`; `compare` writes only
when `--json` names a file).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction
from math import lcm
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
    "FigureComparison",
    "FactOutcome",
    "Rule",
    "RuleName",
    "ScoreComparison",
    "choose",
    "compare",
    "main",
    "one_sided_verdict",
    "sign_test",
]

_EVAL_DIR = DERIVED_DIR / "eval"
_INDEX_DIR = DERIVED_DIR
"""Where an index of another chunk size is, or is built: `edgar_rag-chunks<N>.sqlite`,
the name `make eval-generation CHUNK_TOKENS=<N>` uses."""

RuleName = Literal["arms", "generators", "settings", "prompts", "prompt-fix"]
Score = Literal[
    "fact_recall",
    "stated_facts",
    "faithfulness",
    "coverage_gaps",
    "contradicted_claims",
    "structure",
    "figures",
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
    """The generation report field that names a candidate (falling back to `fallback`,
    then to its model)."""
    run: Callable[..., tuple[list[Path], dict | None]] | None
    """Runs the generation harness once per challenger on a split (reusing reports
    already written when asked) and returns their reports, with the screen that chose
    the challengers (None for a rule that does not screen); the shipped run and Control
    Run come from the round (`_round_runs`). The Arm and settings rules' screen every
    candidate on Evidence Reached first (ADR 0011) and answer only through the ones it
    keeps. The generator rule's also takes `only`, the models to limit the run to; the
    settings rule's `settings`, the (chunk size, context budget) pairs to compare. None
    for a rule that `compare` alone applies: the prompt rules, whose candidates are run
    by `make eval-generation NAME=...`."""
    choice_file: str
    """The default file the choice is written to, before `-<split>.json`."""
    fallback: str = "model"
    """The report field that names a candidate whose report has no `named_by` field."""


_PROMPT_GUARDRAILS: tuple[Score, ...] = (
    "fact_recall",
    "faithfulness",
    "coverage_gaps",
    "contradicted_claims",
    "structure",
)
"""The guardrails of both prompt rules (ADR 0017): the Arm rule's, and structure."""

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
    "prompts": Rule(
        ahead_on_any=("stated_facts",),
        behind_on_none=_PROMPT_GUARDRAILS,
        named_by="name",
        fallback="prompt_version",
        run=None,
        choice_file="prompt-choice",
    ),
    "prompt-fix": Rule(
        ahead_on_any=("figures",),
        behind_on_none=(*_PROMPT_GUARDRAILS, "stated_facts"),
        named_by="name",
        fallback="prompt_version",
        run=None,
        choice_file="prompt-fix-choice",
    ),
}
"""The only place the rules differ. Under the Arm and settings rules Fact Recall is
ahead by the fact-level test (`stated_facts`, ADR 0015) and the per-case sign test on it
is a guardrail; the generator rule decides Fact Recall per case, as ADR 0011 states.
The prompt rules (ADR 0017) have no command of their own: `compare` applies them to a
candidate's report written by `make eval-generation NAME=...`. `prompts` is the Arm
rule with structure followed added to the guardrails; `prompt-fix` is ahead when fewer
cases fail the figure check (`figures`), and adds facts stated to the guardrails."""

_UNRECORDED_CUTOFF = 0.5
"""The fact cut-off of a generation report saved before it recorded one
(`edgar_eval.judge.FACT_CUTOFF`'s note)."""


@dataclass(frozen=True)
class FactOutcome:
    """One must-state Required Fact in one answer."""

    stated: bool | Fraction
    """Whether the answer counts as stating it: Jev's probability at least the report's
    fact cut-off, and never in a truncated answer. For a side of several runs
    (`Candidate.from_reports`), the share of its runs that state it."""
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
    structure: Mapping[str, bool | None] = field(default_factory=dict)
    """Whether each case's answer follows the structure (assumption 8, the structure
    check); None for a report that does not record it."""
    figures: Mapping[str, bool | None] = field(default_factory=dict)
    """Whether each case's answer passes the figure check; None when unrecorded."""
    prompt_version: str | None = None
    code_version: str | None = None
    """The prompt and code versions the report records, which a choice file records."""
    runs: int = 1
    """The runs this side's scores are the mean of (`from_reports`)."""

    @classmethod
    def from_report(cls, report: Mapping[str, Any], rule: RuleName = "arms") -> Candidate:
        """A candidate from a generation harness report (its JSON), named as the rule
        names candidates: by its Arm or by its model."""
        cases = report["cases"]
        costs = [c.get("cost_usd") for c in cases]
        spec = RULES[rule]
        name = report.get(spec.named_by) or report.get(spec.fallback) or report["model"]
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
            structure={c["case_id"]: _passed(c, "structure", "problems") for c in cases},
            figures={c["case_id"]: _passed(c, "figures", "unmatched") for c in cases},
            prompt_version=report.get("prompt_version"),
            code_version=report.get("code_version"),
        )

    @classmethod
    def from_reports(
        cls, reports: Sequence[Mapping[str, Any]], rule: RuleName = "arms"
    ) -> Candidate:
        """One side of a comparison answered by several runs of one setup (ADR 0017's note
        of 2026-10-21): each case's score is the mean over the runs that scored it (a
        pass/fail score as the share of runs passing), each must-state fact is stated by
        the share of the runs that state it, and the cost is the runs' mean. The side is
        named by its first run, so a second run may carry a name of its own. The runs
        must record one setup (`_SETUP`), or this refuses them. One report reads as
        `from_report` reads it."""
        if not reports:
            raise ValueError("a side needs at least one run")
        runs = [cls.from_report(r, rule) for r in reports]
        if len(runs) == 1:
            return runs[0]
        for key in _SETUP:
            recorded = {json.dumps(r.get(key)) for r in reports}
            if len(recorded) > 1:
                raise ValueError(
                    f"the runs of one side must be of one setup, but they record different "
                    f"{key}: {', '.join(sorted(recorded))}"
                )
        costs = [r.cost_usd for r in runs]
        codes = dict.fromkeys(r.code_version for r in runs)
        return replace(
            runs[0],
            fact_recall=_mean_scores([r.fact_recall for r in runs]),
            faithfulness=_mean_scores([r.faithfulness for r in runs]),
            coverage_gaps=_mean_scores([r.coverage_gaps for r in runs]),
            cost_usd=None if None in costs else fmean(costs),  # type: ignore[arg-type]
            contradicted_claims=_mean_scores([r.contradicted_claims for r in runs]),
            query_api_call=any(r.query_api_call for r in runs),
            facts=_mean_facts([r.facts for r in runs]),
            structure=_mean_scores([r.structure for r in runs]),
            figures=_mean_scores([r.figures for r in runs]),
            code_version=next(iter(codes))
            if len(codes) == 1
            else "+".join(c or "unrecorded" for c in codes),
            runs=len(runs),
        )


_SETUP = (
    "split",
    "model",
    "arm",
    "settings",
    "prompt_version",
    "golden_set_version",
    "judge_model",
    "fact_cutoff",
)
"""What the runs of one side must record alike: one setup answering the same split,
judged alike. The code version may differ (a harness change between runs), and is
recorded."""


def _mean_scores(
    runs: Sequence[Mapping[str, float | bool | None]],
) -> dict[str, float | Fraction | None]:
    """Each case's mean over the runs that scored it, None when none did; a pass/fail
    score's mean is the exact share of runs passing."""
    means: dict[str, float | Fraction | None] = {}
    for case in dict.fromkeys(c for run in runs for c in run):
        values = [v for run in runs if (v := run.get(case)) is not None]
        if not values:
            means[case] = None
        elif all(isinstance(v, bool) for v in values):
            means[case] = Fraction(sum(values), len(values))
        else:
            means[case] = fmean(values)
    return means


def _mean_facts(
    runs: Sequence[Mapping[str, tuple[FactOutcome, ...] | None]],
) -> dict[str, tuple[FactOutcome, ...] | None]:
    """Each case's must-state facts, each stated by the share of the runs that scored the
    case and state it; reached as the runs record it, None where they differ."""
    means: dict[str, tuple[FactOutcome, ...] | None] = {}
    for case in dict.fromkeys(c for run in runs for c in run):
        scored = [facts for run in runs if (facts := run.get(case)) is not None]
        if not scored:
            means[case] = None
            continue
        if len({len(facts) for facts in scored}) > 1:
            raise ValueError(f"{case}: the runs of one side have different must-state facts")
        means[case] = tuple(
            FactOutcome(
                stated=Fraction(sum(f.stated for f in column), len(column)),
                reached=column[0].reached if len({f.reached for f in column}) == 1 else None,
            )
            for column in zip(*scored, strict=True)
        )
    return means


def _number(value: int | Fraction) -> int | float:
    """A count as a choice file records it: whole, or a mean of several runs a side."""
    value = Fraction(value)
    return int(value) if value.denominator == 1 else float(value)


def _passed(case: Mapping[str, Any], check: str, failures: str) -> bool | None:
    """Whether a report's case passes a check in code that records what failed it (the
    structure check's problems, the figure check's unmatched figures), or None when the
    case records no such check."""
    record = case.get(check)
    return None if record is None else not record[failures]


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
    challenger_stated: int | float
    shipped_stated: int | float
    """Each side's facts stated: a mean over its runs with several runs a side."""


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
    challenger_stated: int | float
    shipped_stated: int | float
    """Each side's facts stated: a mean over its runs with several runs a side."""
    total_difference: int | float
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
class FigureComparison:
    """The figure check, case by case: how many of the cases both sides recorded each
    side's answer fails. `prompt-fix`'s ahead metric (ADR 0017)."""

    paired: int
    """The cases both sides recorded a figure check for."""
    challenger_failed: int | float
    shipped_failed: int | float
    """Each side's cases failing: a mean over its runs with several runs a side."""
    fixed: int | float
    """Paired cases the shipped choice failed and the challenger passed (with several runs
    a side, the share of runs passing gained, summed)."""
    broken: int | float
    """Paired cases the challenger failed and the shipped choice passed (likewise)."""
    verdict: Verdict
    """`ahead` when fewer paired cases fail for the challenger, `behind` when more, else
    `indistinguishable`: a count, as the prompt log's rule for a correctness fix is, not a
    test."""


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
    structure: ScoreComparison
    """Structure followed, paired per case: a guardrail of the prompt rules only."""
    figures: FigureComparison
    """The figure check's failures: `prompt-fix`'s ahead metric."""
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
    runs: dict[str, int] = field(default_factory=dict)
    """The runs each side's scores are the mean of, named as `costs` names them."""
    control_runs: int | None = None
    """The Control Run's runs; None without a Control Run."""


_SCORES = ("fact_recall", "faithfulness", "coverage_gaps", "contradicted_claims", "structure")
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
    groups: dict[str, list[Any]] = {status: [0, 0, 0] for status in EVIDENCE_STATUSES}
    differences: list[Fraction] = []
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
        differences.append(
            Fraction(sum(a.stated for a in mine)) - Fraction(sum(b.stated for b in theirs))
        )
    # A mean over several runs a side need not be whole: the test runs on the differences
    # scaled to whole numbers, which leaves its p-values unchanged (the resampled cases
    # are drawn alike whatever their values), and the total is scaled back.
    scale = lcm(*(d.denominator for d in differences)) if differences else 1
    test = cluster_bootstrap_test([int(d * scale) for d in differences])
    verdict: Verdict = "indistinguishable"
    if test.p_ahead < AHEAD_P:
        verdict = "ahead"
    elif test.p_behind < BEHIND_P:
        verdict = "behind"
    return FactComparison(
        paired=len(both),
        left_out=len(scored_a ^ scored_b),
        facts=sum(g[0] for g in groups.values()),
        challenger_stated=_number(sum(g[1] for g in groups.values())),
        shipped_stated=_number(sum(g[2] for g in groups.values())),
        total_difference=_number(Fraction(test.total, scale)),
        p_ahead=test.p_ahead,
        p_behind=test.p_behind,
        verdict=verdict,
        difference=bootstrap_interval([float(d) for d in differences]),
        by_evidence={
            s: EvidenceGroup(g[0], _number(g[1]), _number(g[2])) for s, g in groups.items()
        },
        resamples=test.resamples,
        seed=test.seed,
    )


def _compare_figures(
    challenger: Mapping[str, bool | Fraction | None], shipped: Mapping[str, bool | Fraction | None]
) -> FigureComparison:
    both = sorted(
        c for c in challenger.keys() & shipped.keys() if None not in (challenger[c], shipped[c])
    )
    # Each case's share of runs passing (1 or 0 for one run a side).
    mine = {c: Fraction(challenger[c]) for c in both}  # type: ignore[arg-type]
    theirs = {c: Fraction(shipped[c]) for c in both}  # type: ignore[arg-type]
    failed = sum(1 - mine[c] for c in both)
    shipped_failed = sum(1 - theirs[c] for c in both)
    verdict: Verdict = "indistinguishable"
    if failed < shipped_failed:
        verdict = "ahead"
    elif failed > shipped_failed:
        verdict = "behind"
    return FigureComparison(
        paired=len(both),
        challenger_failed=_number(failed),
        shipped_failed=_number(shipped_failed),
        fixed=_number(sum(max(mine[c] - theirs[c], 0) for c in both)),
        broken=_number(sum(max(theirs[c] - mine[c], 0) for c in both)),
        verdict=verdict,
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
    scores["figures"] = _compare_figures(challenger.figures, shipped.figures)
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
    "structure": "Structure followed",
    "figures": "Figures exact",
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
        runs={c.name: c.runs for c in (shipped, *challengers)},
        control_runs=control.runs if control is not None else None,
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
    reports.add_argument(
        "reports",
        type=_side,
        nargs="+",
        help="the shipped choice's first; several runs of one side joined by +",
    )
    reports.add_argument(
        "--control", type=_side, help="the Control Run's report (several runs joined by +)"
    )
    reports.add_argument("--rule", choices=tuple(RULES), default="arms")
    reports.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    rule: RuleName
    screen: dict | None = None
    sides: list[tuple[Path, ...]]
    control: tuple[Path, ...] | None
    if args.command == "compare":
        rule, sides, control, target = args.rule, args.reports, args.control, args.json
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
        shipped_path, control_path = _round_runs(args.split, out)
        run = RULES[rule].run
        assert run is not None  # every command's rule runs its challengers
        challengers, screen = run(args.split, args.reuse, out, **options)
        sides = [(shipped_path,), *((c,) for c in challengers)]
        control = (control_path,)
        target = args.json or _EVAL_DIR / f"{RULES[rule].choice_file}-{args.split}.json"
    data = [[_load(p) for p in side] for side in sides]
    candidates = _distinct(
        [Candidate.from_reports(d, rule) for d in data], [side[0] for side in sides]
    )
    control_data = [_load(p) for p in control] if control else []
    control_candidate = Candidate.from_reports(control_data, rule) if control_data else None
    choice = choose(candidates[0], candidates[1:], rule, control=control_candidate)
    _print(choice, out)
    # Each side as `capped` and `versions` name it, with its reports and their paths.
    shipped = candidates[0].name
    named = [(f"{shipped} (shipped run)", data[0], sides[0])]
    if control:
        named.append((f"{shipped} (Control Run)", control_data, control))
    named += zip([c.name for c in candidates[1:]], data[1:], sides[1:], strict=True)
    capped = {
        _run_name(name, i, len(reports)): _capped(report)
        for name, reports, _ in named
        for i, report in enumerate(reports, 1)
    }
    _print_capped(capped, out)
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "split": data[0][0].get("split"),
            "reports": [str(side[0]) for side in sides],
            "control_report": str(control[0]) if control else None,
            "capped": capped,
            "versions": _versions(candidates, control_candidate),
        }
        if any(len(paths) > 1 for _, _, paths in named):
            record["run_reports"] = {name: [str(p) for p in paths] for name, _, paths in named}
        if screen is not None:
            record["screen"] = screen
        target.write_text(json.dumps(record | asdict(choice), indent=2) + "\n", encoding="utf-8")
        print(f"\nWritten to {target.resolve()}", file=out)
    return 0


def _side(value: str) -> tuple[Path, ...]:
    """A side of a comparison on the command line: one report, or several runs of one
    setup joined by `+` (`generation-dev.json+generation-dev-run2.json`)."""
    return tuple(Path(part) for part in value.split("+") if part)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _run_name(side: str, run: int, runs: int) -> str:
    """How `capped` names one run of a side: the side's name alone with one run, else
    numbered, `v15 (shipped run 2)`, `v16 (run 2)`."""
    if runs == 1:
        return side
    if side.endswith(")"):
        return f"{side[:-1]} {run})"
    return f"{side} (run {run})"


def _distinct(candidates: list[Candidate], paths: Sequence[Path]) -> list[Candidate]:
    """The candidates, each challenger named apart from the shipped choice and from the
    others: one whose name another already has (reports of one prompt version, under a
    prompt rule) takes its report's file name beside it, `v7 (generation-dev-x)`."""
    from dataclasses import replace

    seen = {candidates[0].name}
    named = [candidates[0]]
    for candidate, path in zip(candidates[1:], paths[1:], strict=True):
        if candidate.name in seen:
            candidate = replace(candidate, name=f"{candidate.name} ({Path(path).stem})")
        seen.add(candidate.name)
        named.append(candidate)
    return named


def _versions(
    candidates: Sequence[Candidate], control: Candidate | None
) -> dict[str, dict[str, str | None]]:
    """The prompt and code versions each side's report records, named as `capped` names
    the runs: what a choice file records of both sides (ADR 0017)."""
    runs = [(f"{candidates[0].name} (shipped run)", candidates[0])]
    if control is not None:
        runs.append((f"{candidates[0].name} (Control Run)", control))
    runs += [(c.name, c) for c in candidates[1:]]
    return {
        name: {"prompt_version": c.prompt_version, "code_version": c.code_version}
        for name, c in runs
    }


def _capped(report: Mapping[str, Any]) -> list[str]:
    """The cases of a generation report whose answer stopped at the token cap."""
    return [c["case_id"] for c in report["cases"] if c.get("truncated")]


def _print_capped(capped: Mapping[str, Sequence[str]], out: TextIO) -> None:
    """Every answer that stopped at the token cap, run by run: each is scored as
    truncated, so none is silent."""
    print("\nAnswers capped (stopped at the token cap, scored as truncated):", file=out)
    for name, cases in capped.items():
        print(f"  {name}: {', '.join(cases) or 'none'}", file=out)


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
    f = c.figures
    print(
        f"  {_LABELS['figures']}: {f.verdict} ({_show(f.challenger_failed)} of {f.paired} "
        f"cases failing the figure check against {_show(f.shipped_failed)}; "
        f"{_show(f.fixed)} fixed, {_show(f.broken)} broken)",
        file=out,
    )


def _show(count: int | float, sign: str = "") -> str:
    """A count as printed: whole, or a mean of several runs a side to one decimal."""
    return f"{count:{sign}d}" if isinstance(count, int) else f"{count:{sign}.1f}"


def _print_facts(f: FactComparison, out: TextIO) -> None:
    d = f.difference
    shift = f"; per case {d.mean:+.3f}, 95% interval [{d.low:+.3f}, {d.high:+.3f}]" if d else ""
    print(
        f"  {_LABELS['stated_facts']}: {f.verdict} ({_show(f.challenger_stated)} of {f.facts} "
        f"must-state facts stated against {_show(f.shipped_stated)}, "
        f"{_show(f.total_difference, '+')}, "
        f"p ahead = {f.p_ahead:.3f}, p behind = {f.p_behind:.3f}; {f.paired} cases paired, "
        f"{f.left_out} left out{shift})",
        file=out,
    )
    groups = ", ".join(
        f"{status.replace('_', ' ')} {_show(g.challenger_stated)} / {_show(g.shipped_stated)} "
        f"of {g.facts}"
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
    runs = dict(choice.runs)
    if choice.control_runs is not None:
        runs["Control Run"] = choice.control_runs
    if any(n > 1 for n in runs.values()):
        counted = ", ".join(f"{name} {n} run{'s' if n > 1 else ''}" for name, n in runs.items())
        print(
            "Each side's per-case scores are the mean of its runs, and its counts a mean per "
            f"run: {counted}.",
            file=out,
        )
    if choice.control is not None:
        several = f"{choice.control_runs} runs, " if (choice.control_runs or 1) > 1 else ""
        print(
            f"\nControl Run ({choice.shipped} run again, {several}{choice.control.cases} "
            "cases): within noise unless ahead of the shipped run",
            file=out,
        )
        _print_scores(choice.control, out)
    else:
        print("\nNo Control Run: the noise of this comparison is not shown.", file=out)
    for name, c in choice.comparisons.items():
        cost = choice.costs[name]
        n = choice.runs.get(name, 1)
        several = f"{n} runs, " if n > 1 else ""
        print(f"\n{name} ({c.cases} cases, {several}${cost or 0:.4f} per answer)", file=out)
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
