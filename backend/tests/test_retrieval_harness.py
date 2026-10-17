"""The retrieval harness: its pure parts (metrics, the sign test) and how it scores
Golden Set cases through the Arms."""

import json

import pytest

from edgar_eval.arms import ARMS
from edgar_eval.metrics import hit_at_k, mcnemar_exact, recall_at_k, reciprocal_rank
from edgar_eval.retrieval import Arm, evaluate, main
from edgar_rag.golden_set import ExpectedSource, GoldenCase, Message, load_golden_set
from edgar_rag.retrieval import Message as ChatMessage
from edgar_rag.retrieval import prepare_answer_context

A = ("AAPL_10-K_2025-09-27", "Risk Factors")
B = ("AAPL_10-Q_2025-12-27", "Risk Factors")
C = ("TSLA_10-K_2025-12-31", "Risk Factors")
D = ("TSLA_10-K_2025-12-31", "MD&A")
E = ("JPM_10-K_2025-12-31", "Risk Factors")

# --- Metrics -----------------------------------------------------------------------------


def test_hit_at_k_is_whether_any_expected_pair_is_in_the_top_k():
    ranked = [A, B, C, D]
    assert not hit_at_k(ranked, {C, E}, 2)
    assert hit_at_k(ranked, {C, E}, 3)
    assert hit_at_k(ranked, {C, E}, None)  # None: every Source that reaches the Answer Call
    assert not hit_at_k([A, B], {C, E}, None)


def test_recall_at_k_is_the_share_of_expected_pairs_in_the_top_k():
    ranked = [A, B, C, D, E]
    assert recall_at_k(ranked, {C, E}, 2) == 0
    assert recall_at_k(ranked, {C, E}, 3) == 0.5
    assert recall_at_k(ranked, {C, E}, None) == 1


def test_reciprocal_rank_is_one_over_the_rank_of_the_first_expected_pair():
    assert reciprocal_rank([A, B, C, D], {C, E}) == pytest.approx(1 / 3)
    assert reciprocal_rank([E, A], {C, E}) == 1
    assert reciprocal_rank([A, B], {C, E}) == 0


# --- McNemar's exact test ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("challenger_only", "shipped_only", "p"),
    [
        (0, 0, 1.0),  # no discordant case: nothing to tell apart
        (6, 0, 0.03125),  # 2 * (1/2)^6
        (0, 6, 0.03125),
        (5, 1, 0.21875),  # 2 * (1 + 6) / 64
        (3, 3, 1.0),  # capped at 1
        (10, 2, 0.03857421875),  # 2 * (1 + 12 + 66) / 4096
    ],
)
def test_mcnemar_exact_p_value_counts_only_discordant_cases(challenger_only, shipped_only, p):
    shipped = [False] * challenger_only + [True] * shipped_only + [True, False]
    challenger = [True] * challenger_only + [False] * shipped_only + [True, False]

    result = mcnemar_exact(challenger, shipped)

    assert (result.challenger_only, result.shipped_only) == (challenger_only, shipped_only)
    assert result.p_value == pytest.approx(p)


def test_mcnemar_verdict_is_ahead_behind_or_indistinguishable_at_the_5_percent_level():
    assert mcnemar_exact([True] * 6, [False] * 6).verdict == "ahead"
    assert mcnemar_exact([False] * 6, [True] * 6).verdict == "behind"
    assert mcnemar_exact([True] * 5 + [False], [False] * 5 + [True]).verdict == (
        "indistinguishable"
    )


def test_mcnemar_needs_paired_outcomes():
    with pytest.raises(ValueError):
        mcnemar_exact([True, False], [True])


# --- Scoring Golden Set cases through the Arms --------------------------------------------


def _case(case_id, question_type, expected, question="Q?", history=()):
    return GoldenCase(
        id=case_id,
        question=question,
        history=tuple(history),
        question_type=question_type,
        expected_sources=tuple(ExpectedSource(*pair) for pair in expected),
        required_facts=(),
        expected_coverage_gaps=(),
        split="dev",
        starter=None,
        tags=(),
        notes="",
    )


