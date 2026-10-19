"""The retrieval harness: its pure parts (metrics, the sign test) and how it scores
Golden Set cases through the Arms."""

import io
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from edgar_eval.arms import ARMS
from edgar_eval.metrics import hit_at_k, mcnemar_exact, recall_at_k, reciprocal_rank
from edgar_eval.retrieval import Arm, evaluate, main, print_report, print_screen
from edgar_rag.golden_set import (
    GOLDEN_SET_V1,
    ExpectedSource,
    GoldenCase,
    Message,
    RequiredFact,
    load_golden_set,
)
from edgar_rag.retrieval import Message as ChatMessage
from edgar_rag.retrieval import SearchedPlace, prepare_answer_context

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


def _case(case_id, question_type, expected, question="Q?", history=(), facts=()):
    return GoldenCase(
        id=case_id,
        question=question,
        history=tuple(history),
        question_type=question_type,
        expected_sources=tuple(ExpectedSource(*pair) for pair in expected),
        required_facts=tuple(RequiredFact(f"Fact: {quote}", *A, quote) for quote in facts),
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


def _context(*sources):
    """A fake Answer Context of these Sources, searched in each one's Section."""
    searched = tuple(SearchedPlace(s.ticker, s.filing_id, s.section) for s in sources)
    return SimpleNamespace(sources=sources, query_scope=SimpleNamespace(searched=searched))


def _evidence_arm(name, reached, shipped=False, padding=0, query_api_call=False):
    """An Arm that prepares an Answer Context whose one Source, Apple's Risk Factors,
    holds the evidence quotes `reached[question]` (and `padding` words of other text)."""

    def prepare(messages, index, **settings):
        quotes = reached[messages[-1].content]
        text = " ".join([*quotes, *["filler"] * padding])
        source = SimpleNamespace(
            kind="text", ticker="AAPL", filing_id=A[0], section=A[1], text=text
        )
        return _context(source)

    def retrieve(messages, index, **settings):
        return [A]

    return Arm(
        name,
        f"fixed evidence for {name}",
        retrieve,
        shipped=shipped,
        prepare=prepare,
        query_api_call=query_api_call,
    )


def _two_fact_cases(n):
    """`n` cases of two Required Facts each, "first i" and "second i"."""
    return [
        _case(f"c{i}", "risk", [A], question=f"q{i}", facts=(f"first {i}", f"second {i}"))
        for i in range(n)
    ]


def test_evidence_reached_is_recorded_per_fact_and_gates_each_challenger():
    """The gate pairs the Arms fact by fact, one-sided: 4 facts gained and none lost is
    ahead (p = 0.0625 < 0.10), 3 lost and none gained is behind (p = 0.125 < 0.20), though
    neither would be at two-sided p < 0.05."""
    cases = _two_fact_cases(6)
    firsts = {f"q{i}": [f"first {i}"] for i in range(6)}
    shipped = _evidence_arm("fts5", firsts, shipped=True)
    gains = _evidence_arm(
        "dense", {f"q{i}": [f"first {i}"] + ([f"second {i}"] if i < 4 else []) for i in range(6)}
    )
    loses = _evidence_arm("hybrid", {f"q{i}": [] if i < 3 else [f"first {i}"] for i in range(6)})
    same = _evidence_arm("rerank", firsts)

    report = evaluate(cases, [shipped, gains, loses, same], index="unused")

    assert report.arms["dense"].cases[0].evidence_reached == (True, True)
    assert report.arms["dense"].cases[5].evidence_reached == (True, False)
    assert report.arms["hybrid"].cases[0].evidence_reached == (False, False)
    saved = json.loads(json.dumps(report.to_dict()))
    assert saved["arms"]["fts5"]["cases"][0]["evidence_reached"] == [True, False]
    assert report.gating_metric == "evidence reached"
    gate = {c.arm: c for c in report.comparisons}
    assert {arm: c.verdict for arm, c in gate.items()} == {
        "dense": "ahead",
        "hybrid": "behind",
        "rerank": "indistinguishable",
    }
    assert gate["dense"].facts == 12
    assert (gate["dense"].result.challenger_only, gate["dense"].result.shipped_only) == (4, 0)
    assert gate["dense"].result.p_ahead == pytest.approx(0.0625)
    assert gate["hybrid"].result.p_behind == pytest.approx(0.125)


def _reaching(first, second):
    """Evidence per question: the first fact of cases `first`, the second of `second`."""
    return {
        f"q{i}": ([f"first {i}"] if i in first else []) + ([f"second {i}"] if i in second else [])
        for i in range(6)
    }


ALL, NONE = range(6), ()


def test_the_screen_drops_a_candidate_behind_on_evidence_reached():
    cases = _two_fact_cases(6)
    shipped = _evidence_arm("fts5", _reaching(ALL, NONE), shipped=True)
    behind = _evidence_arm("dense", _reaching(range(3, 6), NONE))  # 3 lost: p behind 0.125
    level = _evidence_arm("hybrid", _reaching(range(1, 6), [0]))  # 1 lost, 1 gained

    result = evaluate(cases, [shipped, behind, level], index="unused").screen

    assert result.shipped == "fts5"
    assert result.kept == ("hybrid",)
    screened = {c.name: c for c in result.candidates}
    assert list(screened) == ["dense", "hybrid"]  # every candidate, in the order given
    assert not screened["dense"].kept and "behind" in screened["dense"].reason
    assert (screened["dense"].lost, screened["dense"].gained) == (3, 0)
    assert screened["dense"].p_behind == pytest.approx(0.125)
    assert screened["hybrid"].kept and screened["hybrid"].reason.startswith("kept")


def test_the_screen_keeps_the_top_three_of_five_ties_going_to_the_cheapest():
    """Five candidates pass; the most Evidence Reached go on, and among equals the one
    with the fewest Source tokens (the Answer Call's input), then the earliest listed."""
    cases = _two_fact_cases(6)
    shipped = _evidence_arm("fts5", _reaching(ALL, NONE), shipped=True)
    candidates = [
        _evidence_arm("most", _reaching(ALL, ALL)),  # 12 of 12
        _evidence_arm("dearer", _reaching(ALL, range(4)), padding=400),  # 10 of 12
        _evidence_arm("cheaper", _reaching(ALL, range(4))),  # 10 of 12
        _evidence_arm("cheaper-later", _reaching(ALL, range(4))),  # 10 of 12, listed later
        _evidence_arm("level", _reaching(ALL, NONE)),  # 6 of 12, the shipped Arm's
    ]

    report = evaluate(cases, [shipped, *candidates], index="unused")

    assert report.screen.kept == ("most", "cheaper", "cheaper-later")
    screened = {c.name: c for c in report.screen.candidates}
    assert [screened[name].kept for name in screened] == [True, False, True, True, False]
    assert screened["dearer"].reason.startswith("dropped: not behind")
    assert screened["dearer"].mean_source_tokens > screened["cheaper"].mean_source_tokens
    assert (screened["most"].facts_reached, screened["level"].facts_reached) == (12, 6)

    printed = io.StringIO()
    print_screen(report.screen, printed)
    printed = printed.getvalue()
    for name in screened:  # every candidate screened, and why
        assert f"{name}: " in printed
    assert "Go on: most, cheaper, cheaper-later" in printed


def test_the_screen_never_sends_an_arm_that_makes_an_api_call_to_a_paid_run():
    """The one-call rule (2026-10-17): an Arm that makes an API call at query time, such
    as a hosted embedding of the question, can't ship. It is still scored and gated,
    unconstrained, and labelled as available if the one-call limit is lifted."""
    cases = _two_fact_cases(6)
    shipped = _evidence_arm("fts5", _reaching(ALL, NONE), shipped=True)
    hosted = _evidence_arm("hosted", _reaching(ALL, ALL), query_api_call=True)  # far ahead
    local = _evidence_arm("local", _reaching(ALL, NONE))

    report = evaluate(cases, [shipped, hosted, local], index="unused")

    assert report.screen.kept == ("local",)
    screened = {c.name: c for c in report.screen.candidates}
    assert not screened["hosted"].kept and not screened["hosted"].shippable
    assert "available if the one-call limit is lifted" in screened["hosted"].reason
    assert screened["hosted"].gained == 6  # its scores are still shown, unconstrained
    assert screened["local"].shippable
    gate = {c.arm: c for c in report.comparisons}
    assert gate["hosted"].verdict == "ahead"
    saved = json.loads(json.dumps(report.to_dict()))
    assert saved["arms"]["hosted"]["query_api_call"] is True
    assert saved["arms"]["hosted"]["shippable"] is False
    assert saved["arms"]["local"]["shippable"] is True

    printed = io.StringIO()
    print_screen(report.screen, printed)
    assert "available if the one-call limit is lifted" in printed.getvalue()


def test_an_arm_that_makes_an_api_call_does_not_take_a_place_in_the_screen():
    cases = _two_fact_cases(6)
    shipped = _evidence_arm("fts5", _reaching(ALL, NONE), shipped=True)
    hosted = [_evidence_arm(f"hosted-{n}", _reaching(ALL, ALL), query_api_call=True) for n in "abc"]
    local = [_evidence_arm(f"local-{n}", _reaching(ALL, NONE)) for n in "abc"]

    report = evaluate(cases, [shipped, *hosted, *local], index="unused")

    assert report.screen.kept == ("local-a", "local-b", "local-c")


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

    scores = evaluate(cases, [arm], index="unused", ks=(1, 3)).arms["fts5"]

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


def _every_fact_in_the_first_expected_source(messages, index, **settings):
    """A fake Arm's Answer Context: the first expected Section of the dev case, holding
    every Required Fact's evidence quote."""
    case = {c.question: c for c in load_golden_set().cases}[messages[-1].content]
    sources = tuple(
        SimpleNamespace(
            kind="text",
            ticker=s.filing_id.split("_")[0],
            filing_id=s.filing_id,
            section=s.section,
            text=" ".join(f.evidence for f in case.required_facts),
        )
        for s in case.expected_sources[:1]
    )
    return _context(*sources)


def test_the_command_scores_the_dev_split_by_default_and_writes_json(tmp_path, capsys, index):
    arms = [
        Arm(
            "fts5",
            "shipped",
            _first_expected_or_nothing,
            shipped=True,
            prepare=_every_fact_in_the_first_expected_source,
        ),
        Arm(
            "nothing",
            "finds nothing",
            lambda messages, index, **settings: [],
            prepare=lambda messages, index, **settings: _context(),
        ),
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
    shipped = report["arms"]["fts5"]["overall"]
    assert shipped["mrr"] == 1  # hit@k, recall@k and MRR are still reported
    assert shipped["hit"]["10"] == 1 and 0 < shipped["recall"]["10"] < 1
    assert report["arms"]["nothing"]["overall"]["hit"]["10"] == 0
    assert report["gating_metric"] == "evidence reached"
    assert report["comparisons"][0]["verdict"] == "behind"
    assert report["screen"]["kept"] == []
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
    case = next(c for c in load_golden_set(GOLDEN_SET_V1).cases if c.id == "risk-aapl-tsla-jpm")
    fts5 = next(arm for arm in ARMS if arm.name == "fts5")

    full = evaluate([case], [fts5], index).arms["fts5"]
    small = evaluate([case], [fts5], index, context_budget=3_000).arms["fts5"]

    assert full.overall.facts == small.overall.facts == len(case.required_facts)
    assert full.overall.facts_reached == len(case.required_facts)
    assert 0 < small.overall.facts_reached < full.overall.facts_reached
    assert small.cases[0].facts_reached == small.overall.facts_reached
    assert small.overall.mean_source_tokens < full.overall.mean_source_tokens <= 32_000 * 1.05


def test_each_unreached_fact_records_its_section_and_whether_it_was_searched(capsys):
    """A fact whose Section was not searched for its Filing is a planning miss; one whose
    Section was searched (or whose Filing was searched whole) is a ranking miss. The
    printout groups the must-state misses; a detail is recorded but not grouped."""
    q10 = "AAPL_10-Q_2025-12-27"
    facts = (
        RequiredFact("Reached.", *A, "reached quote"),
        RequiredFact("Ranked out.", *A, "missing one"),
        RequiredFact("Not planned.", A[0], "MD&A", "missing two"),
        RequiredFact("Searched whole.", q10, "MD&A", "missing three"),
        RequiredFact("A detail.", A[0], "Legal Proceedings", "missing four", tier="detail"),
    )
    case = replace(_case("c1", "risk", [A], question="q1"), required_facts=facts)

    def prepare(messages, index, **settings):
        source = SimpleNamespace(
            kind="text", ticker="AAPL", filing_id=A[0], section=A[1], text="the reached quote"
        )
        searched = (SearchedPlace("AAPL", A[0], "Risk Factors"), SearchedPlace("AAPL", q10, None))
        return SimpleNamespace(sources=(source,), query_scope=SimpleNamespace(searched=searched))

    arm = Arm("fts5", "", lambda m, i, **s: [A], shipped=True, prepare=prepare)
    report = evaluate([case], [arm], index="unused")

    [scored] = report.arms["fts5"].cases
    assert [(u.fact, u.tier, u.filing_id, u.section, u.searched) for u in scored.unreached] == [
        (1, "must_state", *A, True),
        (2, "must_state", A[0], "MD&A", False),
        (3, "must_state", q10, "MD&A", True),
        (4, "detail", A[0], "Legal Proceedings", False),
    ]
    saved = json.loads(json.dumps(report.to_dict()))["arms"]["fts5"]["cases"][0]
    assert saved["unreached"][1] == {
        "fact": 2,
        "tier": "must_state",
        "filing_id": A[0],
        "section": "MD&A",
        "searched": False,
    }

    out = io.StringIO()
    print_report(report, "dev", out)
    printed = out.getvalue()
    assert "Planning misses (must-state, Section not searched): 1 (c1: 1)" in printed
    assert "Ranking misses (must-state, Section searched): 2 (c1: 2)" in printed


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


def test_the_arms_are_fts5_shipped_and_the_challengers():
    assert {arm.name: arm.shipped for arm in ARMS} == {
        "fts5": True,
        "dense": False,
        "hybrid": False,
        "rerank": False,
        "dense-local": False,
        "hybrid-local": False,
    }
    assert all(arm.prepare is not None for arm in ARMS)


def test_every_arm_records_whether_it_makes_an_api_call_at_query_time():
    """One API call per question, the Answer Call (2026-10-17): the hosted embedding
    Arms embed each question with OpenAI, so they can't ship; local models are fine."""
    assert {arm.name: arm.query_api_call for arm in ARMS} == {
        "fts5": False,
        "dense": True,
        "hybrid": True,
        "rerank": False,
        "dense-local": False,
        "hybrid-local": False,
    }
    assert all(arm.shippable is not arm.query_api_call for arm in ARMS)


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


def test_version_2_is_the_default_and_version_1_runs_by_naming_its_file(index, tmp_path):
    from edgar_rag.golden_set import GOLDEN_SET_V1, load_golden_set

    arms = [Arm("fts5", "shipped", lambda messages, index, **settings: [], shipped=True)]
    default, version_1 = tmp_path / "retrieval-dev.json", tmp_path / "retrieval-dev-v1.json"

    main(["--index", str(index), "--json", str(default)], arms=arms)
    main(
        ["--golden-set", str(GOLDEN_SET_V1), "--index", str(index), "--json", str(version_1)],
        arms=arms,
    )

    report = json.loads(default.read_text())
    assert report["golden_set_version"] == 2
    assert len(report["case_ids"] + report["unscored"]) == 60
    report = json.loads(version_1.read_text())
    assert report["golden_set_version"] == 1
    assert len(report["case_ids"] + report["unscored"]) == len(
        load_golden_set(GOLDEN_SET_V1).split("dev")
    )
