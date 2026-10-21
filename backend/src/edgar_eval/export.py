"""The evaluation export: the harnesses' latest results and each Company's Company
Calendar, as one JSON file for the front-end's "How it works" page and Calendar tab.

Its results are the latest only (the page's Technical details show no history, which
`docs/evaluation.md` keeps). It describes Golden Set version 2 by default
(`--golden-set` names version 1's file, which still exports against version 1's
reports), and reads the reports the harnesses last wrote for a split under
`data/derived/eval/`:

- `retrieval-<split>.json` (`make eval-retrieval`): every Arm's scores, overall and per
  question type, and each challenger's comparison with the Shipped Arm. Required. A
  version 2 report is shown as its harness scores it: gated on Evidence Reached (ADR
  0011, one-sided), with the free screen's result and whether each Arm can ship under
  the one-call rule. A version 1 report is shown gated on hit@10, as version 1's harness
  gated it: for one written by the later harness, gated on Evidence Reached, the export
  pairs the Arms' cases on hit@10 itself.
- `generation-<split>.json`, the latest round's shipped run, optional since a run costs
  money. The round is the code, prompt and Golden Set version it records
  (`generation.current_round`, ADR 0011): the rest of the scoreboard is read only when
  it belongs to the same round.
- `generation-control-<split>.json`, the round's Control Run, when it records the shipped
  run's round.
- `generator-choice-<split>.json` (`make eval-generators`): each challenger generator's
  sign tests against the shipped one (with the Control Run's, under version 2), and the
  generator the rule chose, when every report it names is in the shipped run's round.
  The challengers' own reports are the scoreboard's other generator rows; a generation
  report no comparison of the round names is not read.

The Brief Suite, the Arm and settings comparisons and any comparison of an earlier round
are not exported: they stay in their reports and `docs/evaluation.md`.

Every Golden Set report the export reads must record the Golden Set version it
describes: one of another version is refused, never mixed in (a report that records no
version is version 1's).

Beside a dev (or all) export it carries the holdout's latest run, when the holdout has
been scored: `retrieval-holdout.json` and one generation report, the latest. A later
holdout run is kept as `generation-holdout-<suffix>.json` beside the first run's
`generation-holdout.json`, so the latest is the suffixed report written last, else
`generation-holdout.json`.

It adds each Company's Company Calendar (its common names from the Query Scope parser's
alias table, so "What's covered" is searched by the names questions are matched by, its
fiscal year end, and every fiscal quarter and year from its first Filing to its latest
with their calendar months, their Filing and, for a Tracked Company, their revenue
Financial Fact, fourth quarters derived and marked as derived), which the workspace's
Calendar tab and "What's covered" show, and the curated list of notable Companies
missing from the Corpus, which its search names. It writes everything, in the
front-end's camelCase, to `frontend/data/eval-export.json`. The file is committed, so
the page shows the results without anyone rerunning the harnesses.

    python -m edgar_eval.export [--split dev|holdout|all] [--golden-set PATH]
        [--eval-dir DIR] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any, TextIO

from edgar_eval.metrics import mcnemar_exact
from edgar_eval.selection import AHEAD_P, BEHIND_P
from edgar_rag.corpus import MONTH_NAMES, Filing, load_corpus, month_span
from edgar_rag.financial_facts import extract_financial_facts
from edgar_rag.golden_set import DEFAULT_GOLDEN_SET, load_golden_set
from edgar_rag.paths import DERIVED_DIR, REPO_ROOT
from edgar_rag.retrieval import common_names, load_missing_companies

__all__ = [
    "DEFAULT_EVAL_DIR",
    "DEFAULT_EXPORT",
    "company_calendars",
    "export",
    "main",
]

DEFAULT_EVAL_DIR = DERIVED_DIR / "eval"
DEFAULT_EXPORT = REPO_ROOT / "frontend" / "data" / "eval-export.json"

_ROUND = ("code_version", "prompt_version", "golden_set_version")
"""What a Golden Set report records of its round (`generation.current_round`)."""
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
    generation, choice = _round(eval_dir, split, read)
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
        "generation": generation,
        "generatorChoice": _generator_choice(choice) if choice else None,
        "holdout": (
            None if split == "holdout" else _holdout(eval_dir, len(golden.split("holdout")), read)
        ),
        "companies": company_calendars(filings),
        "missingCompanies": [
            {"name": m.name, "ticker": m.ticker, "aliases": list(m.aliases), "sector": m.sector}
            for m in load_missing_companies()
        ],
    }


def _round(eval_dir: Path, split: str, read) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The latest round's generation runs and its generator comparison: the shipped run,
    its Control Run and each challenger the comparison names, those that exist and record
    the shipped run's round; the comparison only when every report it names does."""
    shipped_path = eval_dir / f"generation-{split}.json"
    if not shipped_path.exists():
        return [], None
    shipped = read(shipped_path)
    reports = {shipped_path: shipped}

    def in_round(path: Path) -> bool:
        if path not in reports:
            if not path.exists():
                return False
            reports[path] = read(path)
        return all(reports[path].get(k) == shipped.get(k) for k in _ROUND)

    paths = [shipped_path]
    control_path = eval_dir / f"generation-control-{split}.json"
    if in_round(control_path):
        paths.append(control_path)
    choice_path = eval_dir / f"generator-choice-{split}.json"
    choice = _read(choice_path) if choice_path.exists() else None
    if choice:
        # The choice file records where its reports were when it ran; they are read from
        # `eval_dir` by name. Its first report is the shipped run's.
        named = [eval_dir / Path(p).name for p in choice.get("reports", [])]
        if choice.get("control_report"):
            named.append(eval_dir / Path(choice["control_report"]).name)
        if all(in_round(p) for p in named):
            paths += [p for p in named if p not in paths]
        else:
            choice = None
    return [
        _generation(p, reports[p], control=p.name.startswith("generation-control-")) for p in paths
    ], choice


