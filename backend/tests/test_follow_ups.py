"""Follow-up questions, through the retrieval seam: each part of the Query Scope the latest
user message does not name is inherited from the most recent earlier user message that
named it, and a part it names replaces the inherited one (ADR 0003)."""

import pytest

from edgar_rag.corpus import load_corpus
from edgar_rag.retrieval import (
    HISTORY_MAX_TOKENS,
    Message,
    build_index,
    count_tokens,
    prepare_answer_context,
)

BRIEF_QUESTION = (
    "What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"
)
BRIEF_ANSWER = (
    "Apple depends on outsourcing partners in Asia [S1]. Tesla depends on Elon Musk [S2]. "
    "JPMorgan faces legal and regulatory risk [S3]."
)


def _follow_up(index, *turns):
    """The Answer Context of the last of `turns`, alternating user and assistant."""
    messages = [Message("assistant" if i % 2 else "user", t) for i, t in enumerate(turns)]
    return prepare_answer_context(messages, index)


def _tickers(context):
    return [c.ticker for c in context.query_scope.companies]


def test_a_follow_up_naming_no_company_keeps_the_companies_and_their_risk_factors(index):
    context = _follow_up(
        index, BRIEF_QUESTION, BRIEF_ANSWER, "Which of them has the most regulatory exposure?"
    )

    assert _tickers(context) == ["AAPL", "TSLA", "JPM"]
    assert context.query_scope.sections == ("Risk Factors",)
    assert context.query_scope.time_window.label == "latest"
    pairs = {(s.filing_id, s.section) for s in context.sources}
    assert {
        ("AAPL_10-K_2025-09-27", "Risk Factors"),
        ("TSLA_10-K_2025-12-31", "Risk Factors"),
        ("JPM_10-K_2025-12-31", "Risk Factors"),
    } <= pairs
    assert {section for _, section in pairs} == {"Risk Factors"}


@pytest.fixture(scope="module")
def switch_index(tmp_path_factory):
    """NVIDIA and Microsoft, both Tracked Companies with Financial Facts."""
    filings = [f for f in load_corpus() if f.ticker in {"NVDA", "MSFT"}]
    return build_index(filings, tmp_path_factory.mktemp("switch_index") / "edgar_rag.sqlite")


def test_a_follow_up_naming_a_new_company_switches_to_it_and_keeps_the_rest(switch_index):
    first = _follow_up(switch_index, "How has NVIDIA's revenue changed over the last two years?")
    context = _follow_up(
        switch_index,
        "How has NVIDIA's revenue changed over the last two years?",
        "NVIDIA's revenue grew from $60,922 million in FY2024 [S4] to $130,497 million [S8].",
        "And what about Microsoft?",
    )

    scope = context.query_scope
    assert _tickers(context) == ["MSFT"]
    assert scope.time_window == first.query_scope.time_window
    assert scope.time_window.label == "last 2 years"
    assert scope.metric == "revenue"
    assert scope.change == first.query_scope.change
    assert {s.ticker for s in context.sources} == {"MSFT"}
    assert {r.ticker for r in context.financial_facts} == {"MSFT"}
    assert any(s.kind == "text" for s in context.sources)


def test_a_follow_up_after_an_outlook_question_inherits_the_latest_mdna(switch_index):
    context = _follow_up(
        switch_index,
        "What is NVIDIA's outlook for its Data Center business?",
        "NVIDIA expects demand for its data center platforms to continue [S1].",
        "And what about Microsoft?",
    )

    scope = context.query_scope
    assert _tickers(context) == ["MSFT"]
    assert scope.sections == ("MD&A",)
    assert scope.time_window.label == "latest"
    latest = ["MSFT_10-K_2025-06-30", "MSFT_10-Q_2025-09-30", "MSFT_10-Q_2025-12-31"]
    assert [f.filing_id for f in scope.filings] == latest
    text = [s for s in context.sources if s.kind == "text"]
    assert text
    assert {s.section for s in text} == {"MD&A"}
    assert {s.filing_id for s in text} <= set(latest)
    assert [(g.kind, g.companies) for g in context.coverage_gaps] == [("no_guidance", ("MSFT",))]


def test_a_follow_up_naming_a_time_window_keeps_the_companies_and_replaces_the_window(index):
    context = _follow_up(
        index,
        "What are Tesla's main risk factors?",
        "Tesla depends on Elon Musk [S1].",
        "How did that change over the last two years?",
    )

    scope = context.query_scope
    assert _tickers(context) == ["TSLA"]
    assert scope.sections == ("Risk Factors",)
    assert scope.time_window.label == "last 2 years"
    assert scope.change
    assert {s.section for s in context.sources} == {"Risk Factors"}
    assert {s.filing_id for s in context.sources} & {"TSLA_10-Q_2025-03-31", "TSLA_10-Q_2025-06-30"}


