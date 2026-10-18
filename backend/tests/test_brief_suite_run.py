"""The Brief Suite through the generation harness: each case answered several times, a
pass/fail verdict per case, the report case by case, and the cost estimate printed before
a paid run. A fake answer model and a fake Jev; no provider is called."""

import io
import json
import re
import threading

import pytest

from edgar_eval.judge import JEV_MODEL, ClaimJudgment, FactJudgment, Judgments
from edgar_rag.answer_model import Usage
from edgar_rag.golden_set import GoldenCase, RequiredFact

APPLE_QUESTION = "What are the primary risk factors facing Apple?"
REACHED = "outsourcing partners located primarily in China mainland, India, Japan"
"""An evidence quote from Apple's 10-K Risk Factors, which the question retrieves."""
NOT_REACHED = "a sentence no Filing contains"


class RunModel:
    """An answer model whose answer names the run it was asked in, counted per prompt (a
    case's prompt is the same in every run)."""

    model = "gpt-6-luna"

    def __init__(self, on_first_call=None):
        self.calls: dict[str, int] = {}
        self.lock = threading.Lock()
        self.on_first_call = on_first_call

    def stream(self, messages):
        prompt = messages[-1].content
        with self.lock:
            if not self.calls and self.on_first_call:
                self.on_first_call()
            run = self.calls[prompt] = self.calls.get(prompt, 0) + 1
        yield f"Apple outsources manufacturing to partners in Asia, run {run} [S1]."
        yield Usage(input_tokens=20_000, output_tokens=1_000, stop_reason="complete")


class RunJudge:
    """States each fact in the runs `stated` gives it (every run if not listed), and judges
    every claim of the runs in `contradicted` contradicted by its Sources."""

    def __init__(self, stated=None, contradicted=()):
        self.stated = stated or {}
        self.contradicted = set(contradicted)

    def judge(self, answer, required_facts, claims, sources):
        run = int(re.search(r"run (\d+)", answer).group(1))
        return Judgments(
            facts=tuple(
                FactJudgment(f, 1.0 if run in self.stated.get(f, {run}) else 0.0)
                for f in required_facts
            ),
            claims=tuple(
                ClaimJudgment(
                    c.text, c.tags, "contradicted" if run in self.contradicted else "supported", {}
                )
                for c in claims
            ),
            model=JEV_MODEL,
            requests=1,
            input_tokens=1_000,
        )


def _case(case_id, facts, details=(), question=APPLE_QUESTION):
    """A Brief Suite case: its facts as (text, evidence) pairs, outside the split."""
    return GoldenCase(
        id=case_id,
        question=question,
        history=(),
        question_type="risk",
        expected_sources=(),
        required_facts=tuple(
            RequiredFact(f, "AAPL_10-K_2025-09-27", "Risk Factors", e) for f, e in facts
        )
        + tuple(
            RequiredFact(f, "AAPL_10-K_2025-09-27", "Risk Factors", e, tier="detail")
            for f, e in details
        ),
        expected_coverage_gaps=(),
        split=None,
        starter=None,
        tags=(),
        notes="",
    )


def _run(cases, judge, index, runs=5):
    from edgar_eval.brief_suite import evaluate_brief_suite

    return evaluate_brief_suite(
        cases,
        RunModel(),
        judge,
        index,
        runs=runs,
        names={},
        fact_values=lambda filing_id: [],
        log_path=None,
        workers=1,
    )


OUTSOURCES = "Apple outsources manufacturing."
TARIFFS = "Apple faces tariffs."


def test_a_must_state_fact_stated_in_4_of_5_runs_passes_and_in_3_of_5_fails(index):
    cases = [_case("brief-apple", [(OUTSOURCES, REACHED), (TARIFFS, REACHED)])]

    four = _run(cases, RunJudge(stated={OUTSOURCES: {1, 2, 3, 5}}), index)
    three = _run(cases, RunJudge(stated={OUTSOURCES: {1, 3, 5}}), index)

    [passing] = four.cases
    assert passing.runs == 5
    assert [(f.fact, f.stated_runs) for f in passing.facts] == [(OUTSOURCES, 4), (TARIFFS, 5)]
    assert passing.passed and passing.missed == ()
    [failing] = three.cases
    assert not failing.passed
    assert [(f.fact, f.stated_runs, f.runs) for f in failing.missed] == [(OUTSOURCES, 3, 5)]


def test_a_detail_stated_in_few_runs_never_fails_the_case(index):
    cases = [_case("brief-apple", [(OUTSOURCES, REACHED)], details=[(TARIFFS, REACHED)])]

    report = _run(cases, RunJudge(stated={TARIFFS: {1}}), index)

    [case] = report.cases
    assert case.passed
    assert [(f.tier, f.stated_runs) for f in case.facts] == [("must_state", 5), ("detail", 1)]


