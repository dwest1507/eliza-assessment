"""The retrieval Floors: the lowest scores CI accepts from the Shipped Arm.

`data/eval/retrieval_floors.json` records, for the Shipped Arm on the dev split, a Floor
for each gated metric (hit@10, recall@10 and MRR, overall) and the settings the Floors
were measured at: the Golden Set version, the number of scored cases, the chunk size and
the context budget. CI runs the retrieval harness (no LLM call, so it costs nothing) and
checks its report against the record (ADR 0014):

- a metric below its Floor fails, naming the metric;
- a report measured at other settings fails as stale, since its scores and the Floors
  are not comparable. A change to the Golden Set or the shipped settings re-records the
  Floors in the same commit.

FTS5 ranks deterministically, so a Floor is the measured score rounded down to two
decimals: any case lost at the gated metric fails the gate.

    python -m edgar_eval.floors check REPORT [--floors PATH]
    python -m edgar_eval.floors record REPORT [--floors PATH]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from edgar_rag.paths import DATA_DIR

__all__ = ["DEFAULT_FLOORS", "GATED_K", "check", "main", "measure", "record"]

DEFAULT_FLOORS = DATA_DIR / "eval" / "retrieval_floors.json"

GATED_K = 10
"""The k of the gated hit@k and recall@k, the harness's gating metric."""

SETTINGS = ("split", "arm", "golden_set_version", "cases", "chunk_tokens", "context_budget")
"""What a report must share with the record for its scores to be comparable."""


def measure(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
    """The Shipped Arm's settings and gated scores in a retrieval harness report."""
    shipped = [arm for arm in report["arms"].values() if arm["shipped"]]
    if len(shipped) != 1:
        raise ValueError(f"expected one Shipped Arm in the report, found {len(shipped)}")
    arm = shipped[0]
    overall = arm["overall"]
    settings = {
        "split": report["split"],
        "arm": arm["name"],
        "golden_set_version": report["golden_set_version"],
        "cases": overall["cases"],
        "chunk_tokens": report["chunk_tokens"],
        "context_budget": report["context_budget"],
    }
    scores = {
        f"hit@{GATED_K}": overall["hit"][str(GATED_K)],
        f"recall@{GATED_K}": overall["recall"][str(GATED_K)],
        "mrr": overall["mrr"],
    }
    return settings, scores


def check(report: dict[str, Any], floors: dict[str, Any]) -> list[str]:
    """Every reason the report fails the Floors; none when it passes."""
    settings, scores = measure(report)
    stale = [
        f"{key}: measured at {settings[key]!r}, Floors recorded at {floors[key]!r}"
        for key in SETTINGS
        if settings[key] != floors[key]
    ]
    if stale:
        return ["Floors stale: re-record them (make eval-floors)", *stale]
    return [
        f"{metric} {scores[metric]:.3f} is below its Floor {floor:.2f}"
        for metric, floor in floors["floors"].items()
        if scores[metric] < floor
    ]


def record(report: dict[str, Any]) -> dict[str, Any]:
    """Floors at the report's scores, rounded down to two decimals."""
    settings, scores = measure(report)
    return settings | {
        "floors": {metric: math.floor(score * 100) / 100 for metric, score in scores.items()}
    }


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description="Check or record the retrieval Floors.")
    parser.add_argument("action", choices=("check", "record"))
    parser.add_argument("report", type=Path, help="a retrieval harness report (--json)")
    parser.add_argument("--floors", type=Path, default=DEFAULT_FLOORS)
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))

    if args.action == "record":
        floors = record(report)
        args.floors.write_text(json.dumps(floors, indent=2) + "\n", encoding="utf-8")
        print(f"Floors recorded in {args.floors}: {floors['floors']}", file=out)
        return 0

    floors = json.loads(args.floors.read_text(encoding="utf-8"))
    _, scores = measure(report)
    for metric, floor in floors["floors"].items():
        print(f"{metric}: {scores[metric]:.3f} (Floor {floor:.2f})", file=out)
    failures = check(report, floors)
    for failure in failures:
        print(f"FAIL {failure}", file=out)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
