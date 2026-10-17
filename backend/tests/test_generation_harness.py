"""The generation harness: the pinned Jev judge, and how it scores Golden Set cases end
to end with a fake answer model and a fake judge. Answer cost is in test_generators.py."""

import re
from types import SimpleNamespace

import pytest

from edgar_eval.answer_checks import Claim
from edgar_eval.judge import JEV_MODEL, Evidence, JevJudge

# --- The Jev judge --------------------------------------------------------------------------


def test_jev_is_pinned_to_an_exact_version_never_an_alias():
    assert re.fullmatch(r"jev-\d+\.\d+\.\d+", JEV_MODEL)


class FakeJev:
    """Records every request and answers from fixed tables."""

    def __init__(self, nouls=None, choices=None, model=JEV_MODEL, fail_on=()):
        self.requests = []
        self.nouls = nouls or {}
        self.choices = choices or {}
        self.model = model
        self.fail_on = set(fail_on)
        """Required Facts or claims whose request fails, as a long input fails."""

    def system_one(self, state, questions, *, model=None, extra_headers=None):
        self.requests.append(SimpleNamespace(state=state, questions=questions, model=model))
        asked = {
            q.instructions.get("required_fact") or q.instructions.get("claim")
            for q in questions.values()
        }
        if asked & self.fail_on:
            raise RuntimeError("max_tokens_exceeded: the state is too long")
        return SimpleNamespace(
            model=self.model,
            usage=SimpleNamespace(input_tokens=1_000, output_tokens=10),
            nouls={
                qid: SimpleNamespace(noul=self.nouls.get(q.instructions["required_fact"], 0.0))
                for qid, q in questions.items()
                if "required_fact" in q.instructions
            },
            choices={
                qid: SimpleNamespace(
                    choice=self.choices.get(q.instructions["claim"], "supported"),
                    probabilities={self.choices.get(q.instructions["claim"], "supported"): 1.0},
                )
                for qid, q in questions.items()
                if "claim" in q.instructions
            },
        )


SOURCES = {
    "S1": Evidence("S1", "AAPL 10-K FY2025, Risk Factors", "Apple outsources manufacturing."),
    "S2": Evidence("S2", "TSLA 10-K FY2025, Risk Factors", "Tesla depends on Elon Musk."),
}


def test_the_judge_asks_jev_whether_the_answer_states_each_required_fact():
    jev = FakeJev(nouls={"Apple outsources.": 0.9, "Tesla needs Musk.": 0.2})

    judgments = JevJudge(client=jev).judge(
        "Apple outsources [S1].", ["Apple outsources.", "Tesla needs Musk."], [], SOURCES
    )

    assert [r.model for r in jev.requests] == [JEV_MODEL]
    assert jev.requests[0].state == {"answer": "Apple outsources [S1]."}
    assert [f.probability for f in judgments.facts] == [0.9, 0.2]
    assert judgments.fact_recall == 0.5  # one of two stated (probability at least 0.5)


def test_the_judge_asks_jev_whether_each_claims_cited_sources_support_it():
    claims = [
        Claim("Apple outsources manufacturing.", ("S1",)),
        Claim("Apple builds its own chips.", ("S1",)),
        Claim("Tesla depends on Elon Musk.", ("S2",)),
    ]
    jev = FakeJev(
        choices={
            "Apple outsources manufacturing.": "supported",
            "Apple builds its own chips.": "unsupported",
            "Tesla depends on Elon Musk.": "supported",
        }
    )

    judgments = JevJudge(client=jev).judge("answer", [], claims, SOURCES)

    # One request per set of cited Sources, which is its state.
    assert [[s["tag"] for s in r.state["sources"]] for r in jev.requests] == [["S1"], ["S2"]]
    assert {r.model for r in jev.requests} == {JEV_MODEL}
    assert [c.verdict for c in judgments.claims] == ["supported", "unsupported", "supported"]
    assert judgments.faithfulness == pytest.approx(2 / 3)
    assert judgments.input_tokens == 2_000
    assert judgments.cost_usd == pytest.approx(2_000 * 0.042 / 1_000_000)


def test_a_claim_citing_no_known_source_is_unsupported_without_asking():
    jev = FakeJev()

    judgments = JevJudge(client=jev).judge("answer", [], [Claim("Made up.", ("S9",))], SOURCES)

    assert jev.requests == []
    assert [c.verdict for c in judgments.claims] == ["unsupported"]


def test_no_facts_or_claims_means_no_score_rather_than_zero():
    judgments = JevJudge(client=FakeJev()).judge("answer", [], [], SOURCES)

    assert judgments.fact_recall is None
    assert judgments.faithfulness is None


def test_a_failed_request_is_recorded_against_its_judgment_and_the_rest_are_kept():
    claims = [
        Claim("Apple outsources manufacturing.", ("S1",)),
        Claim("Tesla depends on Elon Musk.", ("S2",)),
    ]
    jev = FakeJev(fail_on={"Tesla depends on Elon Musk."})

    judgments = JevJudge(client=jev).judge("answer", ["Apple outsources."], claims, SOURCES)

    [failure] = judgments.failures
    assert failure.judgment == "faithfulness"
    assert failure.items == ("Tesla depends on Elon Musk.",)
    assert "max_tokens_exceeded" in failure.error
    # The other judgments stand; the score that depends on the failed one is missing.
    assert [c.claim for c in judgments.claims] == ["Apple outsources manufacturing."]
    assert judgments.fact_recall == 0.0
    assert judgments.faithfulness is None