def test_one_run_with_a_contradicted_claim_fails_the_case(index):
    cases = [_case("brief-apple", [(OUTSOURCES, REACHED)])]

    report = _run(cases, RunJudge(contradicted={4}), index)

    [case] = report.cases
    assert all(f.stated_runs == 5 for f in case.facts)  # every fact stated in every run
    assert not case.passed
    assert [(c.run, c.claims) for c in case.contradicted] == [
        (4, ("Apple outsources manufacturing to partners in Asia, run 4.",))
    ]


def test_evidence_reached_is_reported_for_each_fact(index):
    cases = [_case("brief-apple", [(OUTSOURCES, REACHED), (TARIFFS, NOT_REACHED)])]

    report = _run(cases, RunJudge(), index, runs=2)

    [case] = report.cases
    assert [(f.fact, f.evidence_reached_runs) for f in case.facts] == [
        (OUTSOURCES, 2),
        (TARIFFS, 0),
    ]
    # Each run's own answers are kept, one generation report per run.
    assert [len(r.cases) for r in report.run_reports] == [1, 1]
    assert report.run_reports[0].cases[0].evidence_reached == (True, False)


def test_a_run_that_could_not_be_answered_counts_against_the_case(index):
    from edgar_eval.brief_suite import evaluate_brief_suite

    class FailsOnce(RunJudge):
        def judge(self, answer, required_facts, claims, sources):
            if "run 2" in answer:
                raise RuntimeError("Jev is down")
            return super().judge(answer, required_facts, claims, sources)

    report = evaluate_brief_suite(
        [_case("brief-apple", [(OUTSOURCES, REACHED)])],
        RunModel(),
        FailsOnce(stated={OUTSOURCES: {1, 3, 4, 5}}),
        index,
        runs=5,
        names={},
        fact_values=lambda filing_id: [],
        log_path=None,
    )

    [case] = report.cases
    assert case.facts[0].stated_runs == 4
    assert case.passed
    assert [(e.run, e.error) for e in case.errors] == [(2, "RuntimeError: Jev is down")]


def test_a_run_whose_fact_judgment_failed_states_no_fact_and_is_listed(index):
    from edgar_eval.judge import JudgmentFailure

    class FactJudgmentFailsOnce(RunJudge):
        def judge(self, answer, required_facts, claims, sources):
            judged = super().judge(answer, required_facts, claims, sources)
            if "run 5" not in answer:
                return judged
            failure = JudgmentFailure("fact_recall", tuple(required_facts), "Timeout: slow")
            return Judgments(
                facts=(),
                claims=judged.claims,
                model=judged.model,
                requests=judged.requests,
                input_tokens=judged.input_tokens,
                failures=(failure,),
            )

    cases = [_case("brief-apple", [(OUTSOURCES, REACHED)])]

    report = _run(cases, FactJudgmentFailsOnce(stated={OUTSOURCES: {1, 2, 3, 5}}), index)

    [case] = report.cases
    assert case.facts[0].stated_runs == 3  # run 5 judged no fact
    assert not case.passed
    assert [(f.run, f.error) for f in case.judgment_failures] == [(5, "fact_recall: Timeout: slow")]


def test_a_cut_off_run_states_no_fact_by_the_harness_rule(index):
    """The Brief Suite counts a fact stated by `CaseResult.facts_stated`, so a run cut off
    at the token cap states none, even one Jev judged stated."""

    class CutOffInRun5(RunModel):
        def stream(self, messages):
            for part in super().stream(messages):
                if isinstance(part, Usage) and self.calls[messages[-1].content] == 5:
                    part = Usage(part.input_tokens, part.output_tokens, stop_reason="token_cap")
                yield part

    from edgar_eval.brief_suite import evaluate_brief_suite

    report = evaluate_brief_suite(
        [_case("brief-apple", [(OUTSOURCES, REACHED)])],
        CutOffInRun5(),
        RunJudge(stated={OUTSOURCES: {1, 2, 3, 5}}),
        index,
        runs=5,
        names={},
        fact_values=lambda filing_id: [],
        log_path=None,
        workers=1,
    )

    [case] = report.cases
    assert case.truncated_runs == (5,)
    assert case.facts[0].stated_runs == 3  # run 5 was judged stated, but was cut off
    assert not case.passed


def _suite_file(tmp_path):
    """A Brief Suite file of two made-up cases, so the command runs no drafted case."""

    def case(case_id, question, fact, reached):
        return {
            "id": case_id,
            "question": question,
            "history": [],
            "question_type": "risk",
            "starter": None,
            "expected_sources": [],
            "required_facts": [
                {
                    "fact": fact,
                    "filing_id": "X",
                    "section": "Risk Factors",
                    "tier": tier,
                    "evidence": evidence,
                }
                for fact, tier, evidence in (
                    (fact, "must_state", reached),
                    (TARIFFS, "detail", NOT_REACHED),
                )
            ],
            "expected_coverage_gaps": [],
        }

    path = tmp_path / "brief_suite.json"
    suite = {
        "version": 1,
        "cases": [
            case("brief-apple", APPLE_QUESTION, OUTSOURCES, REACHED),
            case(
                "brief-tesla", "What are the primary risk factors facing Tesla?", MUSK, MUSK_QUOTE
            ),
        ],
    }
    path.write_text(json.dumps(suite), encoding="utf-8")
    return path


