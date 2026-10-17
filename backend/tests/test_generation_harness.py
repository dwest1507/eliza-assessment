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

    def __init__(self, nouls=None, choices=None, model=JEV_MODEL):
        self.requests = []
        self.nouls = nouls or {}
        self.choices = choices or {}
        self.model = model

    def system_one(self, state, questions, *, model=None, extra_headers=None):
        self.requests.append(SimpleNamespace(state=state, questions=questions, model=model))
        return SimpleNamespace(
            model=self.model,
            usage=SimpleNamespace(input_tokens=1_000, output_tokens=10),
            nouls={
                qid: SimpleNamespace(noul=self.nouls[q.instructions["required_fact"]])
                for qid, q in questions.items()
                if "required_fact" in q.instructions
            },
            choices={
                qid: SimpleNamespace(
                    choice=self.choices[q.instructions["claim"]],
                    probabilities={self.choices[q.instructions["claim"]]: 1.0},
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


def test_the_judge_refuses_an_answer_from_any_other_model_version():
    jev = FakeJev(nouls={"Apple outsources.": 0.9}, model="jev-1.14.0")

    with pytest.raises(RuntimeError, match="jev-1.14.0"):
        JevJudge(client=jev).judge("answer", ["Apple outsources."], [], SOURCES)


# --- Scoring Golden Set cases end to end ----------------------------------------------------


class FakeModel:
    """An answer model that writes a fixed answer and reports fixed usage."""

    model = "gpt-6-luna"

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def stream(self, messages):
        self.prompts.append(messages)
        yield from re.findall(r"\S+\s*|\s+", self.answer)  # word by word, as it streams
        from edgar_rag.answer_model import Usage

        yield Usage(input_tokens=20_000, output_tokens=1_000)


class FakeJudge:
    """Says every Required Fact is stated and every claim supported, and records what
    it was asked."""

    def __init__(self):
        self.asked = []

    def judge(self, answer, required_facts, claims, sources):
        from edgar_eval.judge import ClaimJudgment, FactJudgment, Judgments

        self.asked.append((answer, list(required_facts), list(claims), dict(sources)))
        return Judgments(
            facts=tuple(FactJudgment(f, 1.0 if "Apple" in f else 0.0) for f in required_facts),
            claims=tuple(ClaimJudgment(c.text, c.tags, "supported", {}) for c in claims),
            model=JEV_MODEL,
            requests=2,
            input_tokens=5_000,
        )


def _case(case_id, question, question_type="risk", facts=(), gaps=()):
    from edgar_rag.golden_set import CoverageGapLabel, GoldenCase, RequiredFact

    return GoldenCase(
        id=case_id,
        question=question,
        history=(),
        question_type=question_type,
        expected_sources=(),
        required_facts=tuple(RequiredFact(f, "X", "Risk Factors", "e") for f in facts),
        expected_coverage_gaps=tuple(CoverageGapLabel(k, c) for k, c in gaps),
        split="dev",
        starter=None,
        tags=(),
        notes="",
    )


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
        fact_values=lambda tickers: [416_161_000_000] if "AAPL" in set(tickers) else [],
        log_path=tmp_path / "answer_calls.jsonl",
    )

    [result] = report.cases
    assert report.errors == {}
    assert result.answer == ANSWER
    # Checks in code.
    assert result.citations.unknown_tags == ("S99",)  # not among this turn's Sources
    assert result.figures.passed  # matches Apple's revenue Financial Fact
    assert result.coverage_gaps.stated == ("periods_differ",)
    assert result.coverage_gaps.missing == ("no_guidance",)
    # Its structure, against the Companies its Sources come from (Apple and Tesla).
    assert not result.structure.passed
    assert any("AAPL, TSLA" in p for p in result.structure.problems)
    assert f"{result.structure.words} words, under 300" in result.structure.problems
    # Jev's judgments, asked about the case's Required Facts and the answer's claims.
    answer, facts, claims, sources = judge.asked[0]
    assert facts == ["Apple uses outsourcing partners.", "Tesla depends on Elon Musk."]
    assert [c.text for c in claims] == [
        "Apple relies on outsourcing partners in Asia.",
        "Tesla depends on its CEO.",
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
    data = json.loads(path.read_text())
    assert data["split"] == "dev"
    [case] = data["cases"]
    assert case["case_id"] == "risk-aapl-tsla-jpm"
    assert case["answer"] == ANSWER
    assert case["cost_usd"] == pytest.approx(0.0025)
    assert case["fact_recall"] is not None


def test_the_command_answers_through_a_chosen_arm_and_records_it(index, tmp_path):
    import io
    import json

    from edgar_eval.generation import main
    from edgar_eval.retrieval import Arm
    from edgar_rag.retrieval import prepare_answer_context

    used = []

    def arm(name, shipped=False):
        def prepare(messages, path):
            used.append(name)
            return prepare_answer_context(messages, path)

        return Arm(name, name, lambda m, i: [], shipped=shipped, prepare=prepare)

    path = tmp_path / "generation-arms-dev-dense.json"
    argv = ["--case", "risk-aapl-tsla-jpm", "--index", str(index), "--log", str(tmp_path / "l")]
    common = dict(judge=FakeJudge(), fact_values=lambda tickers: [], out=io.StringIO())
    arms = [arm("fts5", shipped=True), arm("dense")]

    main(
        [*argv, "--arm", "dense", "--json", str(path)], model=FakeModel(ANSWER), arms=arms, **common
    )
    main([*argv], model=FakeModel(ANSWER), arms=arms, **common)

    assert used == ["dense", "fts5"]  # the shipped Arm by default
    assert json.loads(path.read_text())["arm"] == "dense"


def test_the_jev_keys_placeholder_is_in_the_backends_env_example():
    from pathlib import Path

    from edgar_eval.judge import JEV_KEY_ENV

    example = Path(__file__).resolve().parents[1] / ".env.example"
    assert re.search(rf"^{JEV_KEY_ENV}=your-", example.read_text(), re.M)