def test_the_judge_refuses_an_answer_from_any_other_model_version():
    jev = FakeJev(nouls={"Apple outsources.": 0.9}, model="jev-1.14.0")

    with pytest.raises(RuntimeError, match="jev-1.14.0"):
        JevJudge(client=jev).judge("answer", ["Apple outsources."], [], SOURCES)


# --- Scoring Golden Set cases end to end ----------------------------------------------------


class FakeModel:
    """An answer model that writes a fixed answer and reports fixed usage."""

    model = "gpt-6-luna"

    def __init__(self, answer, stop_reason="complete"):
        self.answer = answer
        self.stop_reason = stop_reason
        self.prompts = []

    def stream(self, messages):
        self.prompts.append(messages)
        yield from re.findall(r"\S+\s*|\s+", self.answer)  # word by word, as it streams
        from edgar_rag.answer_model import Usage

        raw = {"complete": "stop", "token_cap": "length"}.get(self.stop_reason)
        yield Usage(20_000, 1_000, stop_reason=self.stop_reason, raw_stop_reason=raw)


class FakeJudge:
    """Says every Required Fact about Apple is stated and every claim supported, unless
    `verdicts` gives a claim another verdict, and records what it was asked."""

    def __init__(self, verdicts=None):
        self.asked = []
        self.verdicts = verdicts or {}

    def judge(self, answer, required_facts, claims, sources):
        from edgar_eval.judge import ClaimJudgment, FactJudgment, Judgments

        self.asked.append((answer, list(required_facts), list(claims), dict(sources)))
        return Judgments(
            facts=tuple(FactJudgment(f, 1.0 if "Apple" in f else 0.0) for f in required_facts),
            claims=tuple(
                ClaimJudgment(c.text, c.tags, self.verdicts.get(c.text, "supported"), {})
                for c in claims
            ),
            model=JEV_MODEL,
            requests=2,
            input_tokens=5_000,
        )


def _case(case_id, question, question_type="risk", facts=(), gaps=(), details=()):
    from edgar_rag.golden_set import CoverageGapLabel, GoldenCase, RequiredFact

    return GoldenCase(
        id=case_id,
        question=question,
        history=(),
        question_type=question_type,
        expected_sources=(),
        required_facts=tuple(RequiredFact(f, "X", "Risk Factors", "e") for f in facts)
        + tuple(RequiredFact(f, "X", "Risk Factors", "e", tier="detail") for f in details),
        expected_coverage_gaps=tuple(CoverageGapLabel(k, c) for k, c in gaps),
        split="dev",
        starter=None,
        tags=(),
        notes="",
    )


APPLE_10K = "AAPL_10-K_2025-09-27"
APPLE_FY2024_10K = "AAPL_10-K_2024-09-28"

ANSWER = (
    "Apple relies on outsourcing partners in Asia [S1]. Tesla depends on its CEO [S99].\n\n"
    "Apple's revenue was $416.2 billion.\n\n"
    "## Coverage\n\nThe periods differ: Apple's fiscal year ends in September."
)


def test_each_case_is_answered_checked_judged_and_priced(index, tmp_path):
    from edgar_eval.generation import evaluate

    cases = [
        _case(
            "apple-tesla",
            "What are the primary risk factors facing Apple and Tesla?",
            facts=["Apple uses outsourcing partners.", "Tesla depends on Elon Musk."],
            gaps=[("periods_differ", ("AAPL", "TSLA")), ("no_guidance", ("TSLA",))],
        )
    ]
    model, judge = FakeModel(ANSWER), FakeJudge()

    report = evaluate(
        cases,
        model,
        judge,
        index,
        names={"AAPL": ("AAPL", "Apple"), "TSLA": ("TSLA", "Tesla")},
        fact_values=lambda filing_id: [416_161_000_000] if filing_id == APPLE_10K else [],
        log_path=tmp_path / "answer_calls.jsonl",
    )

    [result] = report.cases
    assert report.errors == {}
    assert result.answer == ANSWER
    # Checks in code.
    assert result.citations.unknown_tags == ("S99",)  # not among this turn's Sources
    assert result.figures.passed  # matches the revenue Financial Fact of a cited 10-K
    assert result.coverage_gaps.stated == ("periods_differ",)
    assert result.coverage_gaps.missing == ("no_guidance",)
    # Its structure, against the Companies its Sources come from (Apple and Tesla).
    assert not result.structure.passed
    assert any("AAPL, TSLA" in p for p in result.structure.problems)
    assert f"{result.structure.words} words, under 300" in result.structure.problems
    # Jev's judgments, asked about the case's Required Facts and the answer's claims.
    answer, facts, claims, sources = judge.asked[0]
    assert facts == ["Apple uses outsourcing partners.", "Tesla depends on Elon Musk."]
    assert [(c.text, c.tags) for c in claims] == [
        ("Apple relies on outsourcing partners in Asia.", ("S1",)),
        ("Tesla depends on its CEO.", ("S99",)),
        ("Apple's revenue was $416.2 billion.", ()),  # cites nothing, so is a claim on none
    ]
    assert "S1" in sources and sources["S1"].text
    assert result.fact_recall == 0.5
    assert result.faithfulness == 1.0
    # Cost and latency come from the Answer Call's record, which is logged.
    assert (result.input_tokens, result.output_tokens) == (20_000, 1_000)
    assert result.cost_usd == pytest.approx(0.0025)
    assert result.latency_s >= 0
    assert (tmp_path / "answer_calls.jsonl").read_text().count("\n") == 1
    # And sit next to the scores in the summary.
    overall = report.overall
    assert (overall.citations_valid, overall.figures_exact, overall.coverage_gaps_stated) == (
        0,
        1,
        0,
    )
    assert (overall.fact_recall, overall.faithfulness) == (0.5, 1.0)
    assert overall.structure_followed == 0
    assert overall.mean_words == result.structure.words
    assert overall.mean_cost_usd == pytest.approx(0.0025)
    assert overall.judge_cost_usd == pytest.approx(5_000 * 0.042 / 1_000_000)
    assert report.by_type["risk"].cases == 1


