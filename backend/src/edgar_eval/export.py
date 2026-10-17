"""The evaluation export: the harnesses' latest results and the Corpus coverage, as one
JSON file for the front-end's "How it works" page.

It reads the reports the harnesses last wrote for a split under `data/derived/eval/`:

- `retrieval-<split>.json` (`make eval-retrieval`): every Arm's scores, overall and per
  question type, and each challenger's comparison with the Shipped Arm. Required.
- `generation-<split>[-<model>].json` (`make eval-generation`): one per generator run,
  each with its scores, cost and latency. Optional, since a run costs money: the export
  lists none until one has run.
- `generator-choice-<split>.json` (`make eval-generators`): each challenger generator's
  sign tests against the shipped one, and the generator the rule chose. Optional.

Beside a dev (or all) export it carries the holdout's reports, `retrieval-holdout.json`
and every `generation-holdout[-<suffix>].json`, when the holdout has been scored, so the
page shows the holdout run (or runs) next to the numbers the choices were made on.

It adds the Corpus coverage grid (each Company's Filings by the calendar quarter of
their Report Periods, Tracked Companies first) and writes everything, in the
front-end's camelCase, to `frontend/data/eval-export.json`. The file is committed, so
the page shows the results without anyone rerunning the harnesses.

    python -m edgar_eval.export [--split dev|holdout|all] [--eval-dir DIR] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from edgar_rag.corpus import Filing, load_corpus, report_quarter
from edgar_rag.golden_set import DEFAULT_GOLDEN_SET, load_golden_set
from edgar_rag.paths import DERIVED_DIR, REPO_ROOT

__all__ = ["DEFAULT_EVAL_DIR", "DEFAULT_EXPORT", "coverage_grid", "export", "main"]

DEFAULT_EVAL_DIR = DERIVED_DIR / "eval"
DEFAULT_EXPORT = REPO_ROOT / "frontend" / "data" / "eval-export.json"

_COVERAGE_ORDER = ("tracked", "snapshot")


def export(
    split: str,
    eval_dir: Path,
    filings: Sequence[Filing],
    today: date,
    golden_set: Path = DEFAULT_GOLDEN_SET,
) -> dict[str, Any]:
    """The front-end's export for a split, from the harnesses' reports in `eval_dir`."""
    retrieval_path = eval_dir / f"retrieval-{split}.json"
    if not retrieval_path.exists():
        raise SystemExit(
            f"error: no retrieval report at {retrieval_path}. Run "
            f"`make eval-retrieval SPLIT={split}` first."
        )
    golden = load_golden_set(golden_set)
    cases = golden.cases if split == "all" else golden.split(split)
    choice_path = eval_dir / f"generator-choice-{split}.json"
    return {
        "exportedOn": today.isoformat(),
        "split": split,
        "goldenSet": {
            "version": golden.version,
            "cases": len(golden.cases),
            "splitCases": len(cases),
        },
        "retrieval": _retrieval(_read(retrieval_path)),
        "generation": [_generation(path) for path in _generation_paths(eval_dir, split)],
        "generatorChoice": _generator_choice(_read(choice_path)) if choice_path.exists() else None,
        "holdout": None if split == "holdout" else _holdout(eval_dir, len(golden.split("holdout"))),
        "coverage": coverage_grid(filings),
    }


def _generation_paths(eval_dir: Path, split: str) -> list[Path]:
    """A split's generation reports: the shipped generator's first, then the others."""
    return sorted(eval_dir.glob(f"generation-{split}.json")) + sorted(
        eval_dir.glob(f"generation-{split}-*.json")
    )


def _holdout(eval_dir: Path, split_cases: int) -> dict[str, Any] | None:
    """The holdout's reports, or None when it has not been scored."""
    retrieval_path = eval_dir / "retrieval-holdout.json"
    generation_paths = _generation_paths(eval_dir, "holdout")
    if not retrieval_path.exists() and not generation_paths:
        return None
    return {
        "splitCases": split_cases,
        "retrieval": _retrieval(_read(retrieval_path)) if retrieval_path.exists() else None,
        "generation": [_generation(path) for path in generation_paths],
    }