def _latest_holdout(eval_dir: Path) -> Path | None:
    """The holdout's latest generation report: the suffixed one written last, else the
    first run's `generation-holdout.json`."""
    later = sorted(
        eval_dir.glob("generation-holdout-*.json"), key=lambda p: (p.stat().st_mtime, p.name)
    )
    first = eval_dir / "generation-holdout.json"
    return later[-1] if later else first if first.exists() else None


def _holdout(eval_dir: Path, split_cases: int, read) -> dict[str, Any] | None:
    """The holdout's latest run, or None when it has not been scored."""
    retrieval_path = eval_dir / "retrieval-holdout.json"
    generation_path = _latest_holdout(eval_dir)
    if not retrieval_path.exists() and generation_path is None:
        return None
    return {
        "splitCases": split_cases,
        "retrieval": _retrieval(read(retrieval_path)) if retrieval_path.exists() else None,
        "generation": (
            _generation(generation_path, read(generation_path)) if generation_path else None
        ),
    }


_FISCAL_PERIOD = re.compile(r"^(?:Q([1-4]) )?FY(\d{4})$")


def company_calendars(filings: Iterable[Filing]) -> list[dict[str, Any]]:
    """Each Company's Company Calendar, by ticker: its common names (the names besides
    its Filings' one that a question names it by, `common_names`), its fiscal year end and
    every fiscal quarter from its first Filing's to its latest's, newest first, each
    fiscal year's row just before its fourth quarter's (they end together).

    Each period carries its calendar months ("Aug–Oct 2025") and the calendar year it ends
    in, the Filing that reports it (a fourth quarter's is the 10-K that ends it), or None
    where the Corpus has none, and, for a Tracked Company, its revenue Financial Fact. A
    fourth quarter's revenue is derived as the 10-K's year less its three 10-Q quarters,
    when all three are in the Corpus, and marked as derived. A Snapshot Company has no
    revenue (ADR 0001: its Financial Facts are not extracted)."""
    by_ticker: dict[str, list[Filing]] = {}
    for filing in filings:
        by_ticker.setdefault(filing.ticker, []).append(filing)
    return [_calendar(by_ticker[ticker]) for ticker in sorted(by_ticker)]


