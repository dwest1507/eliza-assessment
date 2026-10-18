"""Tests of the chat API: FastAPI's test client, the real index of the shared fixture and
a fake answer model. They assert on what the browser receives: the order of the AI SDK
UI message stream, the Sources it carries, validation statuses, CORS, and that nothing
is held between requests."""

import json

import pytest
from fastapi.testclient import TestClient

from edgar_api.app import MAX_EARLIER_MESSAGE_CHARS, MAX_MESSAGE_CHARS, MAX_MESSAGES, create_app
from edgar_rag.answer_model import Usage
from edgar_rag.retrieval import HISTORY_TURNS, Message, prepare_answer_context

QUESTION = "What are the primary risk factors facing Apple, Tesla, and JPMorgan?"


class FakeModel:
    """Streams canned text and records every prompt it was sent."""

    model = "fake-model"

    def __init__(self, parts=("Apple faces ", "supply chain risk [S1].")):
        self.parts = parts
        self.received = []

    def stream(self, messages):
        self.received.append(messages)
        yield from self.parts
        yield Usage(input_tokens=1200, output_tokens=300)


class FailingModel(FakeModel):
    def stream(self, messages):
        yield "Apple faces "
        raise RuntimeError("provider went away")


@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "answer_calls.jsonl"


@pytest.fixture
def client(index, model, log_path):
    app = create_app(
        index=index, model=model, allowed_origins=["http://localhost:3000"], log_path=log_path
    )
    return TestClient(app)


def user(text):
    """A user message as the AI SDK's `useChat` sends it."""
    return {"id": "m1", "role": "user", "parts": [{"type": "text", "text": text}]}


def chat(client, *messages):
    return client.post("/api/chat", json={"id": "chat-1", "messages": list(messages)})


def events(response):
    """The stream's parts, in order: the JSON of each `data:` line, then "[DONE]"."""
    parts = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            payload = line.removeprefix("data: ")
            parts.append(payload if payload == "[DONE]" else json.loads(payload))
    return parts


def part_of(parts, type_):
    [part] = [p for p in parts if isinstance(p, dict) and p["type"] == type_]
    return part


# --- The stream --------------------------------------------------------------------------


def test_chat_streams_the_query_scope_and_sources_before_any_text(client):
    response = chat(client, user(QUESTION))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    parts = events(response)
    types = [p["type"] if isinstance(p, dict) else p for p in parts]
    assert types[0] == "start"
    assert types.index("data-query-scope") < types.index("text-start")
    assert types.index("data-sources") < types.index("text-start")
    assert types[-4:] == ["text-end", "finish-step", "finish", "[DONE]"]
    text = "".join(p["delta"] for p in parts if isinstance(p, dict) and p["type"] == "text-delta")
    assert text == "Apple faces supply chain risk [S1]."


def test_the_query_scope_names_the_companies_in_the_question(client):
    scope = part_of(events(chat(client, user(QUESTION))), "data-query-scope")["data"]

    assert [(c["ticker"], c["coverage"]) for c in scope["companies"]] == [
        ("AAPL", "tracked"),
        ("TSLA", "tracked"),
        ("JPM", "snapshot"),
    ]
    assert scope["companies"][0]["name"] == "Apple Inc"


def test_the_query_scope_carries_time_window_sections_and_metric(client):
    question = "How has Tesla's revenue changed over the last two years?"

    scope = part_of(events(chat(client, user(question))), "data-query-scope")["data"]

    assert [c["ticker"] for c in scope["companies"]] == ["TSLA"]
    assert scope["sectorPhrases"] == []
    assert scope["timeWindow"] == {"kind": "years", "count": 2, "label": "last 2 years"}
    assert scope["sections"] == []
    assert scope["metric"] == "revenue"


def test_the_query_scope_carries_the_sections_searched(client):
    question = "What legal proceedings does Apple disclose in its latest Filings?"

    scope = part_of(events(chat(client, user(question))), "data-query-scope")["data"]

    assert scope["searched"] == [
        {"ticker": "AAPL", "filingId": "AAPL_10-K_2025-09-27", "section": "Legal Proceedings"},
        {"ticker": "AAPL", "filingId": "AAPL_10-K_2025-09-27", "section": "Financial Statements"},
        {"ticker": "AAPL", "filingId": "AAPL_10-Q_2025-12-27", "section": "Legal Proceedings"},
        {"ticker": "AAPL", "filingId": "AAPL_10-Q_2025-12-27", "section": "Financial Statements"},
    ]


