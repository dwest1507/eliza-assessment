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
from types import SimpleNamespace

import pytest

from edgar_eval import generation, retrieval, selection
from edgar_eval.export import coverage_grid, main
from edgar_eval.judge import JEV_MODEL
from edgar_eval.retrieval import Arm
from edgar_rag.golden_set import GOLDEN_SET_V1, GOLDEN_SET_V2, load_golden_set
from edgar_rag.retrieval import SearchedPlace

TODAY = date(2026, 10, 16)
V1 = ("--golden-set", str(GOLDEN_SET_V1))
"""The export's arguments for Golden Set version 1, which it still describes when named."""


def _version_1():
    return load_golden_set(GOLDEN_SET_V1)


def _version_2():
    """The Golden Set the export describes by default."""
    return load_golden_set(GOLDEN_SET_V2)


def _case_by_question(question):
    # Version 1's labels win where a rewritten version 2 case asks the same question.
    cases = {
        c.question: c for p in (GOLDEN_SET_V2, GOLDEN_SET_V1) for c in load_golden_set(p).cases
    }
    return cases[question]


def _first_expected(messages, index, **settings):
    """A fake Arm that finds each case's first expected pair, by its question."""
    case = _case_by_question(messages[-1].content)
    return [(s.filing_id, s.section) for s in case.expected_sources[:1]]


def _every_fact_reached(messages, index, **settings):
    """The Answer Context of `_first_expected`: one Source holding every evidence quote."""
    case = _case_by_question(messages[-1].content)
    text = " ".join(f.evidence for f in case.required_facts)
    return _context(
        *(
            SimpleNamespace(
                kind="text",
                ticker=s.filing_id.split("_")[0],
                filing_id=s.filing_id,
                section=s.section,
                text=text,
            )
            for s in case.expected_sources[:1]
        )
    )


def _nothing_reached(messages, index, **settings):
    return _context()


def _context(*sources):
    """A fake Answer Context of these Sources, searched in each one's Section."""
    searched = tuple(SearchedPlace(s.ticker, s.filing_id, s.section) for s in sources)
    return SimpleNamespace(sources=sources, query_scope=SimpleNamespace(searched=searched))


