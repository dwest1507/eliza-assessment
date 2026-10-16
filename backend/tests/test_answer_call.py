"""Tests of the Answer Call: a fake answer model behind the protocol, the OpenAI
implementation against a fake client, and `make ask`'s command line."""

import io
import json
from types import SimpleNamespace

import pytest

from edgar_answer import ask
from edgar_answer.openai_model import OpenAIAnswerModel
from edgar_rag.answer_model import AnswerCall, Usage
from edgar_rag.retrieval import Message, PromptMessage, prepare_answer_context

QUESTION = "What are the primary risk factors facing Apple, Tesla, and JPMorgan?"


class FakeModel:
    model = "fake-model"

    def __init__(self, parts=("Apple faces ", "supply chain risk [S1].")):
        self.parts = parts
        self.received = None

    def stream(self, messages):
        self.received = messages
        yield from self.parts
        yield Usage(input_tokens=1200, output_tokens=300, reasoning_tokens=100)


@pytest.fixture
def context(index):
    return prepare_answer_context([Message("user", QUESTION)], index)


def test_an_answer_call_streams_the_answer_from_the_rendered_prompt(context, tmp_path):
    model = FakeModel()

    text = "".join(AnswerCall(context, model, log_path=tmp_path / "calls.jsonl"))

    assert text == "Apple faces supply chain risk [S1]."
    assert model.received == context.messages


def test_an_answer_call_logs_model_prompt_version_usage_and_latency(context, tmp_path):
    log = tmp_path / "logs" / "calls.jsonl"
    call = AnswerCall(context, FakeModel(), log_path=log)

    list(call)

    [line] = log.read_text().splitlines()
    record = json.loads(line)
    assert record["model"] == "fake-model"
    assert record["prompt_version"] == "v1"
    assert (record["input_tokens"], record["output_tokens"], record["reasoning_tokens"]) == (
        1200,
        300,
        100,
    )
    assert record["latency_s"] >= 0
    assert 0 <= record["first_token_s"] <= record["latency_s"]
    assert record["sources"] == len(context.sources)
    assert record["completed"] is True
    assert call.record.output_tokens == 300


def test_an_answer_call_stopped_early_is_logged_as_incomplete(context, tmp_path):
    log = tmp_path / "calls.jsonl"
    stream = iter(AnswerCall(context, FakeModel(), log_path=log))

    next(stream)
    stream.close()

    record = json.loads(log.read_text())
    assert record["completed"] is False
    assert record["output_tokens"] is None


# --- The OpenAI implementation ----------------------------------------------------------


class FakeOpenAIClient:
    """Stands in for `openai.OpenAI`: records the request, streams canned chunks."""

    def __init__(self):
        self.request = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.request = request

        def chunk(content=None, usage=None):
            delta = SimpleNamespace(content=content)
            choices = [] if content is None else [SimpleNamespace(delta=delta)]
            return SimpleNamespace(choices=choices, usage=usage)

        return iter(
            [
                chunk(""),
                chunk("Apple "),
                chunk("faces risk [S1]."),
                chunk(
                    usage=SimpleNamespace(
                        prompt_tokens=900,
                        completion_tokens=420,
                        completion_tokens_details=SimpleNamespace(reasoning_tokens=64),
                    )
                ),
            ]
        )


def test_openai_model_defaults_to_gpt_6_luna_with_low_reasoning_and_a_token_cap(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    client = FakeOpenAIClient()
    model = OpenAIAnswerModel(client=client)

    parts = list(model.stream([PromptMessage("system", "rules"), PromptMessage("user", "q")]))

    assert model.model == "gpt-6-luna"
    assert parts == ["Apple ", "faces risk [S1].", Usage(900, 420, 64)]
    assert client.request == {
        "model": "gpt-6-luna",
        "messages": [{"role": "system", "content": "rules"}, {"role": "user", "content": "q"}],
        "reasoning_effort": "low",
        "max_completion_tokens": 2500,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def test_openai_model_is_overridden_by_the_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    client = FakeOpenAIClient()

    list(OpenAIAnswerModel(client=client).stream([PromptMessage("user", "q")]))

    assert client.request["model"] == "gpt-6.1-sol"


def test_an_empty_model_variable_keeps_the_default(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "")

    assert OpenAIAnswerModel(client=FakeOpenAIClient()).model == "gpt-6-luna"


# --- make ask --------------------------------------------------------------------------


def test_ask_prints_the_query_scope_the_sources_and_the_streamed_answer(index, tmp_path):
    out = io.StringIO()

    ask.main(
        [QUESTION, "--index", str(index)],
        model=FakeModel(),
        out=out,
        log_path=tmp_path / "calls.jsonl",
    )

    printed = out.getvalue()
    scope, rest = printed.split("\nSources", 1)
    assert "Apple Inc (AAPL, tracked)" in scope
    assert "JPMorgan Chase & Co (JPM, snapshot)" in scope
    assert "[S1] AAPL " in rest
    sources, answer = rest.split("\nAnswer\n", 1)
    assert "TSLA " in sources and "JPM " in sources
    assert "Apple faces supply chain risk [S1]." in answer
    assert "fake-model · prompt v1 · 1200 input / 300 output tokens" in answer
