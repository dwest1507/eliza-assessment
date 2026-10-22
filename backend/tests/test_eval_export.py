"""The evaluation export: the harnesses' latest reports and the Company Calendars, written
as one JSON file for the front-end's "How it works" page and Calendar tab.

The reports are written by the harnesses' own command lines (with fake Arms, a fake
answer model and a fake judge), so the export is tested against the JSON they really
write.
"""

import io
import json
import os
import re
from datetime import date
from types import SimpleNamespace

import pytest

from edgar_eval import generation, retrieval, selection
from edgar_eval.export import company_calendars, main
from edgar_eval.judge import JEV_MODEL
from edgar_eval.retrieval import Arm
from edgar_rag._query_scope import ScopeCompany, find_companies
from edgar_rag.corpus import load_corpus
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
    assert data["holdout"] is None


def test_the_export_carries_no_brief_suite_no_retrieval_comparisons_and_no_coverage_grid(
    tmp_path, eval_dir, indexed_filings
):
    """Technical details show only the latest scoreboard and holdout run: the Brief Suite,
    the Arm and settings comparisons of earlier rounds and the Corpus coverage grid (now
    "What's covered", from the Company Calendars) are not exported, even when their
    reports are there."""
    _write_retrieval_report(eval_dir)
    for name in ("brief-suite.json", "arm-choice-dev.json", "settings-choice-dev.json"):
        (eval_dir / name).write_text("{}")

    data = _export(tmp_path, eval_dir, indexed_filings)

    for key in ("briefSuite", "armChoice", "settingsChoice", "coverage"):
        assert key not in data, key
    assert {c["ticker"] for c in data["companies"]} == {f.ticker for f in indexed_filings}


def _rewrite(path, **fields):
    """Records other values in a written report, as a report of another round would."""
    report = json.loads(path.read_text())
    report.update(fields)
    path.write_text(json.dumps(report))


def test_a_control_run_of_an_earlier_round_is_left_out(tmp_path, eval_dir, index, indexed_filings):
    """The round is the shipped run's code, prompt and Golden Set version (ADR 0011): a
    Control Run left from an earlier round is not shown beside a new round's shipped run."""
    _write_retrieval_report(eval_dir)
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna")
    control = _write_generation_report(
        eval_dir, index, tmp_path, "gpt-6-luna", name="generation-control-dev.json"
    )
    _rewrite(control, prompt_version="v7")

    data = _export(tmp_path, eval_dir, indexed_filings)

    assert [run["report"] for run in data["generation"]] == ["generation-dev.json"]


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