def test_the_query_scope_marks_a_filing_searched_whole(client):
    question = "What legal proceedings does JPMorgan disclose in its latest Filings?"

    scope = part_of(events(chat(client, user(question))), "data-query-scope")["data"]

    assert scope["searched"] == [
        {"ticker": "JPM", "filingId": "JPM_10-K_2025-12-31", "section": None}
    ]


def test_the_query_scope_carries_the_companies_a_sector_phrase_resolved_to(sector_index):
    client = TestClient(create_app(index=sector_index, model=FakeModel(), log_path=None))

    parts = events(chat(client, user("What are the main risks facing the major banks?")))

    scope = part_of(parts, "data-query-scope")["data"]
    assert [c["ticker"] for c in scope["companies"]] == ["BAC", "JPM"]
    assert scope["sectorPhrases"] == [
        {"phrase": "banks", "column": "industry", "values": ["Banks"], "tickers": ["BAC", "JPM"]}
    ]
    assert scope["timeWindow"]["label"] == "latest"
    assert scope["sections"] == ["Risk Factors"]
    assert scope["metric"] is None


def test_each_source_carries_its_tag_filing_metadata_and_passage(client, index):
    expected = prepare_answer_context([Message("user", QUESTION)], index).sources

    sources = part_of(events(chat(client, user(QUESTION))), "data-sources")["data"]["sources"]

    assert len(sources) == len(expected) > 0
    for sent, source in zip(sources, expected, strict=True):
        assert sent == {
            "tag": source.tag,
            "filingId": source.filing_id,
            "company": source.company,
            "ticker": source.ticker,
            "formType": source.form_type,
            "reportPeriod": source.report_period,
            "fiscalPeriod": source.fiscal_period,
            "section": source.section,
            "item": source.item,
            "label": source.label,
            "text": source.text,
            "kind": "text",
        }
    assert {s["ticker"] for s in sources} == {"AAPL", "TSLA", "JPM"}


def test_coverage_gaps_stream_as_a_data_part_before_any_text(client):
    question = "How has JPMorgan's revenue trended over the last three years?"

    parts = events(chat(client, user(question)))

    types = [p["type"] if isinstance(p, dict) else p for p in parts]
    assert types.index("data-sources") < types.index("data-coverage-gaps")
    assert types.index("data-coverage-gaps") < types.index("text-start")
    [gap] = part_of(parts, "data-coverage-gaps")["data"]["gaps"]
    assert gap["kind"] == "snapshot_trend"
    assert gap["label"] == "Trend unavailable"
    assert gap["companies"] == ["JPM"]
    assert gap["text"].startswith("Trend unavailable: JPMorgan Chase is a Snapshot Company.")


def test_a_question_with_no_gaps_streams_an_empty_list(client):
    parts = events(chat(client, user("What are Apple's main risk factors?")))

    assert part_of(parts, "data-coverage-gaps")["data"] == {"gaps": []}


def test_a_missing_company_streams_its_gap_and_no_sources(client):
    parts = events(chat(client, user("What are Citigroup's main risk factors?")))

    assert part_of(parts, "data-sources")["data"] == {"sources": []}
    [gap] = part_of(parts, "data-coverage-gaps")["data"]["gaps"]
    assert (gap["kind"], gap["companies"]) == ("missing_company", ["Citigroup"])


def test_a_facts_source_carries_its_filings_reported_rows(client):
    question = "How has NVIDIA's revenue changed over the last two years?"
    sources = part_of(events(chat(client, user(question))), "data-sources")["data"]["sources"]

    facts = [s for s in sources if s["kind"] == "facts"]
    assert facts and sources[: len(facts)] == facts  # sent first, as numbered
    q3 = next(s for s in facts if s["filingId"] == "NVDA_10-Q_2025-10-26")
    assert q3["section"] == "Financial Facts"
    assert q3["rows"] == [
        {
            "metric": "revenue",
            "metricName": "Revenue",
            "segment": None,
            "months": 3,
            "reportPeriod": "2025-10-26",
            "value": 57_006_000_000,
            "valueText": "$57,006 million",
            "label": "Revenue",
        }
    ]
    assert all("rows" not in s for s in sources if s["kind"] == "text")


