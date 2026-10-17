"""The selection rules: which retrieval Arm, and which generator, ships, decided by the
generation harness's scores on paired cases.

Each score is compared case by case with the exact sign test (p < 0.05). Each score
pairs only the cases both sides scored: a case one side could not score (its judgment
failed, or it was not answered) is left out of that score's test, never counted as a
zero, and each comparison reports how many cases each score paired and left out.

- **Arms** (user story 54): the Shipped Arm stays unless a challenger is
  **distinguishably better on Fact Recall** and **not worse on Faithfulness or Coverage
  Gaps** (neither test says `behind`).
- **Generators** (user story 55): the shipped generator stays unless a challenger is
  **distinguishably better on Fact Recall or on Coverage Gaps** and **worse on none of
  Fact Recall, Faithfulness and Coverage Gaps**.

- **Settings** (ADR 0010): a chunk size and context budget replace the shipped ones under
  the Arm rule. Each setting's report comes from `make eval-generation` with
  `CHUNK_TOKENS` and `CONTEXT_BUDGET`, and is named by its setting
  (`chunks-600-budget-32000`); only `compare` applies it.

Under any rule, when several challengers qualify, the **cheapest** wins: the lowest
mean answer cost, then the earliest listed. `RULES` states the rules, and is the only
place they differ.

    python -m edgar_eval.selection arms [--split dev] [--reuse]
    python -m edgar_eval.selection generators [--split dev] [--reuse] [--model MODEL]...
    python -m edgar_eval.selection compare SHIPPED.json CHALLENGER.json...
        [--rule arms|generators|settings] [--json PATH]

`arms` runs the generation harness once per Arm in `edgar_eval.arms.ARMS`, writing
`data/derived/eval/generation-arms-<split>-<arm>.json`, and compares the Shipped Arm
with each challenger. `generators` runs it once per model in
`edgar_eval.generators.GENERATORS` on the Shipped Arm, writing the default generator's
report to `generation-<split>.json` and each other's to `generation-<split>-<model>.json`
(the names `make eval-generation` uses), and compares the default with each other model;
`--model` (repeatable) limits it to the generators named, the default always run first
(`make eval-generators` passes `gpt-6-luna` and `claude-haiku-5-5`, Golden Set version
2's comparison, unless `MODELS=` says otherwise).
With `--reuse`, a report already written is read instead of rerun. Both call the
generators and Jev, so they cost money. `compare` applies a rule to generation reports
already written, the first being the shipped choice. All three print the comparison and
write it, with the choice, to `--json` (by default
`data/derived/eval/<arm|generator>-choice-<split>.json`).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Literal, TextIO

from edgar_eval.metrics import McNemarResult, sign_test
from edgar_rag.paths import DERIVED_DIR

__all__ = [
    "RULES",
    "Candidate",
    "Choice",
    "Comparison",
    "Rule",
    "RuleName",
    "choose",
    "main",
    "sign_test",
]

_EVAL_DIR = DERIVED_DIR / "eval"

RuleName = Literal["arms", "generators", "settings"]
Score = Literal["fact_recall", "faithfulness", "coverage_gaps"]


def _run_arms(split: str, reuse: bool, out: TextIO) -> list[Path]:
    from edgar_eval import generation
    from edgar_eval.arms import ARMS

    paths = []
    for arm in sorted(ARMS, key=lambda a: not a.shipped):
        path = _EVAL_DIR / f"generation-arms-{split}-{arm.name}.json"
        if not (reuse and path.exists()):
            print(f"\n== Arm {arm.name} ==", file=out, flush=True)
            generation.main(["--split", split, "--arm", arm.name, "--json", str(path)], out=out)
        paths.append(path)
    return paths


def _run_generators(split: str, reuse: bool, out: TextIO, only: Sequence[str] = ()) -> list[Path]:
    from edgar_eval import generation
    from edgar_eval.generators import GENERATORS, generator

    unknown = [m for m in only if generator(m) is None]
    if unknown:
        listed = ", ".join(g.model for g in GENERATORS)
        raise SystemExit(f"error: not compared generators: {', '.join(unknown)} (one of {listed})")
    models = [g.model for g in GENERATORS if g is GENERATORS[0] or not only or g.model in only]
    paths = []
    for n, model in enumerate(models):
        path = _EVAL_DIR / (
            f"generation-{split}.json" if n == 0 else f"generation-{split}-{model}.json"
        )
        if not (reuse and path.exists()):
            print(f"\n== Generator {model} ==", file=out, flush=True)
            generation.main(["--split", split, "--model", model, "--json", str(path)], out=out)
        paths.append(path)
    return paths


@dataclass(frozen=True)
class Rule:
    """What one selection rule decides by. A challenger qualifies when the sign test
    puts it `ahead` on at least one of `ahead_on_any` and `behind` on none of
    `behind_on_none`."""

    ahead_on_any: tuple[Score, ...]
    behind_on_none: tuple[Score, ...]
    named_by: str
    """The generation report field that names a candidate (falling back to its model)."""
    run: Callable[..., list[Path]] | None
    """Runs the generation harness once per candidate on a split (reusing reports already
    written when asked) and returns the reports, the shipped choice's first; None for a
    rule applied only to reports already written (`compare`). The generator rule's also
    takes `only`, the models to limit the run to."""
    choice_file: str
    """The default file the choice is written to, before `-<split>.json`."""


RULES: dict[RuleName, Rule] = {
    "arms": Rule(
        ahead_on_any=("fact_recall",),
        behind_on_none=("faithfulness", "coverage_gaps"),
        named_by="arm",
        run=_run_arms,
        choice_file="arm-choice",
    ),
    "generators": Rule(
        ahead_on_any=("fact_recall", "coverage_gaps"),
        behind_on_none=("fact_recall", "faithfulness", "coverage_gaps"),
        named_by="model",
        run=_run_generators,
        choice_file="generator-choice",
    ),
    "settings": Rule(
        ahead_on_any=("fact_recall",),
        behind_on_none=("faithfulness", "coverage_gaps"),
        named_by="settings",
        run=None,
        choice_file="settings-choice",
    ),
}
"""The only place the rules differ."""


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
        )


@dataclass(frozen=True)
class Comparison:
    """A challenger against the shipped choice, case by case."""

    cases: int
    """Cases both answered."""
    fact_recall: McNemarResult
    faithfulness: McNemarResult
    coverage_gaps: McNemarResult
    qualifies: bool
    """Whether the challenger qualifies under the rule it was compared by."""
    paired: dict[Score, int]
    """Per score, the cases both sides scored, which its test pairs."""
    left_out: dict[Score, int]
    """Per score, the cases only one side scored, left out of its test. Cases neither
    side scored (nothing to score, such as no expected Coverage Gap) are in neither."""


@dataclass(frozen=True)
class Choice:
    rule: RuleName
    shipped: str
    chosen: str
    comparisons: dict[str, Comparison]
    costs: dict[str, float | None]


_SCORES: tuple[Score, ...] = ("fact_recall", "faithfulness", "coverage_gaps")


def compare(challenger: Candidate, shipped: Candidate, rule: RuleName = "arms") -> Comparison:
    answered = set(challenger.fact_recall) & set(shipped.fact_recall)
    tests: dict[Score, McNemarResult] = {}
    paired: dict[Score, int] = {}
    left_out: dict[Score, int] = {}
    for field in _SCORES:
        a, b = getattr(challenger, field), getattr(shipped, field)
        scored_a = {c for c, v in a.items() if v is not None}
        scored_b = {c for c, v in b.items() if v is not None}
        both = sorted(scored_a & scored_b)
        tests[field] = sign_test([a[c] for c in both], [b[c] for c in both])
        paired[field], left_out[field] = len(both), len(scored_a ^ scored_b)
    spec = RULES[rule]
    return Comparison(
        cases=len(answered),
        **tests,
        qualifies=any(tests[f].verdict == "ahead" for f in spec.ahead_on_any)
        and all(tests[f].verdict != "behind" for f in spec.behind_on_none),
        paired=paired,
        left_out=left_out,
    )


def choose(shipped: Candidate, challengers: Sequence[Candidate], rule: RuleName = "arms") -> Choice:
    """Apply the selection rule for Arms or for generators."""
    comparisons = {c.name: compare(c, shipped, rule) for c in challengers}
    qualifying = [
        (c.cost_usd if c.cost_usd is not None else float("inf"), n, c.name)
        for n, c in enumerate(challengers)
        if comparisons[c.name].qualifies
    ]
    return Choice(
        rule=rule,
        shipped=shipped.name,
        chosen=min(qualifying)[2] if qualifying else shipped.name,
        comparisons=comparisons,
        costs={c.name: c.cost_usd for c in (shipped, *challengers)},
    )


# --- Command line -------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description="Choose between Arms by the selection rule.")
    commands = parser.add_subparsers(dest="command", required=True)
    arms = commands.add_parser("arms", help="run every Arm through the generation harness")
    arms.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
    arms.add_argument("--reuse", action="store_true", help="read reports already written")
    arms.add_argument("--json", type=Path)
    generators = commands.add_parser("generators", help="run every generator through the harness")
    generators.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
    generators.add_argument("--reuse", action="store_true", help="read reports already written")
    generators.add_argument(
        "--model", action="append", default=[], help="run only this generator (repeatable)"
    )
    generators.add_argument("--json", type=Path)
    reports = commands.add_parser("compare", help="compare generation reports")
    reports.add_argument("reports", type=Path, nargs="+", help="the shipped choice's first")
    reports.add_argument("--rule", choices=tuple(RULES), default="arms")
    reports.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    rule: RuleName
    if args.command == "compare":
        rule, paths, target = args.rule, args.reports, args.json
    else:
        rule = args.command
        run = RULES[rule].run
        assert run is not None
        only = {"only": args.model} if args.command == "generators" else {}
        paths = run(args.split, args.reuse, out, **only)
        target = args.json or _EVAL_DIR / f"{RULES[rule].choice_file}-{args.split}.json"
    data = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    candidates = [Candidate.from_report(d, rule) for d in data]
    choice = choose(candidates[0], candidates[1:], rule)
    _print(choice, out)
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {"split": data[0].get("split"), "reports": [str(p) for p in paths]}
        target.write_text(json.dumps(record | asdict(choice), indent=2) + "\n", encoding="utf-8")
        print(f"\nWritten to {target.resolve()}", file=out)
    return 0


def _print(choice: Choice, out: TextIO) -> None:
    print(f"\nEach challenger against {choice.shipped}, case by case (exact sign test):", file=out)
    for name, c in choice.comparisons.items():
        cost = choice.costs[name]
        print(f"\n{name} ({c.cases} cases, ${cost or 0:.4f} per answer)", file=out)
        for label, field in (
            ("Fact Recall", "fact_recall"),
            ("Faithfulness", "faithfulness"),
            ("Coverage Gaps", "coverage_gaps"),
        ):
            r = getattr(c, field)
            print(
                f"  {label}: {r.verdict} ({r.challenger_only} cases higher, "
                f"{r.shipped_only} lower, exact p = {r.p_value:.3f}; "
                f"{c.paired[field]} cases paired, {c.left_out[field]} left out)",
                file=out,
            )
        print(f"  Qualifies: {'yes' if c.qualifies else 'no'}", file=out)
    print(f"\nChosen: {choice.chosen}", file=out)


if __name__ == "__main__":
    raise SystemExit(main())