def _arm(name, rankings, shipped=False):
    """An Arm that returns a fixed ranking per question."""
    return Arm(
        name,
        f"fixed rankings for {name}",
        lambda messages, index, **settings: rankings[messages[-1].content],
        shipped=shipped,
    )


def test_multi_turn_cases_are_scored_on_their_final_turn():
    seen = []

    def retrieve(messages, index, **settings):
        seen.append([(m.role, m.content) for m in messages])
        return [A]

    history = [Message("user", "Risks at Apple?"), Message("assistant", "Apple's risks...")]
    case = _case("followup", "risk", [A], question="And Tesla?", history=history)

    report = evaluate([case], [Arm("fts5", "", retrieve, shipped=True)], index="unused")

    assert seen == [
        [("user", "Risks at Apple?"), ("assistant", "Apple's risks..."), ("user", "And Tesla?")]
    ]
    assert report.arms["fts5"].overall.mrr == 1


def test_scores_are_reported_overall_and_per_question_type():
    cases = [
        _case("r1", "risk", [A], question="q1"),  # found first
        _case("r2", "risk", [C, E], question="q2"),  # one of two, found third
        _case("t1", "figure_trend", [D], question="q3"),  # not found
    ]
    arm = _arm("fts5", {"q1": [A, B], "q2": [A, B, C], "q3": [A]}, shipped=True)

    scores = evaluate(cases, [arm], index="unused", ks=(1, 3), gate_k=3).arms["fts5"]

    assert scores.overall.cases == 3
    assert scores.overall.hit == {1: pytest.approx(1 / 3), 3: pytest.approx(2 / 3)}
    assert scores.overall.recall == {1: pytest.approx(1 / 3), 3: pytest.approx(0.5)}
    assert scores.overall.mrr == pytest.approx((1 + 1 / 3 + 0) / 3)
    assert scores.overall.hit_all == pytest.approx(2 / 3)  # anywhere among the Sources
    assert scores.overall.mean_sources == 2
    assert scores.by_type["risk"].hit == {1: 0.5, 3: 1.0}
    assert scores.by_type["risk"].mrr == pytest.approx((1 + 1 / 3) / 2)
    assert scores.by_type["figure_trend"].hit == {1: 0, 3: 0}


def test_cases_with_no_expected_source_are_listed_but_not_scored():
    cases = [_case("r1", "risk", [A], question="q1"), _case("ge", "stale_filing", [], "q2")]
    arm = _arm("fts5", {"q1": [A], "q2": [B]}, shipped=True)

    report = evaluate(cases, [arm], index="unused")

    assert report.unscored == ("ge",)
    assert report.arms["fts5"].overall.cases == 1
    assert "stale_filing" not in report.arms["fts5"].by_type


def test_each_challenger_is_compared_with_the_shipped_arm_on_the_gating_metric():
    cases = [_case(f"c{i}", "risk", [A], question=f"q{i}") for i in range(6)]
    shipped = _arm("fts5", {f"q{i}": [B, C, A] for i in range(6)}, shipped=True)
    better = _arm("dense", {f"q{i}": [A] for i in range(6)})
    same = _arm("hybrid", {f"q{i}": [B, A] for i in range(6)})

    report = evaluate(cases, [shipped, better, same], index="unused", gate_k=1)

    assert report.gating_metric == "hit@1"
    assert {c.arm: c.result.verdict for c in report.comparisons} == {
        "dense": "ahead",
        "hybrid": "indistinguishable",
    }


def test_exactly_one_arm_is_shipped():
    cases = [_case("r1", "risk", [A], question="q1")]
    with pytest.raises(ValueError, match="shipped"):
        evaluate(cases, [_arm("a", {"q1": [A]}), _arm("b", {"q1": [A]})], index="unused")
    with pytest.raises(ValueError, match="shipped"):
        evaluate(
            cases,
            [_arm("a", {"q1": [A]}, shipped=True), _arm("b", {"q1": [A]}, shipped=True)],
            index="unused",
        )


# --- The Arms ---------------------------------------------------------------------------


def test_the_fts5_arm_is_the_one_shipped_arm():
    assert [arm.name for arm in ARMS if arm.shipped] == ["fts5"]
    assert len({arm.name for arm in ARMS}) == len(ARMS)