def test_the_answer_comes_from_one_answer_call_on_the_whole_conversation(client, model):
    chat(
        client,
        user("What are Apple's main supply chain risks?"),
        {"role": "assistant", "parts": [{"type": "text", "text": "Apple relies on Asia [S1]."}]},
        user("And Tesla's?"),
    )

    [prompt] = model.received
    rendered = prompt[-1].content
    assert "Apple's main supply chain risks" in rendered  # the earlier turn, as history
    assert rendered.rstrip().endswith("And Tesla's?")


def test_a_follow_up_streams_the_query_scope_it_inherits(client):
    parts = events(
        chat(
            client,
            user(QUESTION),
            {"role": "assistant", "parts": [{"type": "text", "text": "Apple relies on Asia."}]},
            user("Which of them has the most regulatory exposure?"),
        )
    )

    scope = part_of(parts, "data-query-scope")["data"]
    assert [c["ticker"] for c in scope["companies"]] == ["AAPL", "TSLA", "JPM"]
    assert scope["sections"] == ["Risk Factors"]


EARLIER_SOURCES = [
    {"tag": "S1", "filingId": "AAPL_10-K_2025-09-27", "text": "a long passage"},
    {"tag": "S2", "filingId": "TSLA_10-K_2025-12-31", "text": "another passage"},
]


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(
            {
                "role": "assistant",
                "parts": [
                    {"type": "data-sources", "data": {"sources": EARLIER_SOURCES}},
                    {"type": "text", "text": "Apple relies on Asia [S1]; Tesla on Musk [S2]."},
                ],
            },
            id="useChat parts",
        ),
        pytest.param(
            {
                "role": "assistant",
                "content": "Apple relies on Asia [S1]; Tesla on Musk [S2].",
                "sources": {"S1": "AAPL_10-K_2025-09-27", "S2": "TSLA_10-K_2025-12-31"},
            },
            id="plain content with a sources map",
        ),
    ],
)
def test_an_earlier_answers_source_tags_reach_the_prompt_as_filing_ids(client, model, answer):
    chat(client, user(QUESTION), answer, user("Which of them is most exposed?"))

    [prompt] = model.received
    rendered = prompt[-1].content
    assert (
        "Assistant: Apple relies on Asia (AAPL_10-K_2025-09-27); "
        "Tesla on Musk (TSLA_10-K_2025-12-31)." in rendered
    )


def test_messages_with_plain_content_are_accepted_too(client):
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": QUESTION}]})

    assert response.status_code == 200
    assert part_of(events(response), "data-query-scope")["data"]["companies"]


def test_a_provider_failure_mid_answer_ends_the_stream_with_an_error_part(index, log_path):
    client = TestClient(create_app(index=index, model=FailingModel(), log_path=log_path))

    parts = events(chat(client, user(QUESTION)))

    types = [p["type"] if isinstance(p, dict) else p for p in parts]
    assert "data-sources" in types and "text-delta" in types
    error = part_of(parts, "error")
    assert "provider went away" not in error["errorText"]  # no internals leak to the browser
    assert types[-1] == "[DONE]"
    assert json.loads(log_path.read_text())["completed"] is False


def test_every_answer_call_is_logged(client, log_path):
    chat(client, user(QUESTION))

    record = json.loads(log_path.read_text())
    assert (record["model"], record["completed"]) == ("fake-model", True)


# --- Nothing is held between requests ----------------------------------------------------


def test_nothing_is_held_between_requests(client, model):
    first = events(chat(client, user("What are Apple's main supply chain risks?")))
    second = events(chat(client, user("What are the main risks?")))

    first_scope = part_of(first, "data-query-scope")["data"]["companies"]
    second_scope = part_of(second, "data-query-scope")["data"]["companies"]
    assert [c["ticker"] for c in first_scope] == ["AAPL"]
    assert second_scope == []  # Apple is not carried over from the other request
    second_prompt = model.received[1][-1].content
    assert "Apple's main supply chain risks" not in second_prompt  # nor is its question
    assert "Earlier conversation" not in second_prompt