def _write_retrieval_report(eval_dir, split="dev", golden_set=GOLDEN_SET_V2, evidence=True):
    """The retrieval harness's report: the Shipped Arm finds every case's first expected
    Source, holding all its evidence; `nothing` finds nothing; `hosted` finds the same
    as the Shipped Arm but makes an API call at query time. Without `evidence` the Arms
    prepare no Answer Context, so nothing is gated on Evidence Reached."""
    prepare = {"prepare": _every_fact_reached} if evidence else {}
    arms = [
        Arm("fts5", "shipped", _first_expected, shipped=True, **prepare),
        Arm(
            "nothing",
            "finds nothing",
            lambda messages, index, **settings: [],
            **({"prepare": _nothing_reached} if evidence else {}),
        ),
        Arm("hosted", "calls an API", _first_expected, query_api_call=True, **prepare),
    ]
    path = eval_dir / f"retrieval-{split}.json"
    assert (
        retrieval.main(
            [
                *("--split", split, "--golden-set", str(golden_set)),
                *("--index", str(eval_dir / "no-index.sqlite"), "--json", str(path)),
            ],
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


CASES = {
    (1, "dev"): "risk-aapl-tsla-jpm",
    (1, "holdout"): "risk-aapl-legal-proceedings",
    (2, "dev"): "risk-aapl-legal-proceedings",
    (2, "holdout"): "trend-tsla-energy-two-years",
}
"""The case a fake generation run answers, per Golden Set version and split."""


def _write_generation_report(
    eval_dir,
    index,
    tmp_path,
    model,
    suffix="",
    split="dev",
    answer=ANSWER,
    golden_set=GOLDEN_SET_V2,
    name=None,
):
    path = eval_dir / (name or f"generation-{split}{suffix}.json")
    version = load_golden_set(golden_set).version
    code = generation.main(
        [
            *("--golden-set", str(golden_set), "--split", split),
            "--case",
            CASES[version, split],
            "--index",
            str(index),
            "--log",
            str(tmp_path / "log"),
        ]
        + ["--json", str(path)],
        model=FakeModel(model, answer),
        judge=FakeJudge(),
        fact_values=lambda tickers: [],
        out=io.StringIO(),
    )
    assert code == 0
    return path


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


def test_the_export_describes_golden_set_version_2_by_default(tmp_path, eval_dir, indexed_filings):
    _write_retrieval_report(eval_dir)

    data = _export(tmp_path, eval_dir, indexed_filings)

    golden = _version_2()
    assert data["exportedOn"] == "2026-10-16"
    assert data["split"] == "dev"
    assert data["goldenSet"] == {
        "version": 2,
        "cases": len(golden.cases),
        "splitCases": len(golden.split("dev")),
    }
    # Version 2's verdicts are directional: one-sided, at thresholds fixed before running.
    assert data["thresholds"] == {"aheadP": 0.10, "behindP": 0.20}


def test_version_2_retrieval_is_gated_on_evidence_reached_with_the_screen_and_shippability(
    tmp_path, eval_dir, indexed_filings
):
    _write_retrieval_report(eval_dir)

    results = _export(tmp_path, eval_dir, indexed_filings)["retrieval"]

    golden = _version_2()
    assert results["gatingMetric"] == "evidence reached"
    assert results["k"] == 10
    assert results["scoredCases"] + len(results["unscored"]) == len(golden.split("dev"))
    shipped, nothing, hosted = results["arms"]
    assert (shipped["name"], shipped["shipped"], shipped["shippable"]) == ("fts5", True, True)
    assert (hosted["name"], hosted["shippable"]) == ("hosted", False)
    facts = sum(len(c.required_facts) for c in golden.split("dev") if c.expected_sources)
    assert shipped["overall"]["facts"] == facts
    reached = shipped["overall"]["factsReached"]
    assert 0 < reached <= facts
    assert nothing["overall"]["factsReached"] == 0
    # hit@k, recall@k and MRR stay reported.
    assert shipped["overall"]["hitAt"]["10"] == 1 and shipped["overall"]["mrr"] == 1
    assert len(nothing["missed"]) == results["scoredCases"]

    gates = {c["arm"]: c for c in results["comparisons"]}
    assert gates["nothing"]["metric"] == "evidence reached"
    assert gates["nothing"]["facts"] == facts
    assert gates["nothing"]["shippedOnly"] == reached
    assert gates["nothing"]["verdict"] == "behind"
    assert gates["nothing"]["pBehind"] < 0.20 and gates["nothing"]["pAhead"] > 0.10
    assert gates["hosted"]["verdict"] == "indistinguishable"

    screen = results["screen"]
    assert (screen["shipped"], screen["limit"], screen["kept"]) == ("fts5", 3, [])
    by_name = {c["name"]: c for c in screen["candidates"]}
    assert by_name["nothing"]["kept"] is False
    assert by_name["nothing"]["reason"].startswith("dropped: behind on Evidence Reached")
    assert by_name["hosted"]["shippable"] is False
    assert "API call at query time" in by_name["hosted"]["reason"]
    assert by_name["hosted"]["factsReached"] == reached


def test_a_version_1_retrieval_report_still_exports_gated_on_hit_at_10(
    tmp_path, eval_dir, indexed_filings
):
    _write_retrieval_report(eval_dir, golden_set=GOLDEN_SET_V1, evidence=False)

    data = _export(tmp_path, eval_dir, indexed_filings, *V1)

    golden = _version_1()
    assert data["goldenSet"] == {
        "version": 1,
        "cases": len(golden.cases),
        "splitCases": len(golden.split("dev")),
    }
    assert data["thresholds"] is None  # version 1 decided at two-sided p < 0.05
    results = data["retrieval"]
    assert results["gatingMetric"] == "hit@10"
    assert results["ks"] == [5, 10, 20]
    assert results["scoredCases"] + len(results["unscored"]) == len(golden.split("dev"))
    assert results["screen"] is None
    shipped, nothing, _ = results["arms"]
    assert (shipped["name"], shipped["shipped"]) == ("fts5", True)
    assert shipped["overall"]["mrr"] == 1
    assert shipped["overall"]["hitAt"]["10"] == 1
    assert shipped["overall"]["cases"] == results["scoredCases"]
    assert shipped["missed"] == []
    types = {c.question_type for c in golden.split("dev") if c.expected_sources}
    assert {row["questionType"] for row in shipped["byType"]} == types
    assert nothing["overall"]["hitAll"] == 0
    assert len(nothing["missed"]) == results["scoredCases"]
    comparison = results["comparisons"][0]
    assert comparison["arm"] == "nothing" and comparison["shippedArm"] == "fts5"
    assert comparison["metric"] == "hit@10"  # paired case by case on hit@10, as version 1
    assert comparison["verdict"] == "behind"
    assert comparison["shippedOnly"] == results["scoredCases"]
    assert 0 <= comparison["pValue"] < 0.05
    assert comparison["pAhead"] is None and comparison["facts"] is None


def test_a_version_1_report_gated_on_evidence_reached_is_paired_on_hit_at_10(
    tmp_path, eval_dir, indexed_filings
):
    _write_retrieval_report(eval_dir, golden_set=GOLDEN_SET_V1)

    results = _export(tmp_path, eval_dir, indexed_filings, *V1)["retrieval"]

    assert results["gatingMetric"] == "hit@10"
    assert results["screen"] is None
    gates = {c["arm"]: c for c in results["comparisons"]}
    assert gates["nothing"]["metric"] == "hit@10"
    assert gates["nothing"]["shippedOnly"] == results["scoredCases"]


def test_the_export_carries_the_shipped_run_and_its_control_run(
    tmp_path, eval_dir, index, indexed_filings
):
    _write_retrieval_report(eval_dir)
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna")
    _write_generation_report(
        eval_dir, index, tmp_path, "gpt-6-luna", name="generation-control-dev.json"
    )

    data = _export(tmp_path, eval_dir, indexed_filings)

    shipped, control = data["generation"]
    assert (shipped["report"], shipped["controlRun"]) == ("generation-dev.json", False)
    assert (control["report"], control["controlRun"]) == ("generation-control-dev.json", True)
    assert shipped["model"] == "gpt-6-luna"
    assert shipped["judgeModel"] == JEV_MODEL
    assert shipped["promptVersion"]
    assert shipped["factCutoff"] is not None
    overall = shipped["overall"]
    assert overall["cases"] == 1
    assert overall["citationsValid"] == 0  # cites [S99]
    assert overall["faithfulness"] == 1
    assert overall["answersContradicted"] == 0
    assert overall["truncated"] == 0
    assert overall["detailRecall"] is not None or overall["factRecall"] is not None
    assert overall["meanCostUsd"] == pytest.approx(0.0025)
    assert overall["meanLatencyS"] >= 0
    assert [row["questionType"] for row in shipped["byType"]] == ["risk"]
    assert shipped["failing"]["citations"] == [CASES[2, "dev"]]
    assert shipped["answersPassed"] == 0  # the citation check fails
    assert shipped["errors"] == []


def test_generation_is_left_empty_until_its_harness_has_run(tmp_path, eval_dir, indexed_filings):
    _write_retrieval_report(eval_dir)

    data = _export(tmp_path, eval_dir, indexed_filings)

    assert data["generation"] == []
    assert data["generatorChoice"] is None
    assert data["briefSuite"] is None
    assert data["holdout"] is None


def test_the_export_carries_the_generator_comparison_with_its_control_run_and_intervals(
    tmp_path, eval_dir, index, indexed_filings
):
    _write_retrieval_report(eval_dir)
    shipped = _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna")
    control = _write_generation_report(
        eval_dir, index, tmp_path, "gpt-6-luna", name="generation-control-dev.json"
    )
    challenger = _write_generation_report(
        eval_dir, index, tmp_path, "claude-haiku-5-5", "-claude-haiku-5-5"
    )
    # A report no comparison names (here a stale one of version 1) is not read.
    _write_generation_report(
        eval_dir, index, tmp_path, "gpt-6.1-sol", "-gpt-6.1-sol", golden_set=GOLDEN_SET_V1
    )
    assert (
        selection.main(
            ["compare", str(shipped), str(challenger), "--rule", "generators"]
            + ["--control", str(control)]
            + ["--json", str(eval_dir / "generator-choice-dev.json")],
            out=io.StringIO(),
        )
        == 0
    )

    data = _export(tmp_path, eval_dir, indexed_filings)

    assert [run["model"] for run in data["generation"]] == [
        "gpt-6-luna",
        "gpt-6-luna",
        "claude-haiku-5-5",
    ]
    choice = data["generatorChoice"]
    assert (choice["shipped"], choice["chosen"]) == ("gpt-6-luna", "gpt-6-luna")
    assert choice["inconclusive"] is False and choice["reason"] is None
    [comparison] = choice["comparisons"]
    assert comparison["model"] == "claude-haiku-5-5"
    assert comparison["cases"] == 1
    assert comparison["qualifies"] is False
    assert choice["control"]["model"] == "Control Run"
    for test in (choice["control"], comparison):
        for score in ("factRecall", "faithfulness", "coverageGaps", "contradictedClaims"):
            result = test[score]
            assert (result["challengerOnly"], result["shippedOnly"]) == (0, 0)
            assert result["verdict"] == "indistinguishable"
            assert result["pAhead"] == 1.0 and result["pBehind"] == 1.0
        recall = test["factRecall"]
        assert (recall["paired"], recall["leftOut"]) == (1, 0)
        assert recall["difference"] == {"mean": 0.0, "low": 0.0, "high": 0.0, "confidence": 0.95}


def test_a_version_1_generator_comparison_still_exports(tmp_path, eval_dir, index, indexed_filings):
    _write_retrieval_report(eval_dir, golden_set=GOLDEN_SET_V1, evidence=False)
    v1 = {"golden_set": GOLDEN_SET_V1}
    shipped = _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna", **v1)
    challenger = _write_generation_report(
        eval_dir, index, tmp_path, "gpt-6.1-sol", "-gpt-6.1-sol", **v1
    )
    assert (
        selection.main(
            ["compare", str(shipped), str(challenger), "--rule", "generators"]
            + ["--json", str(eval_dir / "generator-choice-dev.json")],
            out=io.StringIO(),
        )
        == 0
    )

    data = _export(tmp_path, eval_dir, indexed_filings, *V1)

    runs = {run["model"]: run for run in data["generation"]}
    assert set(runs) == {"gpt-6-luna", "gpt-6.1-sol"}
    assert runs["gpt-6.1-sol"]["overall"]["meanCostUsd"] == pytest.approx(0.05)
    choice = data["generatorChoice"]
    assert choice["control"] is None
    [comparison] = choice["comparisons"]
    assert comparison["model"] == "gpt-6.1-sol"
    assert comparison["factRecall"]["verdict"] == "indistinguishable"


def test_the_export_carries_the_brief_suite_verdict_case_by_case(
    tmp_path, eval_dir, index, indexed_filings
):
    _write_retrieval_report(eval_dir)
    path = eval_dir / "brief-suite.json"
    generation.main(
        ["--brief-suite", "--case", "brief-risk-aapl-tsla-jpm", "--runs", "2"]
        + ["--index", str(index), "--log", str(tmp_path / "log"), "--json", str(path)],
        model=FakeModel("gpt-6-luna", ANSWER),
        judge=FakeJudge(),
        fact_values=lambda tickers: [],
        out=io.StringIO(),
    )

    brief = _export(tmp_path, eval_dir, indexed_filings)["briefSuite"]

    assert (brief["model"], brief["runs"], brief["passRuns"]) == ("gpt-6-luna", 2, 2)
    assert brief["judgeModel"] == JEV_MODEL
    [case] = brief["cases"]
    assert case["caseId"] == "brief-risk-aapl-tsla-jpm"
    assert case["briefQuestion"] is True  # the brief's own question, not a variant
    must_state = json.loads(path.read_text())["cases"][0]["facts"]
    assert case["mustState"] == sum(1 for f in must_state if f["tier"] == "must_state")
    # FakeJudge states every fact and supports every claim.
    assert case["passed"] is True and brief["casesPassed"] == 1
    assert case["missed"] == [] and case["contradictedRuns"] == []
    assert case["truncatedRuns"] == [] and case["failedRuns"] == []


def test_the_export_carries_every_holdout_run_beside_the_dev_reports(
    tmp_path, eval_dir, index, indexed_filings
):
    _write_retrieval_report(eval_dir)
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna")
    _write_retrieval_report(eval_dir, split="holdout")
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna", split="holdout")
    _write_generation_report(
        eval_dir, index, tmp_path, "gpt-6-luna", "-second", "holdout", "Apple relies on Asia [S1]."
    )

    data = _export(tmp_path, eval_dir, indexed_filings)

    assert data["split"] == "dev"
    assert [run["report"] for run in data["generation"]] == ["generation-dev.json"]
    holdout = data["holdout"]
    assert holdout["splitCases"] == len(_version_2().split("holdout"))
    assert [arm["name"] for arm in holdout["retrieval"]["arms"]] == ["fts5", "nothing", "hosted"]
    assert holdout["retrieval"]["gatingMetric"] == "evidence reached"
    first, second = holdout["generation"]
    assert first["report"] == "generation-holdout.json"
    assert second["report"] == "generation-holdout-second.json"
    assert first["overall"]["citationsValid"] == 0  # cites [S99]
    assert second["overall"]["citationsValid"] == 1


def test_a_holdout_scored_without_its_retrieval_report_still_shows_its_answers(
    tmp_path, eval_dir, index, indexed_filings
):
    _write_retrieval_report(eval_dir)
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna", split="holdout")

    holdout = _export(tmp_path, eval_dir, indexed_filings)["holdout"]

    assert holdout["retrieval"] is None
    assert [run["model"] for run in holdout["generation"]] == ["gpt-6-luna"]


def test_the_export_reads_the_chosen_splits_reports(tmp_path, eval_dir, indexed_filings):
    _write_retrieval_report(eval_dir, split="holdout")

    data = _export(tmp_path, eval_dir, indexed_filings, "--split", "holdout")

    assert data["split"] == "holdout"
    assert data["holdout"] is None  # the holdout is the split itself
    assert data["briefSuite"] is None  # outside the split
    assert data["retrieval"]["scoredCases"] + len(data["retrieval"]["unscored"]) == len(
        _version_2().split("holdout")
    )


def _run_export(tmp_path, eval_dir, *args):
    main(
        ["--eval-dir", str(eval_dir), "--out", str(tmp_path / "x.json"), *args],
        filings=[],
        today=TODAY,
        out=io.StringIO(),
    )


def test_the_export_refuses_a_dev_retrieval_report_of_another_golden_set_version(
    tmp_path, eval_dir
):
    """A version 1 report is refused by a version 2 export, and a version 2 report by a
    version 1 export, rather than mixed with the other version's counts."""
    _write_retrieval_report(eval_dir, golden_set=GOLDEN_SET_V1)
    with pytest.raises(SystemExit, match="scores Golden Set version 1"):
        _run_export(tmp_path, eval_dir)

    _write_retrieval_report(eval_dir)
    with pytest.raises(SystemExit, match="scores Golden Set version 2"):
        _run_export(tmp_path, eval_dir, *V1)


def test_the_export_refuses_a_dev_generation_report_of_another_golden_set_version(
    tmp_path, eval_dir, index
):
    _write_retrieval_report(eval_dir)
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna", golden_set=GOLDEN_SET_V1)

    with pytest.raises(SystemExit, match="generation-dev.json scores Golden Set version 1"):
        _run_export(tmp_path, eval_dir)


def test_the_export_refuses_a_holdout_retrieval_report_of_another_golden_set_version(
    tmp_path, eval_dir
):
    """Without the check, a version 1 export would pick up version 2's holdout reports."""
    _write_retrieval_report(eval_dir, golden_set=GOLDEN_SET_V1, evidence=False)
    _write_retrieval_report(eval_dir, split="holdout")

    with pytest.raises(SystemExit, match="retrieval-holdout.json scores Golden Set version 2"):
        _run_export(tmp_path, eval_dir, *V1)


def test_the_export_refuses_any_holdout_generation_report_of_another_golden_set_version(
    tmp_path, eval_dir, index
):
    _write_retrieval_report(eval_dir)
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna", split="holdout")
    _write_generation_report(
        eval_dir, index, tmp_path, "gpt-6-luna", "-v1", "holdout", golden_set=GOLDEN_SET_V1
    )

    with pytest.raises(SystemExit, match="generation-holdout-v1.json scores Golden Set version 1"):
        _run_export(tmp_path, eval_dir)


def test_a_missing_retrieval_report_names_the_command_that_writes_it(tmp_path, eval_dir):
    with pytest.raises(SystemExit, match="make eval-retrieval"):
        _run_export(tmp_path, eval_dir)


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
