"""The evaluation export: the harnesses' latest results and the Corpus coverage, as one
JSON file for the front-end's "How it works" page.

It describes Golden Set version 2 by default (`--golden-set` names version 1's file,
which still exports against version 1's reports), and reads the reports the harnesses
last wrote for a split under `data/derived/eval/`:

- `retrieval-<split>.json` (`make eval-retrieval`): every Arm's scores, overall and per
  question type, and each challenger's comparison with the Shipped Arm. Required. A
  version 2 report is shown as its harness scores it: gated on Evidence Reached (ADR
  0011, one-sided), with the free screen's result and whether each Arm can ship under
  the one-call rule. A version 1 report is shown gated on hit@10, as version 1's harness
  gated it: for one written by the later harness, gated on Evidence Reached, the export
  pairs the Arms' cases on hit@10 itself.
- `generation-<split>.json` (the round's shipped run) and `generation-control-<split>.json`
  (its Control Run, ADR 0011), each optional, since a run costs money.
- `generator-choice-<split>.json` (`make eval-generators`): each challenger generator's
  sign tests against the shipped one (with the Control Run's, under version 2), and the
  generator the rule chose. Optional. The challengers' own reports, which it names, are
  the scoreboard's other generator rows; a generation report no comparison names, such
  as a settings run or a stale report of another version, is not read.
- `brief-suite.json` (`make eval-brief`): the Brief Suite's verdict per case. Optional,
  and outside the split, so it is left out of a holdout export.

Every Golden Set report the export reads must record the Golden Set version it
describes: one of another version is refused, never mixed in (a report that records no
version is version 1's).

Beside a dev (or all) export it carries the holdout's reports, `retrieval-holdout.json`
and every `generation-holdout[-<suffix>].json`, when the holdout has been scored, so the
page shows the holdout run (or runs) next to the numbers the choices were made on.

It adds the Corpus coverage grid (each Company's Filings by the calendar quarter of
their Report Periods, Tracked Companies first) and writes everything, in the
front-end's camelCase, to `frontend/data/eval-export.json`. The file is committed, so
the page shows the results without anyone rerunning the harnesses.

    python -m edgar_eval.export [--split dev|holdout|all] [--golden-set PATH]
        [--eval-dir DIR] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from edgar_eval.metrics import mcnemar_exact
from edgar_eval.selection import AHEAD_P, BEHIND_P
from edgar_rag.corpus import Filing, load_corpus, report_quarter
from edgar_rag.golden_set import DEFAULT_GOLDEN_SET, load_brief_suite, load_golden_set
from edgar_rag.paths import DERIVED_DIR, REPO_ROOT

__all__ = ["DEFAULT_EVAL_DIR", "DEFAULT_EXPORT", "coverage_grid", "export", "main"]

DEFAULT_EVAL_DIR = DERIVED_DIR / "eval"
DEFAULT_EXPORT = REPO_ROOT / "frontend" / "data" / "eval-export.json"

_COVERAGE_ORDER = ("tracked", "snapshot")
_PAGE_K = 10
"""The k the page reports recall and missed cases at when a report has no gate k, and
the hit@k it gates a version 1 report on when that report does not."""


def export(
    split: str,
    eval_dir: Path,
    filings: Sequence[Filing],
    today: date,
    golden_set: Path = DEFAULT_GOLDEN_SET,
) -> dict[str, Any]:
    """The front-end's export for a split, from the harnesses' reports in `eval_dir`,
    describing the Golden Set in `golden_set`. A report of another Golden Set version is
    refused rather than mixed with this version's."""
    retrieval_path = eval_dir / f"retrieval-{split}.json"
    if not retrieval_path.exists():
        raise SystemExit(
            f"error: no retrieval report at {retrieval_path}. Run "
            f"`make eval-retrieval SPLIT={split}` first."
        )
    golden = load_golden_set(golden_set)
    version = golden.version

    def read(path: Path) -> dict[str, Any]:
        report = _read(path)
        if report.get("golden_set_version", 1) != version:
            raise SystemExit(
                f"error: {path} scores Golden Set version "
                f"{report.get('golden_set_version', 1)}, and the export describes version "
                f"{version} ({golden_set})."
            )
        return report

    retrieval = read(retrieval_path)
    cases = golden.cases if split == "all" else golden.split(split)
    choice_path = eval_dir / f"generator-choice-{split}.json"
    choice = _read(choice_path) if choice_path.exists() else None
    brief_path = eval_dir / "brief-suite.json"
    return {
        "exportedOn": today.isoformat(),
        "split": split,
        "goldenSet": {
            "version": version,
            "cases": len(golden.cases),
            "splitCases": len(cases),
        },
        # Version 2's rules are one-sided (ADR 0011); version 1 decided at two-sided
        # p < 0.05, so its export carries none.
        "thresholds": {"aheadP": AHEAD_P, "behindP": BEHIND_P} if version >= 2 else None,
        "retrieval": _retrieval(retrieval),
        "generation": [
            _generation(path, read(path), control=path.name.startswith("generation-control-"))
            for path in _round_paths(eval_dir, split, choice)
        ],
        "generatorChoice": _generator_choice(choice) if choice else None,
        "briefSuite": (
            _brief_suite(_read(brief_path)) if split != "holdout" and brief_path.exists() else None
        ),
        "holdout": (
            None if split == "holdout" else _holdout(eval_dir, len(golden.split("holdout")), read)
        ),
        "coverage": coverage_grid(filings),
    }