def test_every_generation_report_records_the_fact_cut_off(index, tmp_path):
    import json

    from edgar_eval.generation import evaluate
    from edgar_eval.judge import FACT_CUTOFF

    cases = [_case("apple", "What are Apple's risks?", facts=["Apple uses outsourcing."])]
    report = evaluate(
        cases,
        FakeModel(ANSWER),
        FakeJudge(),
        index,
        names={},
        fact_values=lambda filing_id: [],
        log_path=None,
    )

    assert FACT_CUTOFF == 0.6  # set by the judge study (ADR 0013)
    assert report.fact_cutoff == FACT_CUTOFF
    assert json.loads(json.dumps(report.to_dict()))["fact_cutoff"] == 0.6


def test_fact_recall_scores_must_state_facts_and_detail_recall_the_details(index, tmp_path):
    import json

    from edgar_eval.generation import evaluate

    cases = [
        _case(
            "both-tiers",
            "What are the primary risk factors facing Apple and Tesla?",
            facts=["Apple uses outsourcing partners.", "Tesla depends on Elon Musk."],
            details=["Apple sells the iPhone.", "Tesla builds cars in Texas.", "Tesla has a CEO."],
        ),
        _case("must-state-only", "What are Apple's risks?", facts=["Apple uses outsourcing."]),
    ]
    judge = FakeJudge()  # states the facts that name Apple, and no others

    report = evaluate(
        cases,
        FakeModel(ANSWER),
        judge,
        index,
        names={},
        fact_values=lambda filing_id: [],
        log_path=None,
    )

    # Jev is asked about every fact, of both tiers, in one judgment.
    assert sorted(len(facts) for _, facts, _, _ in judge.asked) == [1, 5]
    both, must_state_only = report.cases
    assert both.fact_recall == 0.5  # one of the two must-state facts
    assert both.detail_recall == pytest.approx(1 / 3)  # one of the three details
    assert must_state_only.fact_recall == 1.0
    assert must_state_only.detail_recall is None  # no detail to score, not zero
    assert report.overall.fact_recall == 0.75
    assert report.overall.detail_recall == pytest.approx(1 / 3)
    assert report.by_type["risk"].detail_recall == pytest.approx(1 / 3)
    # Both are written into the report, per case and overall.
    data = json.loads(json.dumps(report.to_dict()))
    assert [c["fact_recall"] for c in data["cases"]] == [0.5, 1.0]
    assert [c["detail_recall"] for c in data["cases"]] == [pytest.approx(1 / 3), None]
    assert data["cases"][0]["fact_tiers"] == ["must_state"] * 2 + ["detail"] * 3
    assert data["overall"]["detail_recall"] == pytest.approx(1 / 3)


def test_an_answer_cut_off_at_the_token_cap_fails_with_no_fact_recall(index):
    from edgar_eval.generation import evaluate

    cases = [
        _case(
            case_id,
            "What are the primary risk factors facing Apple?",
            facts=["Apple uses outsourcing partners."],
        )
        for case_id in ("cut-off", "finished")
    ]
    whole = "Apple relies on outsourcing partners in Asia [S1]."
    judge = FakeJudge()  # says the fact is stated and every claim supported

    report = evaluate(
        cases[:1],
        FakeModel(whole + " Apple also", stop_reason="token_cap"),
        judge,
        index,
        names={},
        fact_values=lambda filing_id: [],
        log_path=None,
    )
    finished = evaluate(
        cases[1:],
        FakeModel(whole),
        judge,
        index,
        names={},
        fact_values=lambda filing_id: [],
        log_path=None,
    )

    [result] = report.cases
    assert (result.stop_reason, result.raw_stop_reason) == ("token_cap", "length")
    assert result.truncated
    assert not result.passed
    assert result.fact_recall == 0.0
    # What it did write is still judged for Faithfulness.
    assert judge.asked[0][2][0].text == "Apple relies on outsourcing partners in Asia."
    assert result.faithfulness is not None
    assert (report.overall.truncated, report.overall.fact_recall) == (1, 0.0)
    data = report.to_dict()["cases"][0]
    assert (data["truncated"], data["passed"], data["fact_recall"]) == (True, False, 0.0)
    # The same answer, finished, passes with its Fact Recall.
    [done] = finished.cases
    assert (done.truncated, done.passed, done.fact_recall) == (False, True, 1.0)
    assert finished.overall.truncated == 0