def test_the_same_conversation_gets_the_same_sources_every_time(client):
    first = part_of(events(chat(client, user(QUESTION))), "data-sources")
    again = part_of(events(chat(client, user(QUESTION))), "data-sources")

    assert first == again


# --- Validation ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "messages",
    [
        pytest.param([user("")], id="empty latest message"),
        pytest.param([user("   \n ")], id="blank latest message"),
        pytest.param([user("x" * (MAX_MESSAGE_CHARS + 1))], id="over-long latest message"),
        pytest.param([], id="no messages"),
        pytest.param(
            [user(QUESTION), {"role": "assistant", "content": "An answer."}],
            id="latest message not from the user",
        ),
    ],
)
def test_an_unanswerable_latest_message_is_rejected_with_400(client, model, messages):
    response = client.post("/api/chat", json={"messages": messages})

    assert response.status_code == 400
    assert response.json()["detail"]
    assert model.received == []  # no Answer Call was made


def test_a_latest_message_at_the_length_cap_is_accepted(client):
    assert chat(client, user("Apple " + "x" * (MAX_MESSAGE_CHARS - 6))).status_code == 200


def turns(count, *, earlier="Apple faces supply chain risk."):
    """A conversation of `count` messages, alternating, ending with the user's question."""
    roles = ["user" if (count - i) % 2 else "assistant" for i in range(count)]
    return [{"role": role, "content": earlier} for role in roles[:-1]] + [user(QUESTION)]


def test_the_message_limit_is_the_turns_the_prompt_uses():
    # The prompt keeps the last HISTORY_TURNS messages as history, then the question.
    assert MAX_MESSAGES == HISTORY_TURNS + 1


def test_a_conversation_of_as_many_turns_as_the_prompt_uses_is_accepted(client, model):
    response = chat(client, *turns(MAX_MESSAGES))

    assert response.status_code == 200
    assert len(model.received) == 1


def test_a_conversation_of_more_turns_than_the_prompt_uses_is_rejected_with_400(client, model):
    response = chat(client, *turns(MAX_MESSAGES + 1))

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert f"{MAX_MESSAGES + 1} messages" in detail
    assert f"at most {MAX_MESSAGES}" in detail
    assert model.received == []


def test_an_earlier_message_over_the_length_cap_is_rejected_with_400(client, model):
    messages = turns(3)
    messages[1] = {"role": "assistant", "content": "x" * (MAX_EARLIER_MESSAGE_CHARS + 1)}

    response = chat(client, *messages)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "message 2" in detail.lower()
    assert f"{MAX_EARLIER_MESSAGE_CHARS:,} characters" in detail
    assert model.received == []


def test_an_earlier_message_at_the_length_cap_is_accepted(client):
    messages = turns(3)
    messages[1] = {"role": "assistant", "content": "x" * MAX_EARLIER_MESSAGE_CHARS}

    assert chat(client, *messages).status_code == 200


def test_a_malformed_body_is_rejected(client):
    assert client.post("/api/chat", json={"messages": "hello"}).status_code == 422


# --- Health and configuration -------------------------------------------------------------


def test_health_returns_status(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_only_the_configured_origins(index, model, log_path, monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000, https://app.example.com")
    client = TestClient(create_app(index=index, model=model, log_path=log_path))

    def allowed(origin):
        response = client.options(
            "/api/chat",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        return response.headers.get("access-control-allow-origin") == origin

    assert allowed("https://app.example.com")
    assert allowed("http://localhost:3000")
    assert not allowed("https://elsewhere.example.com")


def test_no_cross_origin_requests_are_allowed_unless_configured(
    index, model, log_path, monkeypatch
):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    client = TestClient(create_app(index=index, model=model, log_path=log_path))

    response = client.get("/api/health", headers={"Origin": "http://localhost:3000"})

    assert "access-control-allow-origin" not in response.headers


def test_the_answer_model_is_built_only_when_a_question_arrives(index, log_path, monkeypatch):
    built = []

    def factory():
        built.append(FakeModel())
        return built[-1]

    client = TestClient(create_app(index=index, model_factory=factory, log_path=log_path))

    assert client.get("/api/health").status_code == 200
    assert built == []
    chat(client, user(QUESTION))
    chat(client, user(QUESTION))
    assert len(built) == 1
