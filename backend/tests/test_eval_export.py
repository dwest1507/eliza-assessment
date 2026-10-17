"""The evaluation export: the harnesses' latest reports and the Corpus coverage, written
as one JSON file for the front-end's "How it works" page.

The reports are written by the harnesses' own command lines (with fake Arms, a fake
answer model and a fake judge), so the export is tested against the JSON they really
write.
"""

import io
import json
import re
from datetime import date

import pytest

from edgar_eval import generation, retrieval
from edgar_eval.export import coverage_grid, main
from edgar_eval.judge import JEV_MODEL
from edgar_eval.retrieval import Arm
from edgar_rag.golden_set import load_golden_set

TODAY = date(2026, 10, 16)


def _first_expected(messages, index, **settings):
    """A fake Arm that finds each case's first expected pair, by its question."""
    cases = {c.question: c for c in load_golden_set().cases}
    case = cases[messages[-1].content]
    return [(s.filing_id, s.section) for s in case.expected_sources[:1]]


def _write_retrieval_report(eval_dir, split="dev"):
    arms = [
        Arm("fts5", "shipped", _first_expected, shipped=True),
        Arm("nothing", "finds nothing", lambda messages, index, **settings: []),
    ]
    path = eval_dir / f"retrieval-{split}.json"
    assert (
        retrieval.main(
            ["--split", split, "--index", str(eval_dir / "no-index.sqlite"), "--json", str(path)],
            arms=arms,
            out=io.StringIO(),
        )
        == 0
    )


class FakeModel:
    """An answer model that writes a fixed answer and reports fixed usage."""

    def __init__(self, model, answer):
        self.model = model
        self.answer = answer

    def stream(self, messages):
        from edgar_rag.answer_model import Usage

        yield from re.findall(r"\S+\s*|\s+", self.answer)
        yield Usage(input_tokens=20_000, output_tokens=1_000)


class FakeJudge:
    """Says every Required Fact is stated and every claim supported."""

    def judge(self, answer, required_facts, claims, sources):
        from edgar_eval.judge import ClaimJudgment, FactJudgment, Judgments

        return Judgments(
            facts=tuple(FactJudgment(f, 1.0) for f in required_facts),
            claims=tuple(ClaimJudgment(c.text, c.tags, "supported", {}) for c in claims),
            model=JEV_MODEL,
            requests=2,
            input_tokens=5_000,
        )


# Cites a Source the turn does not have, so the citation check fails.
ANSWER = "Apple relies on outsourcing partners in Asia [S1]. Tesla depends on its CEO [S99]."


def _write_generation_report(eval_dir, index, tmp_path, model, suffix=""):
    path = eval_dir / f"generation-dev{suffix}.json"
    code = generation.main(
        ["--case", "risk-aapl-tsla-jpm", "--index", str(index), "--log", str(tmp_path / "log")]
        + ["--json", str(path)],
        model=FakeModel(model, ANSWER),
        judge=FakeJudge(),
        fact_values=lambda tickers: [],
        out=io.StringIO(),
    )
    assert code == 0


def _export(tmp_path, eval_dir, filings, *args):
    out_path = tmp_path / "eval-export.json"
    code = main(
        ["--eval-dir", str(eval_dir), "--out", str(out_path), *args],
        filings=filings,
        today=TODAY,
        out=io.StringIO(),
    )
    assert code == 0
    return json.loads(out_path.read_text())


@pytest.fixture
def eval_dir(tmp_path):
    path = tmp_path / "eval"
    path.mkdir()
    return path


def test_the_export_carries_each_arms_scores_and_its_comparison_with_the_shipped_arm(
    tmp_path, eval_dir, indexed_filings
):
    _write_retrieval_report(eval_dir)

    data = _export(tmp_path, eval_dir, indexed_filings)

    golden = load_golden_set()
    assert data["exportedOn"] == "2026-10-16"
    assert data["split"] == "dev"
    assert data["goldenSet"] == {
        "version": golden.version,
        "cases": len(golden.cases),
        "splitCases": len(golden.split("dev")),
    }
    results = data["retrieval"]
    assert results["gatingMetric"] == "hit@10"
    assert results["ks"] == [5, 10, 20]
    assert results["scoredCases"] + len(results["unscored"]) == len(golden.split("dev"))
    shipped, nothing = results["arms"]
    assert (shipped["name"], shipped["shipped"]) == ("fts5", True)
    assert shipped["overall"]["mrr"] == 1
    assert shipped["overall"]["hitAt"]["10"] == 1
    assert shipped["overall"]["cases"] == results["scoredCases"]
    assert shipped["missed"] == []
    types = {c.question_type for c in golden.split("dev") if c.expected_sources}
    assert {row["questionType"] for row in shipped["byType"]} == types
    assert nothing["overall"]["hitAll"] == 0
    assert len(nothing["missed"]) == results["scoredCases"]
    [comparison] = results["comparisons"]
    assert comparison["arm"] == "nothing" and comparison["shippedArm"] == "fts5"
    assert comparison["verdict"] == "behind"
    assert comparison["shippedOnly"] == results["scoredCases"]
    assert 0 <= comparison["pValue"] < 0.05