MUSK = "Tesla depends on Elon Musk."
MUSK_QUOTE = "We are highly dependent on the services of Elon Musk"


def test_the_command_runs_the_brief_suite_and_reports_each_case_one_by_one(index, tmp_path):
    from edgar_eval.generation import main

    out = io.StringIO()
    path = tmp_path / "brief-suite.json"
    code = main(
        [
            *("--brief-suite", str(_suite_file(tmp_path))),
            *("--index", str(index), "--log", str(tmp_path / "log.jsonl"), "--json", str(path)),
        ],
        model=RunModel(),
        judge=RunJudge(stated={MUSK: {1, 2}}, contradicted={3}),
        fact_values=lambda filing_id: [],
        out=out,
    )

    assert code == 0
    printed = out.getvalue()
    # Five runs by default, and a verdict per case, never an average over them.
    assert "5 runs each" in printed
    assert "brief-apple: FAIL" in printed and "brief-tesla: FAIL" in printed
    assert "Contradicted Claims in run 3:" in printed
    assert f"stated in 2 of 5 runs, evidence reached in 5 of 5: {MUSK}" in printed
    assert "Fact Recall" not in printed and "overall" not in printed
    data = json.loads(path.read_text())
    assert data["runs"] == 5 and len(data["run_reports"]) == 5
    assert [c["case_id"] for c in data["cases"]] == ["brief-apple", "brief-tesla"]
    apple, tesla = data["cases"]
    assert apple["passed"] is False and [c["run"] for c in apple["contradicted"]] == [3]
    assert tesla["missed"] == [MUSK]
    assert [
        (f["tier"], f["stated_runs"], f["evidence_reached_runs"], f["passed"])
        for f in tesla["facts"]
    ] == [("must_state", 2, 5, False), ("detail", 5, 0, True)]


def test_the_command_answers_the_brief_suite_a_chosen_number_of_times(index, tmp_path):
    from edgar_eval.generation import main

    out = io.StringIO()
    main(
        [
            *("--brief-suite", str(_suite_file(tmp_path)), "--case", "brief-apple"),
            *("--runs", "3", "--index", str(index), "--log", str(tmp_path / "log.jsonl")),
        ],
        model=RunModel(),
        judge=RunJudge(),
        fact_values=lambda filing_id: [],
        out=out,
    )

    printed = out.getvalue()
    assert "1 case, 3 runs each" in printed
    assert "brief-apple: PASS" in printed and "brief-tesla" not in printed


def test_the_cost_estimate_prints_before_the_first_answer_call(index, tmp_path):
    from edgar_eval.generation import main

    out = io.StringIO()
    seen_before_first_call = []
    model = RunModel(on_first_call=lambda: seen_before_first_call.append(out.getvalue()))

    main(
        [
            *("--brief-suite", str(_suite_file(tmp_path))),
            *("--index", str(index), "--log", str(tmp_path / "log.jsonl")),
        ],
        model=model,
        judge=RunJudge(),
        fact_values=lambda filing_id: [],
        out=out,
    )

    [printed] = seen_before_first_call
    estimate = r"Estimated cost: up to \$\d+\.\d{2} for 10 Answer Calls with gpt-6-luna"
    assert re.search(estimate, printed)


def test_the_cost_estimate_prices_every_answer_call_and_its_judging():
    from edgar_eval.brief_suite import estimate_cost
    from edgar_eval.generators import generator
    from edgar_eval.judge import JEV_USD_PER_MILLION_INPUT_TOKENS

    one = estimate_cost("gpt-6-luna", answers=1, context_budget=32_000)
    fifteen = estimate_cost("gpt-6-luna", answers=15, context_budget=32_000)

    assert fifteen.total_usd == pytest.approx(15 * one.total_usd)
    price = generator("gpt-6-luna").price
    # An upper bound: at least the whole context budget is priced as input.
    assert one.answer_usd > 32_000 * price.input / 1_000_000
    assert one.judge_usd > 32_000 * JEV_USD_PER_MILLION_INPUT_TOKENS / 1_000_000
    assert estimate_cost("not-a-model", answers=1, context_budget=32_000).answer_usd is None


def test_the_golden_set_still_runs_once_and_refuses_several_runs(index, tmp_path):
    from edgar_eval.generation import main

    with pytest.raises(SystemExit):
        main(
            ["--case", "risk-aapl-tsla-jpm", "--runs", "3", "--index", str(index)],
            model=RunModel(),
            judge=RunJudge(),
            fact_values=lambda filing_id: [],
            out=io.StringIO(),
        )