def test_the_fts5_arm_ranks_the_answer_contexts_sources_taking_each_company_in_turn(index):
    # Not a risk question: the risk route gives each of these Companies a single Source.
    question = [
        ChatMessage(
            "user",
            "How do Apple, Tesla, and JPMorgan describe competition, and how do they compare?",
        )
    ]
    fts5 = next(arm for arm in ARMS if arm.name == "fts5")

    ranked = fts5.retrieve(question, index)

    sources = prepare_answer_context(question, index).sources
    assert sorted(ranked) == sorted((s.filing_id, s.section) for s in sources)
    # Each Company is retrieved with its own budget, so no Company's Sources wait
    # behind another's: the ranking takes each Company's next-best Source in turn.
    assert [filing_id.split("_")[0] for filing_id, _ in ranked[:6]] == ["AAPL", "TSLA", "JPM"] * 2


def test_the_fts5_arm_ranks_text_sources_only(index):
    """Facts Sources are not retrieved text, so they don't take ranks from the Sections
    the Golden Set labels."""
    question = [ChatMessage("user", "How has NVIDIA's revenue changed over the last two years?")]
    fts5 = next(arm for arm in ARMS if arm.name == "fts5")

    ranked = fts5.retrieve(question, index)

    sources = prepare_answer_context(question, index).sources
    assert any(s.kind == "facts" for s in sources)
    assert ranked and "Financial Facts" not in {section for _, section in ranked}
    assert sorted(ranked) == sorted((s.filing_id, s.section) for s in sources if s.kind == "text")


# --- The command line -------------------------------------------------------------------


def _first_expected_or_nothing(messages, index, **settings):
    """A fake Arm that finds every dev case's first expected pair, by its question."""
    cases = {c.question: c for c in load_golden_set().cases}
    case = cases[messages[-1].content]
    return [(s.filing_id, s.section) for s in case.expected_sources[:1]]


def test_the_command_scores_the_dev_split_by_default_and_writes_json(tmp_path, capsys, index):
    arms = [
        Arm("fts5", "shipped", _first_expected_or_nothing, shipped=True),
        Arm("nothing", "finds nothing", lambda messages, index, **settings: []),
    ]
    out = tmp_path / "retrieval-dev.json"

    assert main(["--json", str(out), "--index", str(index)], arms=arms) == 0

    dev = [c for c in load_golden_set().cases if c.split == "dev"]
    printed = capsys.readouterr().out
    assert "dev" in printed and "hit@10" in printed and "MRR" in printed
    for question_type in {c.question_type for c in dev if c.expected_sources}:
        assert question_type in printed
    assert "nothing" in printed and "behind" in printed

    report = json.loads(out.read_text())
    assert report["split"] == "dev"
    assert sorted(report["case_ids"] + report["unscored"]) == sorted(c.id for c in dev)
    assert report["arms"]["fts5"]["overall"]["mrr"] == 1
    assert report["comparisons"][0]["result"]["verdict"] == "behind"
    assert (report["chunk_tokens"], report["context_budget"]) == (600, 32_000)


def test_the_command_scores_a_chosen_context_budget_and_records_the_setting(tmp_path, index):
    budgets = []

    def retrieve(messages, index, context_budget):
        budgets.append(context_budget)
        return _first_expected_or_nothing(messages, index)

    out = tmp_path / "retrieval-dev.json"

    main(
        ["--context-budget", "9000", "--index", str(index), "--json", str(out)],
        arms=[Arm("fts5", "shipped", retrieve, shipped=True)],
    )

    assert budgets and set(budgets) == {9000}
    report = json.loads(out.read_text())
    assert (report["chunk_tokens"], report["context_budget"]) == (600, 9000)


def test_evidence_reached_counts_the_required_facts_whose_quote_reaches_the_prompt(index):
    """Whether each Required Fact's evidence quote is in the Answer Context's Sources: a
    smaller budget leaves some of the brief's risk comparison out."""
    case = next(c for c in load_golden_set().cases if c.id == "risk-aapl-tsla-jpm")
    fts5 = next(arm for arm in ARMS if arm.name == "fts5")

    full = evaluate([case], [fts5], index).arms["fts5"]
    small = evaluate([case], [fts5], index, context_budget=3_000).arms["fts5"]

    assert full.overall.facts == small.overall.facts == len(case.required_facts)
    assert full.overall.facts_reached == len(case.required_facts)
    assert 0 < small.overall.facts_reached < full.overall.facts_reached
    assert small.cases[0].facts_reached == small.overall.facts_reached
    assert small.overall.mean_source_tokens < full.overall.mean_source_tokens <= 32_000 * 1.05