def test_the_export_carries_every_generators_scores_with_cost_and_latency(
    tmp_path, eval_dir, index, indexed_filings
):
    _write_retrieval_report(eval_dir)
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna")
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6.1-sol", "-gpt-6.1-sol")

    data = _export(tmp_path, eval_dir, indexed_filings)

    runs = {run["model"]: run for run in data["generation"]}
    assert set(runs) == {"gpt-6-luna", "gpt-6.1-sol"}
    luna = runs["gpt-6-luna"]
    assert luna["judgeModel"] == JEV_MODEL
    assert luna["promptVersion"]
    overall = luna["overall"]
    assert overall["cases"] == 1
    assert overall["citationsValid"] == 0  # cites [S99]
    assert overall["faithfulness"] == 1
    assert overall["meanCostUsd"] == pytest.approx(0.0025)
    assert overall["meanLatencyS"] >= 0
    assert [row["questionType"] for row in luna["byType"]] == ["risk"]
    assert luna["failing"]["citations"] == ["risk-aapl-tsla-jpm"]
    assert luna["errors"] == []
    assert runs["gpt-6.1-sol"]["overall"]["meanCostUsd"] == pytest.approx(0.05)


def test_generation_is_left_empty_until_its_harness_has_run(tmp_path, eval_dir, indexed_filings):
    _write_retrieval_report(eval_dir)

    data = _export(tmp_path, eval_dir, indexed_filings)

    assert data["generation"] == []


def test_the_export_reads_the_chosen_splits_reports(tmp_path, eval_dir, indexed_filings):
    _write_retrieval_report(eval_dir, split="holdout")

    data = _export(tmp_path, eval_dir, indexed_filings, "--split", "holdout")

    assert data["split"] == "holdout"
    assert data["retrieval"]["scoredCases"] + len(data["retrieval"]["unscored"]) == len(
        load_golden_set().split("holdout")
    )


def test_a_missing_retrieval_report_names_the_command_that_writes_it(tmp_path, eval_dir):
    with pytest.raises(SystemExit, match="make eval-retrieval"):
        main(
            ["--eval-dir", str(eval_dir), "--out", str(tmp_path / "x.json")],
            filings=[],
            today=TODAY,
            out=io.StringIO(),
        )


# --- The Corpus coverage grid -------------------------------------------------------------


def test_the_coverage_grid_places_each_filing_under_its_report_periods_quarter(indexed_filings):
    grid = coverage_grid(indexed_filings)

    companies = {c["ticker"]: c for c in grid["companies"]}
    assert set(companies) == {f.ticker for f in indexed_filings}
    assert companies["AAPL"]["coverage"] == "tracked"
    assert companies["JPM"]["coverage"] == "snapshot"
    assert companies["AAPL"]["sector"] == "Information Technology"
    # Apple's fiscal year ends on the last Saturday of September.
    assert {
        "period": "2025Q3",
        "filingId": "AAPL_10-K_2025-09-27",
        "formType": "10-K",
        "reportPeriod": "2025-09-27",
        "fiscalPeriod": "FY2025",
    } in companies["AAPL"]["filings"]
    # Every Filing appears once, under a period the grid has a column for.
    cells = [f for c in grid["companies"] for f in c["filings"]]
    assert sorted(f["filingId"] for f in cells) == sorted(f.filing_id for f in indexed_filings)
    assert {f["period"] for f in cells} == set(grid["periods"])
    assert grid["periods"] == sorted(grid["periods"])


def test_the_coverage_grid_lists_tracked_companies_before_snapshot_companies(indexed_filings):
    grid = coverage_grid(indexed_filings)

    classes = [c["coverage"] for c in grid["companies"]]
    assert classes == sorted(classes, key=["tracked", "snapshot"].index)
    assert "snapshot" in classes and "tracked" in classes