def test_each_part_comes_from_the_most_recent_message_that_named_it(index):
    context = _follow_up(
        index,
        "What are Apple's risk factors?",
        "Apple outsources manufacturing [S1].",
        "How has NVIDIA's revenue changed over the last two years?",
        "NVIDIA's revenue grew [S1].",
        "And Tesla's net income?",
    )

    scope = context.query_scope
    assert _tickers(context) == ["TSLA"]
    assert scope.metric == "net_income"
    assert scope.time_window.label == "last 2 years"
    assert scope.sections == ("Risk Factors",)


def test_a_follow_up_naming_a_missing_company_drops_the_earlier_ones(gap_index):
    context = _follow_up(
        gap_index,
        "How has General Electric performed recently?",
        "The only General Electric Filing is GE Capital's 10-K for 2014.",
        "What about Honeywell?",
    )

    assert _tickers(context) == []
    assert context.query_scope.missing_companies == ("Honeywell",)
    assert context.sources == ()
    assert [g.kind for g in context.coverage_gaps] == ["missing_company"]


def test_a_change_of_topic_that_names_no_company_still_inherits_the_companies(index):
    """The known weakness of ADR 0003, measured by a Golden Set case."""
    context = _follow_up(
        index,
        "What are Apple's main risk factors?",
        "Apple outsources manufacturing [S1].",
        "Which companies took charges because of new U.S. export controls?",
    )

    assert _tickers(context) == ["AAPL"]
    assert {s.ticker for s in context.sources} == {"AAPL"}


# --- History in the prompt ---------------------------------------------------------------


def _earlier(context):
    """The earlier-conversation block of the prompt."""
    user = context.messages[1].content
    return user.split("# Earlier conversation (context only, not evidence)\n\n")[1].split(
        "\n\n# Question"
    )[0]


def test_earlier_source_tags_are_rewritten_as_the_filing_ids_they_cited(index):
    conversation = [
        Message("user", BRIEF_QUESTION),
        Message(
            "assistant",
            "Apple outsources manufacturing [S1][S2]. Tesla depends on Elon Musk [S3, S1]. "
            "JPMorgan faces regulatory risk [S9].",
            sources={
                "S1": "AAPL_10-K_2025-09-27",
                "S2": "AAPL_10-Q_2025-12-27",
                "S3": "TSLA_10-K_2025-12-31",
            },
        ),
        Message("user", "Which of them has the most regulatory exposure?"),
    ]

    earlier = _earlier(prepare_answer_context(conversation, index))

    assert earlier == (
        f"User: {BRIEF_QUESTION}\n\n"
        "Assistant: Apple outsources manufacturing (AAPL_10-K_2025-09-27; "
        "AAPL_10-Q_2025-12-27). Tesla depends on Elon Musk (TSLA_10-K_2025-12-31; "
        "AAPL_10-K_2025-09-27). JPMorgan faces regulatory risk."
    )


def test_history_is_the_last_ten_turns(index):
    turns = []
    for n in range(1, 8):
        turns += [f"Question {n} about Apple's risk factors?", f"Answer {n}."]
    context = _follow_up(index, *turns, "Which risk is the largest?")

    earlier = _earlier(context)
    assert earlier.startswith("User: Question 3 about")
    assert earlier.count("User: ") == 5 and earlier.count("Assistant: ") == 5
    assert earlier.endswith("Assistant: Answer 7.")


def test_history_drops_its_oldest_turns_to_fit_the_token_cap(index):
    long_answer = "Apple outsources its manufacturing to partners in Asia. " * 500
    context = _follow_up(
        index,
        "What are Apple's risk factors?",
        long_answer,
        "And its legal proceedings?",
        "Apple is party to several lawsuits.",
        "Which is the largest?",
    )

    earlier = _earlier(context)
    assert count_tokens(earlier) <= HISTORY_MAX_TOKENS
    assert earlier == (
        "User: And its legal proceedings?\n\nAssistant: Apple is party to several lawsuits."
    )


def test_a_follow_up_naming_a_new_sector_phrase_switches_to_its_companies(sector_index):
    context = _follow_up(
        sector_index,
        "What regulatory risks do the major pharmaceutical companies face?",
        "They describe drug pricing pressure [S1].",
        "And the major banks?",
    )

    assert sorted(_tickers(context)) == ["BAC", "JPM"]
    assert [p.phrase for p in context.query_scope.sector_phrases] == ["banks"]
    assert context.query_scope.sections == ("Risk Factors",)
    assert {s.ticker for s in context.sources} == {"BAC", "JPM"}