def test_an_arm_measured_by_retrieval_only_reports_no_evidence():
    cases = [_case("r1", "risk", [A], question="q1")]

    scores = evaluate(cases, [_arm("fts5", {"q1": [A]}, shipped=True)], index="unused")

    assert scores.arms["fts5"].overall.facts_reached is None
    assert scores.arms["fts5"].overall.mean_source_tokens is None


def test_the_command_scores_a_chosen_split(tmp_path, index):
    arms = [Arm("fts5", "shipped", _first_expected_or_nothing, shipped=True)]
    out = tmp_path / "retrieval-holdout.json"

    main(["--split", "holdout", "--index", str(index), "--json", str(out)], arms=arms)

    holdout = {c.id for c in load_golden_set().cases if c.split == "holdout"}
    report = json.loads(out.read_text())
    assert set(report["case_ids"] + report["unscored"]) == holdout


# --- The challenger Arms -----------------------------------------------------------------


def test_the_arms_are_fts5_shipped_and_the_three_challengers_of_the_spec():
    assert {arm.name: arm.shipped for arm in ARMS} == {
        "fts5": True,
        "dense": False,
        "hybrid": False,
        "rerank": False,
    }
    assert all(arm.prepare is not None for arm in ARMS)


def test_a_seam_arm_ranks_the_sources_its_ranker_gives_the_answer_call(index):
    from edgar_eval.arms import seam_arm

    requests = []

    def make_ranker(path):
        assert path == index

        def ranker(request):
            requests.append(request)
            return list(reversed(request.eligible))

        return ranker

    arm = seam_arm("backwards", "eligible chunks in reverse id order", make_ranker)
    question = [ChatMessage("user", "What does Tesla say about Gigafactory Texas?")]

    context = arm.prepare(question, index)
    ranked = arm.retrieve(question, index)
    small = arm.prepare(question, index, context_budget=2_000)

    assert requests and {r.ticker for r in requests} == {"TSLA"}
    assert context.sources != prepare_answer_context(question, index).sources
    assert ranked == [(s.filing_id, s.section) for s in context.sources if s.kind == "text"]
    assert sum(len(s.text) for s in small.sources) < sum(len(s.text) for s in context.sources)


def test_a_version_2_run_refuses_while_any_case_is_pending(index, golden_set_v2_file, capsys):
    path = golden_set_v2_file({"risk-unh-cybersecurity": "dev", "outlook-tsla-2026": "pending"})
    arms = [Arm("fts5", "shipped", lambda messages, index, **settings: [], shipped=True)]

    with pytest.raises(SystemExit):
        main(["--golden-set", str(path), "--index", str(index)], arms=arms)

    assert "outlook-tsla-2026" in capsys.readouterr().err


def test_a_version_2_run_names_its_file_and_scores_its_recorded_split(
    index, golden_set_v2_file, tmp_path
):
    path = golden_set_v2_file(
        {"risk-unh-cybersecurity": "dev", "risk-aapl-legal-proceedings": "holdout"}
    )
    arms = [Arm("fts5", "shipped", lambda messages, index, **settings: [], shipped=True)]
    out = tmp_path / "retrieval-dev.json"

    main(["--golden-set", str(path), "--index", str(index), "--json", str(out)], arms=arms)

    report = json.loads(out.read_text())
    assert report["golden_set_version"] == 2
    assert report["case_ids"] + report["unscored"] == ["risk-unh-cybersecurity"]


def test_version_1_stays_the_default(index, tmp_path):
    arms = [Arm("fts5", "shipped", lambda messages, index, **settings: [], shipped=True)]
    out = tmp_path / "retrieval-dev.json"

    main(["--index", str(index), "--json", str(out)], arms=arms)

    assert json.loads(out.read_text())["golden_set_version"] == 1