def test_a_jev_failure_on_one_fact_keeps_the_cases_checks_and_other_judgments(index):
    from edgar_eval.generation import evaluate

    case = _case(
        "apple-tesla",
        "What are the primary risk factors facing Apple and Tesla?",
        facts=["Apple uses outsourcing partners.", "Tesla depends on Elon Musk."],
        gaps=[("periods_differ", ("AAPL", "TSLA"))],
        details=["Apple sells the iPhone."],
    )
    judge = JevJudge(client=FakeJev(fail_on={"Tesla depends on Elon Musk."}))

    report = evaluate(
        [case],
        FakeModel(ANSWER),
        judge,
        index,
        names={"AAPL": ("AAPL", "Apple"), "TSLA": ("TSLA", "Tesla")},
        fact_values=lambda filing_id: [416_161_000_000] if filing_id == APPLE_10K else [],
        log_path=None,
    )

    assert report.errors == {}
    [result] = report.cases
    # The code checks are kept.
    assert result.citations.unknown_tags == ("S99",)
    assert result.figures.passed
    assert result.coverage_gaps.stated == ("periods_differ",)
    assert result.structure.words > 0
    # So are the other judgments: Faithfulness, one claim judged, one citing no Source
    # of the turn and one uncited.
    assert [c.verdict for c in result.judgments.claims] == [
        "supported",
        "unsupported",
        "unsupported",
    ]
    assert result.faithfulness == pytest.approx(1 / 3)
    # The failure is listed, and the Fact Recall that depends on it is missing, not 0.
    [failure] = result.judgments.failures
    assert failure.judgment == "fact_recall"
    assert "max_tokens_exceeded" in failure.error
    assert result.fact_recall is None
    assert result.detail_recall is None
    assert report.overall.fact_recall is None
    assert report.overall.faithfulness == pytest.approx(1 / 3)
    assert report.overall.judgments_failed == 1
    assert report.by_type["risk"].judgments_failed == 1
    [saved] = report.to_dict()["cases"]
    assert saved["fact_recall"] is None
    assert saved["judgments"]["failures"][0]["judgment"] == "fact_recall"


def test_the_command_line_lists_every_failed_judgment(index, tmp_path):
    import io
    import json

    from edgar_eval.generation import main

    out = io.StringIO()
    path = tmp_path / "generation-dev.json"
    jev = FakeJev(fail_on={"Apple relies on outsourcing partners in Asia."})
    code = main(
        ["--case", "risk-aapl-tsla-jpm", "--index", str(index), "--log", str(tmp_path / "l")]
        + ["--json", str(path)],
        model=FakeModel(ANSWER),
        judge=JevJudge(client=jev),
        fact_values=lambda filing_id: [],
        out=out,
    )

    assert code == 0  # the case was answered and checked; only one judgment is missing
    printed = out.getvalue()
    assert "Judgments failed: 1" in printed
    assert "risk-aapl-tsla-jpm: Faithfulness of 1 claim" in printed
    assert "max_tokens_exceeded" in printed
    data = json.loads(path.read_text())
    assert data["errors"] == {}
    assert data["overall"]["judgments_failed"] == 1
    [case] = data["cases"]
    assert case["faithfulness"] is None and case["fact_recall"] is not None


def test_a_figure_matching_only_an_uncited_filings_financial_fact_fails(index, tmp_path):
    from edgar_eval.generation import evaluate

    report = evaluate(
        [_case("apple", "What are the primary risk factors facing Apple?")],
        FakeModel("Apple outsources manufacturing [S1]. Its revenue was $391.0 billion [S1]."),
        FakeJudge(),
        index,
        names={},
        # Apple's FY2024 revenue, reported by its FY2024 10-K, which no Source is from.
        fact_values=lambda filing_id: [391_035_000_000] if filing_id == APPLE_FY2024_10K else [],
        log_path=None,
    )

    [result] = report.cases
    assert result.figures.unmatched == ("$391.0 billion",)
    assert report.overall.figures_exact == 0


def test_a_score_with_nothing_to_score_is_none_not_zero(index, tmp_path):
    from edgar_eval.generation import evaluate

    report = evaluate(
        [_case("no-labels", "What are Apple's risk factors?")],
        FakeModel("Apple outsources manufacturing [S1]."),
        FakeJudge(),
        index,
        names={},
        fact_values=lambda tickers: [],
        log_path=None,
    )

    assert report.overall.coverage_gaps_stated is None
    assert report.overall.fact_recall is None
    assert report.overall.faithfulness == 1.0


CONTRADICTING_JEV = {"Tesla depends on its CEO.": "contradicted"}
"""A fake Jev's verdicts: one of `ANSWER`'s three claims contradicted by its Sources."""


def test_a_contradicted_claim_fails_the_answer_while_its_faithfulness_is_still_reported(
    index, tmp_path
):
    from edgar_eval.generation import evaluate

    cases = [
        _case("apple-tesla", "What are the primary risk factors facing Apple and Tesla?"),
        _case("apple", "What are the primary risk factors facing Apple?"),
    ]
    report = evaluate(
        cases,
        FakeModel(ANSWER),
        FakeJudge(verdicts=CONTRADICTING_JEV),
        index,
        names={},
        fact_values=lambda filing_id: [],
        log_path=None,
        workers=1,
    )

    for result in report.cases:
        assert result.contradictions.claims == ("Tesla depends on its CEO.",)
        assert result.contradictions.count == 1
        assert not result.contradictions.passed
        assert result.faithfulness == pytest.approx(2 / 3)  # two of three supported: a score
    assert report.overall.answers_contradicted == 2
    assert report.overall.faithfulness == pytest.approx(2 / 3)
    assert report.by_type["risk"].answers_contradicted == 2


