"""The selection rule: which retrieval Arm (or generator) ships, decided by the
generation harness's scores on paired cases.

The shipped choice stays unless a challenger is **distinguishably better on Fact
Recall** (the exact sign test on per-case Fact Recall, p < 0.05) **and not worse on
Faithfulness or Coverage Gaps** (neither sign test says `behind`). When several
challengers qualify, the **cheapest** wins: the lowest mean answer cost, then the
earliest listed. Cases either side could not score, or that only one side answered, are
left out of each test.

    python -m edgar_eval.selection arms [--split dev] [--reuse]
    python -m edgar_eval.selection compare SHIPPED.json CHALLENGER.json... [--json PATH]

`arms` runs the generation harness once per Arm in `edgar_eval.arms.ARMS`, writing
`data/derived/eval/generation-arms-<split>-<arm>.json` (with `--reuse`, an existing
report is read instead of rerun), and then compares them: the Shipped Arm against each
challenger. It calls the generator and Jev for every Arm, so it costs money (about
$0.07 per Arm on dev). `compare` applies the rule to generation reports already
written, the first being the shipped choice. Both print the comparison and write it,
with the choice, to `--json` (by default `data/derived/eval/arm-choice-<split>.json`).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, TextIO

from edgar_eval.metrics import McNemarResult, sign_test

__all__ = ["Candidate", "Choice", "Comparison", "choose", "main", "sign_test"]

_EVAL_DIR = Path(__file__).resolve().parents[3] / "data" / "derived" / "eval"


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
    def from_report(cls, report: Mapping[str, Any]) -> Candidate:
        """A candidate from a generation harness report (its JSON)."""
        cases = report["cases"]
        costs = [c.get("cost_usd") for c in cases]
        return cls(
            name=report.get("arm") or report["model"],
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
    """Ahead on Fact Recall and behind on neither Faithfulness nor Coverage Gaps."""


@dataclass(frozen=True)
class Choice:
    shipped: str
    chosen: str
    comparisons: dict[str, Comparison]
    costs: dict[str, float | None]


def compare(challenger: Candidate, shipped: Candidate) -> Comparison:
    cases = sorted(set(challenger.fact_recall) & set(shipped.fact_recall))

    def test(field: str) -> McNemarResult:
        a, b = getattr(challenger, field), getattr(shipped, field)
        return sign_test([a[c] for c in cases], [b[c] for c in cases])

    recall, faithful, gaps = test("fact_recall"), test("faithfulness"), test("coverage_gaps")
    return Comparison(
        cases=len(cases),
        fact_recall=recall,
        faithfulness=faithful,
        coverage_gaps=gaps,
        qualifies=recall.verdict == "ahead" and "behind" not in (faithful.verdict, gaps.verdict),
    )


def choose(shipped: Candidate, challengers: Sequence[Candidate]) -> Choice:
    """Apply the selection rule."""
    comparisons = {c.name: compare(c, shipped) for c in challengers}
    qualifying = [
        (c.cost_usd if c.cost_usd is not None else float("inf"), n, c.name)
        for n, c in enumerate(challengers)
        if comparisons[c.name].qualifies
    ]
    return Choice(
        shipped=shipped.name,
        chosen=min(qualifying)[2] if qualifying else shipped.name,
        comparisons=comparisons,
        costs={c.name: c.cost_usd for c in (shipped, *challengers)},
    )


# --- Command line -------------------------------------------------------------------------


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


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description="Choose between Arms by the selection rule.")
    commands = parser.add_subparsers(dest="command", required=True)
    arms = commands.add_parser("arms", help="run every Arm through the generation harness")
    arms.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
    arms.add_argument("--reuse", action="store_true", help="read reports already written")
    arms.add_argument("--json", type=Path)
    reports = commands.add_parser("compare", help="compare generation reports")
    reports.add_argument("reports", type=Path, nargs="+", help="the shipped choice's first")
    reports.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    if args.command == "arms":
        paths = _run_arms(args.split, args.reuse, out)
        target = args.json or _EVAL_DIR / f"arm-choice-{args.split}.json"
    else:
        paths, target = args.reports, args.json
    data = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    candidates = [Candidate.from_report(d) for d in data]
    choice = choose(candidates[0], candidates[1:])
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
        for label, r in (
            ("Fact Recall", c.fact_recall),
            ("Faithfulness", c.faithfulness),
            ("Coverage Gaps", c.coverage_gaps),
        ):
            print(
                f"  {label}: {r.verdict} ({r.challenger_only} cases higher, "
                f"{r.shipped_only} lower, exact p = {r.p_value:.3f})",
                file=out,
            )
        print(f"  Qualifies: {'yes' if c.qualifies else 'no'}", file=out)
    print(f"\nChosen: {choice.chosen}", file=out)


if __name__ == "__main__":
    raise SystemExit(main())