def _calendar(filings: list[Filing]) -> dict[str, Any]:
    first = filings[0]
    end_month = first.fiscal_year_end_month
    tracked = first.coverage == "tracked"
    # Each Filing by its fiscal quarter, counted as year * 4 + quarter - 1 (a 10-K's is
    # its fiscal year's fourth quarter).
    by_quarter: dict[int, Filing] = {}
    for filing in filings:
        m = _FISCAL_PERIOD.match(filing.fiscal_period or "")
        if m:
            by_quarter[int(m.group(2)) * 4 + int(m.group(1) or 4) - 1] = filing
    revenue = {
        f.filing_id: fact
        for f in (filings if tracked else ())
        for fact in extract_financial_facts(f)
        if fact.metric == "revenue" and fact.segment is None
    }

    def reported(filing: Filing | None, months: int) -> dict[str, Any] | None:
        fact = revenue.get(filing.filing_id) if filing else None
        if fact is None or fact.period_months != months:
            return None
        return {
            "value": fact.value,
            "filingId": fact.filing_id,
            "label": fact.label,
            "derived": None,
        }

    periods: list[dict[str, Any]] = []
    for index in range(max(by_quarter, default=-1), min(by_quarter, default=0) - 1, -1):
        year, quarter = divmod(index, 4)
        quarter += 1
        filing = by_quarter.get(index)
        if quarter < 4:
            periods.append(
                _period(
                    f"Q{quarter} FY{year}", year, quarter, end_month, filing, reported(filing, 3)
                )
            )
            continue
        annual = filing if filing and filing.form_type == "10-K" else None
        year_revenue = reported(annual, 12)
        parts = [reported(by_quarter.get(year * 4 + q), 3) for q in range(3)]
        fourth = None
        if year_revenue and all(parts):
            fourth = {
                "value": year_revenue["value"] - sum(p["value"] for p in parts if p),
                "filingId": year_revenue["filingId"],
                "label": None,
                "derived": f"FY{year} less Q1–Q3 FY{year}",
            }
        periods.append(_period(f"FY{year}", year, None, end_month, annual, year_revenue))
        periods.append(_period(f"Q4 FY{year}", year, 4, end_month, annual, fourth))
    return {
        "ticker": first.ticker,
        "company": first.company,
        "commonNames": list(common_names(first.ticker, first.company)),
        "sector": first.sector,
        "coverage": first.coverage,
        "fiscalYearEnd": _fiscal_year_end(filings),
        "periods": periods,
    }


def _period(
    fiscal_period: str,
    fiscal_year: int,
    quarter: int | None,
    end_month: int | None,
    filing: Filing | None,
    revenue: dict[str, Any] | None,
) -> dict[str, Any]:
    """One row of a Company Calendar: a fiscal quarter, or (`quarter` None) a fiscal year."""
    # Fiscal year Y ends in month `end_month` of calendar year Y; each quarter before the
    # fourth ends three months earlier than the next.
    end_year, end_month_index = divmod(
        fiscal_year * 12 + (end_month or 12) - 1 - 3 * (4 - (quarter or 4)), 12
    )
    return {
        "fiscalPeriod": fiscal_period,
        "kind": "quarter" if quarter else "year",
        "months": month_span(end_year, end_month_index + 1, 3 if quarter else 12),
        "calendarYear": end_year,
        "filing": (
            {
                "filingId": filing.filing_id,
                "formType": filing.form_type,
                "reportPeriod": filing.report_period.isoformat(),
            }
            if filing
            else None
        ),
        "revenue": revenue,
    }


def _fiscal_year_end(filings: list[Filing]) -> str | None:
    """When the Company's fiscal year ends, as its 10-Ks date it: "December 31" when each
    ends on the same last day of a month, else "late January" for a 52/53-week year, or
    "late January or early February" when one ends in the first days of the next month
    (which stand for the end of the month before)."""
    month = filings[0].fiscal_year_end_month
    ends = [f.report_period for f in filings if f.form_type == "10-K"]
    if month is None or not ends:
        return None
    name = MONTH_NAMES[month - 1]
    if all((d + timedelta(days=1)).day == 1 for d in ends) and len({d.day for d in ends}) == 1:
        return f"{name} {ends[0].day}"
    if any(d.month != month for d in ends):
        return f"late {name} or early {MONTH_NAMES[month % 12]}"
    return f"late {name}"


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
    return {"model": model} | _scores(c)


def _difference(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return None
    return {"mean": d["mean"], "low": d["low"], "high": d["high"], "confidence": d["confidence"]}


def _scores(c: dict[str, Any]) -> dict[str, Any]:
    """A comparison's per-case sign tests and whether the challenger qualifies."""
    contradicted = c.get("contradicted_claims")
    return {
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
    return {
        "challengerOnly": result.get("wins", result.get("challenger_only")),
        "shippedOnly": result.get("losses", result.get("shipped_only")),
        "pValue": result["p_value"],
        "pAhead": result.get("p_ahead"),
        "pBehind": result.get("p_behind"),
        "paired": result.get("paired"),
        "leftOut": result.get("left_out"),
        "verdict": result["verdict"],
        "difference": _difference(result.get("difference")),
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
        description="Export the latest evaluation results and the Company Calendars for the "
        "front-end."
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
    holdout = data["holdout"]
    print(
        f"Exported Golden Set version {data['goldenSet']['version']}'s {args.split} split: "
        f"retrieval results (Arms: {arms}), the latest round's generation results (runs: "
        f"{models}), "
        + (f"the generator choice ({choice['chosen']}), " if choice else "")
        + (
            f"the latest holdout run ({holdout['generation']['report']}), "
            if holdout and holdout["generation"]
            else ""
        )
        + f"and the Company Calendars of {len(data['companies'])} Companies to "
        f"{args.out.resolve()}",
        file=out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