def coverage_grid(filings: Iterable[Filing]) -> dict[str, Any]:
    """Each Company's Filings by the calendar quarter of their Report Period.

    The periods are the quarters that hold at least one Filing, in order. Companies are
    listed Tracked first, then Snapshot, each by Sector and then ticker.
    """
    companies: dict[str, dict[str, Any]] = {}
    for filing in sorted(filings, key=lambda f: (f.ticker, f.report_period)):
        company = companies.setdefault(
            filing.ticker,
            {
                "ticker": filing.ticker,
                "company": filing.company,
                "sector": filing.sector,
                "coverage": filing.coverage,
                "filings": [],
            },
        )
        company["filings"].append(
            {
                "period": report_quarter(filing.report_period),
                "filingId": filing.filing_id,
                "formType": filing.form_type,
                "reportPeriod": filing.report_period.isoformat(),
                "fiscalPeriod": filing.fiscal_period,
            }
        )
    rows = sorted(
        companies.values(),
        key=lambda c: (
            _COVERAGE_ORDER.index(c["coverage"]) if c["coverage"] in _COVERAGE_ORDER else 2,
            c["sector"] or "",
            c["ticker"],
        ),
    )
    periods = sorted({f["period"] for c in rows for f in c["filings"]})
    return {"periods": periods, "companies": rows}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _retrieval(report: dict[str, Any]) -> dict[str, Any]:
    gate = str(report["gate_k"])
    return {
        "gatingMetric": report["gating_metric"],
        "ks": report["ks"],
        "scoredCases": len(report["case_ids"]),
        "unscored": report["unscored"],
        "arms": [
            {
                "name": arm["name"],
                "shipped": arm["shipped"],
                "overall": _retrieval_summary(arm["overall"]),
                "byType": [
                    {"questionType": kind} | _retrieval_summary(summary)
                    for kind, summary in sorted(arm["by_type"].items())
                ],
                "missed": [c["case_id"] for c in arm["cases"] if not c["hit"][gate]],
            }
            # The Shipped Arm first, then the challengers in the harness's order.
            for arm in sorted(report["arms"].values(), key=lambda a: not a["shipped"])
        ],
        "comparisons": [
            {
                "arm": c["arm"],
                "shippedArm": c["shipped_arm"],
                "metric": c["metric"],
                "challengerOnly": c["result"]["challenger_only"],
                "shippedOnly": c["result"]["shipped_only"],
                "pValue": c["result"]["p_value"],
                "verdict": c["result"]["verdict"],
            }
            for c in report["comparisons"]
        ],
    }


def _retrieval_summary(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "cases": s["cases"],
        "hitAt": s["hit"],
        "recallAt": s["recall"],
        "hitAll": s["hit_all"],
        "recallAll": s["recall_all"],
        "mrr": s["mrr"],
        "meanSources": s["mean_sources"],
    }


def _generation(path: Path) -> dict[str, Any]:
    report = _read(path)
    cases = report["cases"]
    return {
        "report": path.name,
        "model": report["model"],
        "judgeModel": report["judge_model"],
        "promptVersion": report["prompt_version"],
        "overall": _generation_summary(report["overall"]),
        "byType": [
            {"questionType": kind} | _generation_summary(summary)
            for kind, summary in sorted(report["by_type"].items())
        ],
        "failing": {
            "citations": [
                c["case_id"]
                for c in cases
                if c["citations"]["unknown_tags"] or c["citations"]["uncited"]
            ],
            "figures": [c["case_id"] for c in cases if c["figures"]["unmatched"]],
            "coverageGaps": [
                c["case_id"] for c in cases if c["coverage_gaps"] and c["coverage_gaps"]["missing"]
            ],
        },
        "errors": sorted(report["errors"]),
    }


def _generator_choice(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "shipped": report["shipped"],
        "chosen": report["chosen"],
        "comparisons": [
            {
                "model": model,
                "cases": c["cases"],
                "factRecall": _sign_test(c["fact_recall"]),
                "faithfulness": _sign_test(c["faithfulness"]),
                "coverageGaps": _sign_test(c["coverage_gaps"]),
                "qualifies": c["qualifies"],
            }
            for model, c in report["comparisons"].items()
        ],
    }


def _sign_test(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "challengerOnly": result["challenger_only"],
        "shippedOnly": result["shipped_only"],
        "pValue": result["p_value"],
        "verdict": result["verdict"],
    }


def _generation_summary(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "cases": s["cases"],
        "citationsValid": s["citations_valid"],
        "figuresExact": s["figures_exact"],
        "coverageGapsStated": s["coverage_gaps_stated"],
        "factRecall": s["fact_recall"],
        "faithfulness": s["faithfulness"],
        "meanCostUsd": s["mean_cost_usd"],
        "totalCostUsd": s["total_cost_usd"],
        "meanLatencyS": s["mean_latency_s"],
        "maxLatencyS": s["max_latency_s"],
        "meanFirstTokenS": s["mean_first_token_s"],
        "meanInputTokens": s["mean_input_tokens"],
        "meanOutputTokens": s["mean_output_tokens"],
        "judgeCostUsd": s["judge_cost_usd"],
    }


def main(
    argv: list[str] | None = None,
    *,
    filings: Sequence[Filing] | None = None,
    today: date | None = None,
    out: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(
        description="Export the evaluation results and Corpus coverage for the front-end."
    )
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    parser.add_argument("--out", type=Path, default=DEFAULT_EXPORT)
    args = parser.parse_args(argv)

    data = export(
        args.split,
        args.eval_dir,
        load_corpus() if filings is None else filings,
        today or date.today(),
        args.golden_set,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    arms = ", ".join(arm["name"] for arm in data["retrieval"]["arms"])
    models = ", ".join(run["model"] for run in data["generation"]) or "none yet"
    choice = data["generatorChoice"]
    holdout = data["holdout"]
    print(
        f"Exported the {args.split} split's retrieval results (Arms: {arms}), generation "
        f"results (generators: {models}), "
        + (f"the generator choice ({choice['chosen']}), " if choice else "")
        + (f"{len(holdout['generation'])} holdout generation run(s), " if holdout else "")
        + f"and the coverage of {len(data['coverage']['companies'])} Companies to "
        f"{args.out.resolve()}",
        file=out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