def test_an_answer_with_no_contradicted_claim_passes_the_check(index, tmp_path):
    from edgar_eval.generation import evaluate

    report = evaluate(
        [_case("apple", "What are the primary risk factors facing Apple?")],
        FakeModel(ANSWER),
        FakeJudge(verdicts={"Tesla depends on its CEO.": "unsupported"}),
        index,
        names={},
        fact_values=lambda filing_id: [],
        log_path=None,
    )

    [result] = report.cases
    assert result.contradictions.count == 0
    assert result.contradictions.passed  # unsupported lowers Faithfulness, but is no contradiction
    assert result.faithfulness == pytest.approx(2 / 3)
    assert report.overall.answers_contradicted == 0


def test_the_report_and_its_summary_show_each_cases_contradicted_claims(index, tmp_path):
    import io
    import json

    from edgar_eval.generation import main

    out = io.StringIO()
    path = tmp_path / "generation-dev.json"
    code = main(
        [
            *("--case", "risk-aapl-tsla-jpm", "--index", str(index)),
            *("--log", str(tmp_path / "log.jsonl"), "--json", str(path)),
        ],
        model=FakeModel(ANSWER),
        judge=FakeJudge(verdicts=CONTRADICTING_JEV),
        fact_values=lambda filing_id: [],
        out=out,
    )

    assert code == 0
    data = json.loads(path.read_text())
    [case] = data["cases"]
    assert case["contradictions"] == {
        "claims": ["Tesla depends on its CEO."],
        "count": 1,
        "passed": False,
    }
    assert case["faithfulness"] == pytest.approx(2 / 3)
    assert data["overall"]["answers_contradicted"] == 1
    printed = out.getvalue()
    assert "Answers with a Contradicted Claim: 1 of 1" in printed
    assert "Contradicted Claims in risk-aapl-tsla-jpm: Tesla depends on its CEO." in printed


UNCITED_ANSWER = """\
Apple relies on outsourcing partners in Asia [S1].

## Apple

Apple's main risks are:

- Apple's iPhone sales fell by a third in 2025.

## Coverage

The Sources do not include Honeywell's filings.
"""


def test_an_uncited_sentence_is_unsupported_without_a_jev_call(index, tmp_path):
    from edgar_eval.generation import evaluate

    jev = FakeJev(choices={"Apple relies on outsourcing partners in Asia.": "supported"})

    report = evaluate(
        [_case("apple", "What are the primary risk factors facing Apple?")],
        FakeModel(UNCITED_ANSWER),
        JevJudge(client=jev),
        index,
        names={"AAPL": ("AAPL", "Apple")},
        fact_values=lambda filing_id: [],
        log_path=None,
    )

    [result] = report.cases
    # Only the cited sentence goes to Jev; the heading, the lead-in and the Coverage Gap
    # wording are not claims, and the uncited sentence is judged without a request.
    assert [list(r.questions.values())[0].instructions["claim"] for r in jev.requests] == [
        "Apple relies on outsourcing partners in Asia."
    ]
    assert [(c.claim, c.tags, c.verdict) for c in result.judgments.claims] == [
        ("Apple relies on outsourcing partners in Asia.", ("S1",), "supported"),
        ("Apple's iPhone sales fell by a third in 2025.", (), "unsupported"),
    ]
    assert result.faithfulness == 0.5
    assert report.overall.faithfulness == 0.5


CONTEXT_ANSWER = """\
## Tesla

It depends on its CEO [S1].

| Company | Main risk |
|---|---|
| Apple | Outsourcing [S1] |
"""


def _context_report(index, answer):
    from edgar_eval.generation import evaluate

    jev = FakeJev(
        choices={
            "It depends on its CEO.": "supported",
            "| Apple | Outsourcing |": "supported",
            "Apple relies on outsourcing partners in Asia.": "supported",
        }
    )
    report = evaluate(
        [_case("apple", "What are the primary risk factors facing Apple?")],
        FakeModel(answer),
        JevJudge(client=jev),
        index,
        names={"AAPL": ("AAPL", "Apple")},
        fact_values=lambda filing_id: [],
        log_path=None,
    )
    asked = [q.instructions for r in jev.requests for q in r.questions.values()]
    return report, asked


def test_a_claim_reaches_jev_with_its_heading_and_a_table_row_with_its_header(index):
    report, asked = _context_report(index, CONTEXT_ANSWER)

    # The context is beside the claim, marked as context, never part of the claim.
    assert [(i["claim"], i["context"]) for i in asked] == [
        ("It depends on its CEO.", {"heading": "Tesla"}),
        (
            "| Apple | Outsourcing |",
            {"heading": "Tesla", "table_header": "| Company | Main risk |"},
        ),
    ]
    assert all("`context`" in i["question"] for i in asked)
    assert report.cases[0].faithfulness == 1.0


def test_the_report_stores_each_claims_context_beside_it(index):
    report, _ = _context_report(index, CONTEXT_ANSWER)

    [case] = report.to_dict()["cases"]
    assert [(c["claim"], c["heading"], c["table_header"]) for c in case["judgments"]["claims"]] == [
        ("It depends on its CEO.", "Tesla", ""),
        ("| Apple | Outsourcing |", "Tesla", "| Company | Main risk |"),
    ]