def _round_paths(eval_dir: Path, split: str, choice: dict[str, Any] | None) -> list[Path]:
    """The round's generation reports: the shipped run, its Control Run, then each
    challenger the generator comparison names, those that exist."""
    paths = [eval_dir / f"generation-{split}.json", eval_dir / f"generation-control-{split}.json"]
    # The choice file records where its reports were when it ran; they are read from
    # `eval_dir` by name. Its first report is the shipped run's.
    for name in (Path(p).name for p in (choice or {}).get("reports", [])[1:]):
        if eval_dir / name not in paths:
            paths.append(eval_dir / name)
    return [p for p in paths if p.exists()]


def _holdout_paths(eval_dir: Path) -> list[Path]:
    """The holdout's generation reports: the first run's, then any others."""
    return sorted(eval_dir.glob("generation-holdout.json")) + sorted(
        eval_dir.glob("generation-holdout-*.json")
    )


def _holdout(eval_dir: Path, split_cases: int, read) -> dict[str, Any] | None:
    """The holdout's reports, or None when it has not been scored."""
    retrieval_path = eval_dir / "retrieval-holdout.json"
    generation_paths = _holdout_paths(eval_dir)
    if not retrieval_path.exists() and not generation_paths:
        return None
    return {
        "splitCases": split_cases,
        "retrieval": _retrieval(read(retrieval_path)) if retrieval_path.exists() else None,
        "generation": [_generation(path, read(path)) for path in generation_paths],
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
    """A retrieval report as its harness gated it: on Evidence Reached for version 2,
    on hit@k for version 1."""
    version_1 = report.get("golden_set_version", 1) == 1
    k = str(report.get("gate_k", _PAGE_K))
    if "gate_k" in report:
        gating, comparisons = f"hit@{k}", report["comparisons"]
    elif version_1:
        gating, comparisons = f"hit@{k}", _hit_comparisons(report)
    else:
        gating, comparisons = report["gating_metric"], report["comparisons"]
    screen = None if version_1 else report.get("screen")
    return {
        "gatingMetric": gating,
        "k": int(k),
        "ks": report["ks"],
        "scoredCases": len(report["case_ids"]),
        "unscored": report["unscored"],
        "arms": [
            {
                "name": arm["name"],
                "shipped": arm["shipped"],
                # A report from before the one-call rule records no Arm making a call.
                "shippable": arm.get("shippable", True),
                "overall": _retrieval_summary(arm["overall"]),
                "byType": [
                    {"questionType": kind} | _retrieval_summary(summary)
                    for kind, summary in sorted(arm["by_type"].items())
                ],
                "missed": [c["case_id"] for c in arm["cases"] if not c["hit"][k]],
            }
            # The Shipped Arm first, then the challengers in the harness's order.
            for arm in sorted(report["arms"].values(), key=lambda a: not a["shipped"])
        ],
        "comparisons": [
            {
                "arm": c["arm"],
                "shippedArm": c["shipped_arm"],
                "metric": c["metric"],
                "facts": c.get("facts") if not version_1 else None,
                "challengerOnly": c["result"]["challenger_only"],
                "shippedOnly": c["result"]["shipped_only"],
                "pValue": c["result"]["p_value"],
                "pAhead": None if version_1 else c["result"]["p_ahead"],
                "pBehind": None if version_1 else c["result"]["p_behind"],
                # The gate's one-sided verdict for version 2; version 1's two-sided one.
                "verdict": c["result"]["verdict"] if version_1 else c["verdict"],
            }
            for c in comparisons
        ],
        "screen": _screen(screen) if screen else None,
    }


def _screen(screen: dict[str, Any]) -> dict[str, Any]:
    return {
        "shipped": screen["shipped"],
        "limit": screen["limit"],
        "kept": screen["kept"],
        "candidates": [
            {
                "name": c["name"],
                "facts": c["facts"],
                "factsReached": c["facts_reached"],
                "gained": c["gained"],
                "lost": c["lost"],
                "pBehind": c["p_behind"],
                "kept": c["kept"],
                "shippable": c.get("shippable", True),
                "reason": c["reason"],
            }
            for c in screen["candidates"]
        ],
    }


def _hit_comparisons(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Each challenger Arm against the Shipped Arm on hit@10, case by case, as version 1's
    harness compared them: the view of a version 1 report gated on Evidence Reached."""
    gate = str(_PAGE_K)
    arms = report["arms"].values()
    shipped = next(a for a in arms if a["shipped"])
    hits = [c["hit"][gate] for c in shipped["cases"]]
    return [
        {
            "arm": arm["name"],
            "shipped_arm": shipped["name"],
            "metric": f"hit@{gate}",
            "result": vars(mcnemar_exact([c["hit"][gate] for c in arm["cases"]], hits)),
        }
        for arm in arms
        if not arm["shipped"]
    ]


def _retrieval_summary(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "cases": s["cases"],
        "hitAt": s["hit"],
        "recallAt": s["recall"],
        "hitAll": s["hit_all"],
        "recallAll": s["recall_all"],
        "mrr": s["mrr"],
        "meanSources": s["mean_sources"],
        # Evidence Reached, for a report that records it.
        "facts": s.get("facts"),
        "factsReached": s.get("facts_reached"),
        "meanSourceTokens": s.get("mean_source_tokens"),
    }


def _generation(path: Path, report: dict[str, Any], control: bool = False) -> dict[str, Any]:
    cases = report["cases"]
    return {
        "report": path.name,
        "model": report["model"],
        "judgeModel": report["judge_model"],
        "promptVersion": report["prompt_version"],
        "controlRun": control,
        "factCutoff": report.get("fact_cutoff"),
        "answersPassed": (
            sum(1 for c in cases if c["passed"]) if all("passed" in c for c in cases) else None
        ),
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
    control = report.get("control")
    return {
        "shipped": report["shipped"],
        "chosen": report["chosen"],
        "inconclusive": report.get("inconclusive", False),
        "reason": report.get("reason"),
        "control": _generator_comparison("Control Run", control) if control else None,
        "comparisons": [
            _generator_comparison(model, c) for model, c in report["comparisons"].items()
        ],
    }


def _generator_comparison(model: str, c: dict[str, Any]) -> dict[str, Any]:
    contradicted = c.get("contradicted_claims")
    return {
        "model": model,
        "cases": c["cases"],
        "factRecall": _sign_test(c["fact_recall"]),
        "faithfulness": _sign_test(c["faithfulness"]),
        "coverageGaps": _sign_test(c["coverage_gaps"]),
        # Paired on "has no Contradicted Claim"; version 1's rule had no such guardrail.
        "contradictedClaims": _sign_test(contradicted) if contradicted else None,
        "qualifies": c["qualifies"],
    }


def _sign_test(result: dict[str, Any]) -> dict[str, Any]:
    # A version 1 choice file names the wins and losses `challenger_only` and
    # `shipped_only`, and decided at two-sided p < 0.05; one written under ADR 0011's
    # rule, `wins` and `losses`, with both one-sided p-values and the bootstrap interval.
    difference = result.get("difference")
    return {
        "challengerOnly": result.get("wins", result.get("challenger_only")),
        "shippedOnly": result.get("losses", result.get("shipped_only")),
        "pValue": result["p_value"],
        "pAhead": result.get("p_ahead"),
        "pBehind": result.get("p_behind"),
        "paired": result.get("paired"),
        "leftOut": result.get("left_out"),
        "verdict": result["verdict"],
        "difference": (
            {
                "mean": difference["mean"],
                "low": difference["low"],
                "high": difference["high"],
                "confidence": difference["confidence"],
            }
            if difference
            else None
        ),
    }


def _brief_suite(report: dict[str, Any]) -> dict[str, Any]:
    """The Brief Suite's verdict per case, never averaged: for each, its must-state facts,
    the ones it missed (stated in fewer runs than a pass needs) with whether their
    evidence reached the Answer Context, and its runs with a Contradicted Claim."""
    # The brief's own questions are the Brief Suite cases that replace a version 1 case.
    brief_questions = {c.id for c in load_brief_suite().cases if c.replaces is not None}
    return {
        "model": report["model"],
        "judgeModel": report["judge_model"],
        "promptVersion": report["prompt_version"],
        "settings": report.get("settings"),
        "runs": report["runs"],
        "passRuns": report["pass_runs"],
        "casesPassed": report["cases_passed"],
        "cases": [
            {
                "caseId": case["case_id"],
                "question": case["question"],
                "briefQuestion": case["case_id"] in brief_questions,
                "passed": case["passed"],
                "mustState": sum(1 for f in case["facts"] if f["tier"] == "must_state"),
                "missed": [
                    {
                        "fact": f["fact"],
                        "statedRuns": f["stated_runs"],
                        "evidenceReachedRuns": f["evidence_reached_runs"],
                    }
                    for f in case["facts"]
                    if f["tier"] == "must_state" and not f["passed"]
                ],
                "contradictedRuns": [c["run"] for c in case["contradicted"]],
                "truncatedRuns": case["truncated_runs"],
                "failedRuns": sorted(
                    {e["run"] for e in case["errors"]}
                    | {f["run"] for f in case["judgment_failures"]}
                ),
            }
            for case in report["cases"]
        ],
    }


def _generation_summary(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "cases": s["cases"],
        "citationsValid": s["citations_valid"],
        "figuresExact": s["figures_exact"],
        "coverageGapsStated": s["coverage_gaps_stated"],
        "structureFollowed": s.get("structure_followed"),
        "meanWords": s.get("mean_words"),
        "factRecall": s["fact_recall"],
        # Version 2's: detail recall beside must-state Fact Recall, the answers with a
        # Contradicted Claim, those cut off at the token cap and the failed judgments.
        "detailRecall": s.get("detail_recall"),
        "faithfulness": s["faithfulness"],
        "answersContradicted": s.get("answers_contradicted"),
        "truncated": s.get("truncated"),
        "judgmentsFailed": s.get("judgments_failed"),
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
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=DEFAULT_GOLDEN_SET,
        help="the Golden Set the export describes (default: version 2; name "
        "data/eval/golden_set.json, with version 1's reports, for 1)",
    )
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
    brief = data["briefSuite"]
    holdout = data["holdout"]
    print(
        f"Exported Golden Set version {data['goldenSet']['version']}'s {args.split} split: "
        f"retrieval results (Arms: {arms}), generation results (runs: {models}), "
        + (f"the generator choice ({choice['chosen']}), " if choice else "")
        + (
            f"the Brief Suite ({brief['casesPassed']} of {len(brief['cases'])} cases pass), "
            if brief
            else ""
        )
        + (f"{len(holdout['generation'])} holdout generation run(s), " if holdout else "")
        + f"and the coverage of {len(data['coverage']['companies'])} Companies to "
        f"{args.out.resolve()}",
        file=out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