def test_a_generator_comparison_of_an_earlier_round_is_left_out(
    tmp_path, eval_dir, index, indexed_filings
):
    """A new round's shipped run (new code) is shown alone until its own comparison runs:
    the earlier round's Control Run, challengers and choice are not exported."""
    _write_retrieval_report(eval_dir)
    shipped = _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna")
    control = _write_generation_report(
        eval_dir, index, tmp_path, "gpt-6-luna", name="generation-control-dev.json"
    )
    challenger = _write_generation_report(
        eval_dir, index, tmp_path, "claude-haiku-5-5", "-claude-haiku-5-5"
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
    _rewrite(shipped, code_version="0123456789abcdef")

    data = _export(tmp_path, eval_dir, indexed_filings)

    assert [run["report"] for run in data["generation"]] == ["generation-dev.json"]
    assert data["generatorChoice"] is None


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


def _age(path, seconds):
    """Dates the report's file `seconds` into the past."""
    stamp = path.stat().st_mtime - seconds
    os.utime(path, (stamp, stamp))


def test_the_export_carries_only_the_latest_holdout_run_beside_the_dev_reports(
    tmp_path, eval_dir, index, indexed_filings
):
    """A later holdout run is kept as `generation-holdout-<suffix>.json` beside the first
    run's `generation-holdout.json`: the export shows only the latest, the suffixed report
    written last."""
    _write_retrieval_report(eval_dir)
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna")
    _write_retrieval_report(eval_dir, split="holdout")
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna", split="holdout")
    _write_generation_report(
        eval_dir, index, tmp_path, "gpt-6-luna", "-second", "holdout", "Apple relies on Asia [S1]."
    )
    earlier = _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna", "-a", "holdout")
    _age(earlier, 3600)

    data = _export(tmp_path, eval_dir, indexed_filings)

    assert data["split"] == "dev"
    assert [run["report"] for run in data["generation"]] == ["generation-dev.json"]
    holdout = data["holdout"]
    assert holdout["splitCases"] == len(_version_2().split("holdout"))
    assert [arm["name"] for arm in holdout["retrieval"]["arms"]] == ["fts5", "nothing", "hosted"]
    assert holdout["retrieval"]["gatingMetric"] == "evidence reached"
    run = holdout["generation"]
    assert run["report"] == "generation-holdout-second.json"
    assert run["overall"]["citationsValid"] == 1


def test_the_first_holdout_run_is_the_latest_until_another_is_kept(
    tmp_path, eval_dir, index, indexed_filings
):
    _write_retrieval_report(eval_dir)
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna", split="holdout")

    holdout = _export(tmp_path, eval_dir, indexed_filings)["holdout"]

    assert holdout["generation"]["report"] == "generation-holdout.json"
    assert holdout["generation"]["overall"]["citationsValid"] == 0  # cites [S99]


def test_a_holdout_scored_without_its_retrieval_report_still_shows_its_answers(
    tmp_path, eval_dir, index, indexed_filings
):
    _write_retrieval_report(eval_dir)
    _write_generation_report(eval_dir, index, tmp_path, "gpt-6-luna", split="holdout")

    holdout = _export(tmp_path, eval_dir, indexed_filings)["holdout"]

    assert holdout["retrieval"] is None
    assert holdout["generation"]["model"] == "gpt-6-luna"


def test_the_export_reads_the_chosen_splits_reports(tmp_path, eval_dir, indexed_filings):
    _write_retrieval_report(eval_dir, split="holdout")

    data = _export(tmp_path, eval_dir, indexed_filings, "--split", "holdout")

    assert data["split"] == "holdout"
    assert data["holdout"] is None  # the holdout is the split itself
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


def test_the_export_refuses_a_holdout_generation_report_of_another_golden_set_version(
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


# --- The Company Calendars ----------------------------------------------------------------


MONTHS = re.compile(
    r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?: \d{4})?"
    r"–(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}$"
)


@pytest.fixture(scope="module")
def calendars(indexed_filings):
    return {c["ticker"]: c for c in company_calendars(indexed_filings)}


def _period(calendar, fiscal_period):
    return next(p for p in calendar["periods"] if p["fiscalPeriod"] == fiscal_period)


def test_the_export_carries_every_companys_calendar_and_the_missing_companies(
    tmp_path, eval_dir, indexed_filings
):
    _write_retrieval_report(eval_dir)

    data = _export(tmp_path, eval_dir, indexed_filings)

    assert [c["ticker"] for c in data["companies"]] == sorted({f.ticker for f in indexed_filings})
    nvda = next(c for c in data["companies"] if c["ticker"] == "NVDA")
    assert nvda["company"] == "NVIDIA Corporation"
    assert nvda["sector"] == "Information Technology"
    assert nvda["coverage"] == "tracked"
    # The curated list of notable Companies not in the Corpus, as the Query Scope reads it.
    assert {
        "name": "Wells Fargo",
        "ticker": "WFC",
        "aliases": ["Wells Fargo & Company", "WFC"],
        "sector": "Financials",
    } in data["missingCompanies"]


def test_every_period_of_every_calendar_carries_its_calendar_months(calendars):
    for calendar in calendars.values():
        assert calendar["periods"], calendar["ticker"]
        for period in calendar["periods"]:
            assert MONTHS.match(period["months"]), (calendar["ticker"], period)
            assert period["calendarYear"] == int(period["months"][-4:])


def test_the_fiscal_year_end_is_named_as_the_filings_date_it(calendars):
    # NVIDIA's 52/53-week year ends on the last Sunday of January, Apple's on the last
    # Saturday of September; Tesla's on 31 December.
    assert calendars["NVDA"]["fiscalYearEnd"] == "late January"
    assert calendars["AAPL"]["fiscalYearEnd"] == "late September"
    assert calendars["TSLA"]["fiscalYearEnd"] == "December 31"
    # Target's only 10-K ends on 1 February, which stands for the end of January.
    assert calendars["TGT"]["fiscalYearEnd"] == "late January or early February"


def test_nvidias_calendar_places_its_fiscal_periods_in_calendar_months(calendars):
    nvda = calendars["NVDA"]

    q3 = _period(nvda, "Q3 FY2026")
    assert q3 | {"revenue": None} == {
        "fiscalPeriod": "Q3 FY2026",
        "kind": "quarter",
        "months": "Aug–Oct 2025",
        "calendarYear": 2025,
        "filing": {
            "filingId": "NVDA_10-Q_2025-10-26",
            "formType": "10-Q",
            "reportPeriod": "2025-10-26",
        },
        "revenue": None,
    }
    assert q3["revenue"] == {
        "value": 57_006_000_000,
        "filingId": "NVDA_10-Q_2025-10-26",
        "label": "Revenue",
        "derived": None,
    }

    fy = _period(nvda, "FY2025")
    assert fy["kind"] == "year"
    assert fy["months"] == "Feb 2024–Jan 2025"
    assert fy["calendarYear"] == 2025
    assert fy["filing"]["filingId"] == "NVDA_10-K_2025-01-26"
    assert fy["revenue"]["value"] == 130_497_000_000
    assert fy["revenue"]["derived"] is None


def test_a_fourth_quarter_is_derived_from_the_year_and_marked_as_derived(calendars):
    q4 = _period(calendars["NVDA"], "Q4 FY2025")

    assert q4["months"] == "Nov 2024–Jan 2025"
    # The 10-K's year less its three 10-Q quarters: 130,497 − 26,044 − 30,040 − 35,082.
    assert q4["filing"]["filingId"] == "NVDA_10-K_2025-01-26"
    assert q4["revenue"] == {
        "value": 39_331_000_000,
        "filingId": "NVDA_10-K_2025-01-26",
        "label": None,
        "derived": "FY2025 less Q1–Q3 FY2025",
    }


def test_a_calendar_runs_newest_first_with_each_year_beside_its_fourth_quarter(calendars):
    periods = [p["fiscalPeriod"] for p in calendars["NVDA"]["periods"]]

    # From the latest Filing (Q3 FY2026) back to the first, every quarter once.
    assert periods[:6] == [
        "Q3 FY2026",
        "Q2 FY2026",
        "Q1 FY2026",
        "FY2025",
        "Q4 FY2025",
        "Q3 FY2025",
    ]
    quarters = [p for p in periods if p.startswith("Q")]
    assert len(quarters) == len(set(quarters))
    assert periods[-1] == "Q4 FY2022" or periods[-1].startswith("Q1")


def test_tracked_companies_have_revenue_for_every_filed_quarter_and_year(calendars):
    for ticker in ("AAPL", "NVDA", "TSLA"):
        periods = {p["fiscalPeriod"]: p for p in calendars[ticker]["periods"]}
        for name, period in periods.items():
            year = name.split("FY")[1]
            # A fourth quarter is derived only when its year's three 10-Qs are filed.
            filed = (
                all(periods.get(f"Q{q} FY{year}", {}).get("filing") for q in (1, 2, 3))
                if name.startswith("Q4")
                else period["filing"]
            )
            assert bool(period["revenue"]) == bool(filed), (ticker, name)
    # Apple's Corpus starts at its second quarter of fiscal 2022, so that year's fourth
    # quarter can't be derived.
    assert _period(calendars["AAPL"], "Q4 FY2022")["revenue"] is None
    assert _period(calendars["AAPL"], "Q4 FY2023")["revenue"]["derived"]


def test_snapshot_companies_have_the_revenue_their_filings_yield(calendars):
    jpm = calendars["JPM"]
    assert jpm["coverage"] == "snapshot"
    assert _period(jpm, "FY2025")["revenue"]["value"] == 182_447_000_000
    assert _period(jpm, "Q1 FY2025")["revenue"]["value"] == 45_310_000_000
    q4 = _period(jpm, "Q4 FY2025")["revenue"]
    assert (q4["value"], bool(q4["derived"])) == (45_798_000_000, True)
    # Target's one 10-K yields no revenue figure.
    assert calendars["TGT"]["coverage"] == "snapshot"
    assert all(p["revenue"] is None for p in calendars["TGT"]["periods"])


def test_a_quarter_with_no_filing_is_listed_without_one_and_its_year_is_not_split(
    indexed_filings,
):
    # Without NVIDIA's Q2 FY2025 10-Q, that quarter is a gap and its fourth quarter
    # can't be derived.
    filings = [f for f in indexed_filings if f.filing_id != "NVDA_10-Q_2024-07-28"]

    nvda = next(c for c in company_calendars(filings) if c["ticker"] == "NVDA")

    gap = _period(nvda, "Q2 FY2025")
    assert gap["filing"] is None and gap["revenue"] is None
    assert gap["months"] == "May–Jul 2024"
    assert _period(nvda, "Q4 FY2025")["revenue"] is None
    assert _period(nvda, "FY2025")["revenue"]["value"] == 130_497_000_000


def test_each_calendar_carries_the_common_names_questions_match_it_by():
    filings = [f for f in load_corpus() if f.ticker in {"GOOG", "KO", "META", "NVDA"}]

    calendars = {c["ticker"]: c for c in company_calendars(filings)}

    assert calendars["GOOG"]["commonNames"] == ["Alphabet", "Google"]
    assert calendars["KO"]["commonNames"] == ["Coca-Cola", "Coca Cola", "Coke"]
    assert calendars["META"]["commonNames"] == ["Meta Platforms", "Meta", "Facebook"]
    assert calendars["NVDA"]["commonNames"] == ["NVIDIA"]
    # Taken from the Query Scope parser's alias table, so each is a name a question is
    # matched by: the search on "What's covered" can't drift from what questions understand.
    companies = [ScopeCompany(c["ticker"], c["company"], c["coverage"]) for c in calendars.values()]
    for calendar in calendars.values():
        for name in calendar["commonNames"]:
            named, _ = find_companies(f"What does {name} say?", companies)
            assert [c.ticker for c in named] == [calendar["ticker"]], name