def test_a_claim_with_no_heading_or_table_reaches_jev_as_before(index):
    report, asked = _context_report(index, "Apple relies on outsourcing partners in Asia [S1].")

    # No context and no mention of one: the same request as before claims carried context.
    [instructions] = asked
    assert instructions.keys() == {"claim", "question"}
    assert instructions["claim"] == "Apple relies on outsourcing partners in Asia."
    assert "context" not in instructions["question"]
    [claim] = report.to_dict()["cases"][0]["judgments"]["claims"]
    assert (claim["heading"], claim["table_header"]) == ("", "")


def test_the_command_line_prints_scores_with_cost_and_latency_and_writes_json(index, tmp_path):
    import io
    import json

    from edgar_eval.generation import main

    out = io.StringIO()
    path = tmp_path / "generation-dev.json"
    code = main(
        [
            "--case",
            "risk-aapl-tsla-jpm",
            "--index",
            str(index),
            "--log",
            str(tmp_path / "log.jsonl"),
            "--json",
            str(path),
        ],
        model=FakeModel(ANSWER),
        judge=FakeJudge(),
        fact_values=lambda tickers: [],
        out=out,
    )

    assert code == 0
    printed = out.getvalue()
    assert "gpt-6-luna" in printed and JEV_MODEL in printed
    assert "$/answer" in printed and "latency s" in printed
    assert "Truncated at the token cap: none" in printed
    data = json.loads(path.read_text())
    assert data["split"] == "dev"
    [case] = data["cases"]
    assert case["case_id"] == "risk-aapl-tsla-jpm"
    assert case["answer"] == ANSWER
    assert case["cost_usd"] == pytest.approx(0.0025)
    assert case["fact_recall"] is not None


def test_a_report_records_the_round_it_was_run_in(index, tmp_path):
    """The code, prompt and Golden Set version the selection commands match a shipped
    run and a Control Run on, to reuse them within a round (ADR 0011)."""
    import io
    import json

    from edgar_eval.generation import current_round, main
    from edgar_rag.retrieval import PROMPT_VERSION

    path = tmp_path / "generation-dev.json"
    main(
        ["--case", "risk-aapl-tsla-jpm", "--index", str(index), "--log", str(tmp_path / "l")]
        + ["--json", str(path)],
        model=FakeModel(ANSWER),
        judge=FakeJudge(),
        fact_values=lambda tickers: [],
        out=io.StringIO(),
    )

    data = json.loads(path.read_text())
    now = current_round()
    assert {k: data[k] for k in now} == now
    assert now["prompt_version"] == PROMPT_VERSION
    assert now["golden_set_version"] == data["golden_set_version"]


def test_the_code_version_changes_with_any_source_file(tmp_path):
    from edgar_eval.generation import code_version

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("A = 1\n")
    (tmp_path / "pkg" / "notes.txt").write_text("not code")
    before = code_version(tmp_path)

    assert code_version(tmp_path) == before
    (tmp_path / "pkg" / "notes.txt").write_text("still not code")
    assert code_version(tmp_path) == before
    (tmp_path / "pkg" / "a.py").write_text("A = 2\n")
    assert code_version(tmp_path) != before
    assert code_version() != code_version(tmp_path)  # the backend's own source by default


def test_the_command_answers_through_a_chosen_arm_and_records_it(index, tmp_path):
    import io
    import json

    from edgar_eval.generation import main
    from edgar_eval.retrieval import Arm
    from edgar_rag.retrieval import prepare_answer_context

    used = []

    def arm(name, shipped=False, query_api_call=False):
        def prepare(messages, path, **settings):
            used.append(name)
            return prepare_answer_context(messages, path, **settings)

        return Arm(
            name,
            name,
            lambda m, i, **settings: [],
            shipped=shipped,
            prepare=prepare,
            query_api_call=query_api_call,
        )

    path = tmp_path / "generation-arms-dev-dense.json"
    argv = ["--case", "risk-aapl-tsla-jpm", "--index", str(index), "--log", str(tmp_path / "l")]
    common = dict(judge=FakeJudge(), fact_values=lambda tickers: [], out=io.StringIO())
    arms = [arm("fts5", shipped=True), arm("dense", query_api_call=True)]

    main(
        [*argv, "--arm", "dense", "--json", str(path)], model=FakeModel(ANSWER), arms=arms, **common
    )
    main([*argv], model=FakeModel(ANSWER), arms=arms, **common)

    assert used == ["dense", "fts5"]  # the shipped Arm by default
    saved = json.loads(path.read_text())
    assert saved["arm"] == "dense"
    assert saved["query_api_call"] is True  # so the selection rule never chooses it


def _saved_report(index, tmp_path, answer, fact_values):
    """A generation report written by the command line, as `make eval-generation` saves it."""
    import io
    import json

    from edgar_eval.generation import main

    path = tmp_path / "generation-dev.json"
    argv = ["--case", "risk-aapl-tsla-jpm", "--index", str(index), "--log", str(tmp_path / "l")]
    code = main(
        [*argv, "--json", str(path)],
        model=FakeModel(answer),
        judge=FakeJudge(),
        fact_values=fact_values,
        out=io.StringIO(),
    )
    assert code == 0
    return path, json.loads(path.read_text())


class Refuses:
    """An answer model or judge that must not be called."""

    model = "never"

    def __getattr__(self, name):
        raise AssertionError(f"called {name} while rescoring")


def test_rescoring_redoes_the_figure_check_from_the_saved_answers_alone(index, tmp_path):
    import io
    import json

    from edgar_eval.generation import main

    answer = "Apple outsources manufacturing [S1]. Its revenue was $391.0 billion [S1]."
    # Saved under the old rule: any Financial Fact of Apple's, whichever Filing reports it.
    path, before = _saved_report(index, tmp_path, answer, lambda filing_id: [391_035_000_000])
    assert before["overall"]["figures_exact"] == 1.0

    out = io.StringIO()
    code = main(
        ["--rescore", str(path), "--index", str(index)],
        model=Refuses(),
        judge=Refuses(),
        fact_values=lambda filing_id: [391_035_000_000] if filing_id == APPLE_FY2024_10K else [],
        out=out,
    )

    assert code == 0
    after = json.loads(path.read_text())
    [case] = after["cases"]
    assert case["figures"] == {"figures": 1, "unmatched": ["$391.0 billion"]}
    assert after["overall"]["figures_exact"] == 0.0
    assert after["by_type"]["risk"]["figures_exact"] == 0.0
    # Nothing else in the report changes.
    for report in (before, after):
        for case in report["cases"]:
            case.pop("figures")
        for summary in (report["overall"], *report["by_type"].values()):
            summary.pop("figures_exact")
    assert after == before
    assert "1.00 → 0.00" in out.getvalue()


def test_a_report_saved_before_tiers_and_stop_reasons_still_loads_and_rescores(index, tmp_path):
    """Version 1 reports name no tier, no detail recall and no stop reason: every fact
    was must-state, and no answer was marked truncated."""
    import io
    import json

    from edgar_eval.generation import main
    from edgar_eval.selection import Candidate

    path, saved = _saved_report(index, tmp_path, ANSWER, lambda filing_id: [])
    for case in saved["cases"]:
        del case["fact_tiers"], case["detail_recall"]
        del case["stop_reason"], case["raw_stop_reason"], case["truncated"], case["passed"]
    for summary in (saved["overall"], *saved["by_type"].values()):
        del summary["detail_recall"], summary["truncated"]
    path.write_text(json.dumps(saved))

    code = main(
        ["--rescore", str(path), "--index", str(index)],
        model=Refuses(),
        judge=Refuses(),
        fact_values=lambda filing_id: [],
        out=io.StringIO(),
    )

    assert code == 0
    rescored = json.loads(path.read_text())
    assert rescored == saved  # the same figures, and no field added
    assert Candidate.from_report(rescored).fact_recall == {
        "risk-aapl-tsla-jpm": saved["cases"][0]["fact_recall"]
    }


def test_rescoring_refuses_a_report_whose_sources_cannot_be_rebuilt(index, tmp_path):
    import io
    import json

    from edgar_eval.generation import main

    path, saved = _saved_report(index, tmp_path, ANSWER, lambda filing_id: [])
    saved["cases"][0]["sources"] += 1  # as if answered from another index
    path.write_text(json.dumps(saved))

    with pytest.raises(ValueError, match="risk-aapl-tsla-jpm"):
        main(
            ["--rescore", str(path), "--index", str(index)],
            fact_values=lambda filing_id: [],
            out=io.StringIO(),
        )
    assert json.loads(path.read_text()) == saved


def test_rescoring_rebuilds_each_answer_context_at_the_reports_own_setting(index, tmp_path):
    """A report answered at another context budget is rescored at that budget, and one
    answered from an index of another chunk size is refused (ADR 0010)."""
    import io
    import json

    from edgar_eval.generation import main

    path = tmp_path / "generation-dev-budget3000.json"
    argv = ["--case", "trend-tsla-net-income-three-years", "--index", str(index)]
    main(
        [*argv, "--context-budget", "3000", "--log", str(tmp_path / "l"), "--json", str(path)],
        model=FakeModel(ANSWER),
        judge=FakeJudge(),
        fact_values=lambda filing_id: [],
        out=io.StringIO(),
    )
    saved = json.loads(path.read_text())

    rescore = ["--rescore", str(path), "--index", str(index)]
    assert main(rescore, fact_values=lambda filing_id: [], out=io.StringIO()) == 0
    assert json.loads(path.read_text())["cases"][0]["sources"] == saved["cases"][0]["sources"]

    path.write_text(json.dumps(saved | {"chunk_tokens": 300}))
    with pytest.raises(ValueError, match="300-token chunks"):
        main(rescore, fact_values=lambda filing_id: [], out=io.StringIO())


def test_a_report_saved_before_contradicted_claims_were_counted_still_loads(index, tmp_path):
    """A version 1 report has no Contradicted Claim fields: the rescore command and the
    selection rule still read it, as they read a report that has them."""
    import io
    import json

    from edgar_eval.generation import main
    from edgar_eval.selection import Candidate

    path, saved = _saved_report(index, tmp_path, ANSWER, lambda filing_id: [])
    assert "contradictions" in saved["cases"][0]
    old = json.loads(json.dumps(saved))
    for case in old["cases"]:
        del case["contradictions"]
    for summary in (old["overall"], *old["by_type"].values()):
        del summary["answers_contradicted"]

    for report in (saved, old):
        path.write_text(json.dumps(report))
        rescore = ["--rescore", str(path), "--index", str(index)]
        assert main(rescore, fact_values=lambda filing_id: [], out=io.StringIO()) == 0
        rescored = json.loads(path.read_text())
        assert rescored == report  # nothing to change: its figures were already checked
        candidate = Candidate.from_report(rescored)
        assert candidate.faithfulness == {"risk-aapl-tsla-jpm": 1.0}


def test_a_report_saved_before_judgment_failures_were_recorded_still_loads(index, tmp_path):
    """Version 1's saved reports have no `failures` in their judgments and no
    `judgments_failed` in their summaries: they still rescore and still compare."""
    import io
    import json

    from edgar_eval import selection
    from edgar_eval.generation import main

    path, saved = _saved_report(index, tmp_path, ANSWER, lambda filing_id: [])
    for case in saved["cases"]:
        del case["judgments"]["failures"]
    for summary in (saved["overall"], *saved["by_type"].values()):
        del summary["judgments_failed"]
    path.write_text(json.dumps(saved))

    rescore = ["--rescore", str(path), "--index", str(index)]
    assert main(rescore, fact_values=lambda filing_id: [], out=io.StringIO()) == 0
    candidate = selection.Candidate.from_report(json.loads(path.read_text()))
    assert candidate.fact_recall == {"risk-aapl-tsla-jpm": saved["cases"][0]["fact_recall"]}
    choice = path.with_name("arm-choice-dev.json")
    compare = ["compare", str(path), str(path), "--json", str(choice)]
    assert selection.main(compare, out=io.StringIO()) == 0


def test_the_jev_keys_placeholder_is_in_the_backends_env_example():
    from pathlib import Path

    from edgar_eval.judge import JEV_KEY_ENV

    example = Path(__file__).resolve().parents[1] / ".env.example"
    assert re.search(rf"^{JEV_KEY_ENV}=your-", example.read_text(), re.M)


def test_the_command_answers_with_a_chosen_context_budget_and_records_the_setting(index, tmp_path):
    import io
    import json

    from edgar_eval.generation import main
    from edgar_eval.retrieval import Arm
    from edgar_rag.retrieval import prepare_answer_context

    budgets = []

    def prepare(messages, path, context_budget):
        budgets.append(context_budget)
        return prepare_answer_context(messages, path, context_budget=context_budget)

    path = tmp_path / "generation-dev.json"
    argv = ["--case", "risk-aapl-tsla-jpm", "--index", str(index), "--log", str(tmp_path / "l")]
    common = dict(
        model=FakeModel(ANSWER),
        judge=FakeJudge(),
        fact_values=lambda t: [],
        arms=[Arm("fts5", "", lambda m, i, **settings: [], shipped=True, prepare=prepare)],
        out=io.StringIO(),
    )

    main([*argv, "--json", str(path)], **common)
    default = json.loads(path.read_text())
    main([*argv, "--context-budget", "6000", "--json", str(path)], **common)
    small = json.loads(path.read_text())

    assert budgets == [32_000, 6_000]
    assert (default["chunk_tokens"], default["context_budget"]) == (600, 32_000)
    assert (small["chunk_tokens"], small["context_budget"]) == (600, 6_000)
    assert default["settings"] == "chunks-600-budget-32000"
    assert small["settings"] == "chunks-600-budget-6000"


# --- Golden Set version 2 ----------------------------------------------------------------


def test_a_version_2_run_refuses_while_any_case_is_pending(
    index, tmp_path, golden_set_v2_file, capsys
):
    import io

    from edgar_eval.generation import main

    path = golden_set_v2_file({"risk-unh-cybersecurity": "dev", "outlook-tsla-2026": "pending"})
    model = FakeModel(ANSWER)

    with pytest.raises(SystemExit):
        main(
            ["--golden-set", str(path), "--index", str(index), "--log", str(tmp_path / "l")],
            model=model,
            judge=FakeJudge(),
            fact_values=lambda tickers: [],
            out=io.StringIO(),
        )

    assert "outlook-tsla-2026" in capsys.readouterr().err
    assert model.prompts == []  # refused before any Answer Call


def test_a_version_2_run_answers_its_recorded_split_once_frozen(
    index, tmp_path, golden_set_v2_file
):
    import io
    import json

    from edgar_eval.generation import main

    path = golden_set_v2_file(
        {"risk-unh-cybersecurity": "dev", "risk-aapl-legal-proceedings": "holdout"}
    )
    report = tmp_path / "generation-dev.json"

    code = main(
        [
            *("--golden-set", str(path), "--index", str(index)),
            *("--log", str(tmp_path / "l"), "--json", str(report)),
        ],
        model=FakeModel(ANSWER),
        judge=FakeJudge(),
        fact_values=lambda tickers: [],
        out=io.StringIO(),
    )

    assert code == 0
    data = json.loads(report.read_text())
    assert data["golden_set_version"] == 2
    assert [c["case_id"] for c in data["cases"]] == ["risk-unh-cybersecurity"]


def test_a_brief_suite_run_beside_golden_set_version_2_still_loads_the_suite(
    index, tmp_path, golden_set_v2_file
):
    """The Brief Suite's cases replace version 1 cases, which a version 2 file need not
    hold, so the suite is checked against both versions whichever file is named."""
    import io

    from edgar_eval.generation import main

    path = golden_set_v2_file({"risk-unh-cybersecurity": "pending"})

    code = main(
        [
            *("--golden-set", str(path), "--brief-suite", "--runs", "1"),
            *("--case", "brief-risk-aapl-tsla-jpm", "--index", str(index)),
            *("--log", str(tmp_path / "l")),
        ],
        model=FakeModel(ANSWER),
        judge=FakeJudge(),
        fact_values=lambda tickers: [],
        out=io.StringIO(),
    )

    assert code == 0
