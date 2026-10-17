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
    assert record["prompt_version"] == "v7"
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


# --- The Anthropic implementation -------------------------------------------------------


class FakeAnthropicClient:
    """Stands in for `anthropic.Anthropic`: records the request, streams canned text."""

    def __init__(self, stop_reason="end_turn"):
        self.request = None
        self.stop_reason = stop_reason
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **request):
        self.request = request
        message = SimpleNamespace(
            stop_reason=self.stop_reason,
            stop_details=SimpleNamespace(category="cyber")
            if self.stop_reason == "refusal"
            else None,
            usage=SimpleNamespace(
                input_tokens=900,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                output_tokens=420,
                output_tokens_details=SimpleNamespace(thinking_tokens=64),
            ),
        )

        class Stream:
            text_stream = iter(["Apple ", "faces risk [S1]."])

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_final_message(self):
                return message

        return Stream()


def test_anthropic_model_streams_with_the_same_effort_and_token_cap_as_openai():
    from edgar_answer.anthropic_model import AnthropicAnswerModel

    client = FakeAnthropicClient()
    model = AnthropicAnswerModel("claude-sonnet-5-5", client=client)

    parts = list(model.stream([PromptMessage("system", "rules"), PromptMessage("user", "q")]))

    assert model.model == "claude-sonnet-5-5"
    assert parts == ["Apple ", "faces risk [S1].", Usage(900, 420, 64)]
    assert client.request == {
        "model": "claude-sonnet-5-5",
        "system": "rules",
        "messages": [{"role": "user", "content": "q"}],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "low"},
        "max_tokens": 2500,
    }


def test_anthropic_model_raises_when_the_model_declines_to_answer():
    from edgar_answer.anthropic_model import AnswerRefused, AnthropicAnswerModel

    model = AnthropicAnswerModel("claude-opus-5-5", client=FakeAnthropicClient("refusal"))

    with pytest.raises(AnswerRefused, match="cyber"):
        list(model.stream([PromptMessage("user", "q")]))


def test_the_anthropic_keys_placeholder_is_in_the_backends_env_example():
    import re
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / ".env.example"
    assert re.search(r"^ANTHROPIC_API_KEY=your-", example.read_text(), re.M)


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
    assert "Time window: latest" in scope
    assert "Sections: Risk Factors" in scope
    assert "Metrics: none" in scope
    assert "AAPL: AAPL_10-K_2025-09-27 (FY2025), AAPL_10-Q_2025-12-27 (Q1 FY2026)" in scope
    assert "[S1] AAPL " in rest
    sources, answer = rest.split("\nAnswer\n", 1)
    assert "TSLA " in sources and "JPM " in sources
    assert "Apple faces supply chain risk [S1]." in answer
    assert "fake-model · prompt v7 · 1200 input / 300 output tokens" in answer


def test_ask_prints_a_named_period_and_the_change_route(index, tmp_path):
    out = io.StringIO()

    ask.main(
        ["How have Apple's risk factors changed since fiscal 2024?", "--index", str(index)],
        model=FakeModel(),
        out=out,
        log_path=tmp_path / "calls.jsonl",
    )

    scope = out.getvalue().split("\nSources", 1)[0]
    assert "Named periods: FY2024" in scope
    assert "Change question: new paragraphs first" in scope


def test_ask_prints_the_companies_a_sector_phrase_resolved_to(sector_index, tmp_path):
    out = io.StringIO()

    ask.main(
        ["How has revenue changed at the major banks?", "--index", str(sector_index)],
        model=FakeModel(),
        out=out,
        log_path=tmp_path / "calls.jsonl",
    )

    scope = out.getvalue().split("\nSources", 1)[0]
    assert 'Sector phrase: "banks" → BAC, JPM (industry: Banks)' in scope
    assert "Metrics: revenue" in scope


def test_ask_prints_the_coverage_gaps_before_the_answer(index, tmp_path):
    out = io.StringIO()

    ask.main(
        ["Compare the risk factors of JPMorgan and Wells Fargo.", "--index", str(index)],
        model=FakeModel(),
        out=out,
        log_path=tmp_path / "calls.jsonl",
    )

    before_answer = out.getvalue().split("\nAnswer\n", 1)[0]
    gaps = before_answer.split("\nCoverage Gaps (1)\n", 1)[1]
    assert (
        "  Not in the Corpus: Wells Fargo is not in the Filings provided, so this answer "
        "does not cover it." in gaps
    )


def test_ask_says_when_there_are_no_coverage_gaps(index, tmp_path):
    out = io.StringIO()

    ask.main(
        ["What are Apple's main risk factors?", "--index", str(index)],
        model=FakeModel(),
        out=out,
        log_path=tmp_path / "calls.jsonl",
    )

    assert "\nCoverage Gaps (0)\n  none\n" in out.getvalue()


def test_ask_prints_the_financial_facts_and_what_falls_back_to_text(index, tmp_path):
    out = io.StringIO()

    ask.main(
        [
            "Compare the revenue of NVIDIA and JPMorgan over the last year.",
            "--index",
            str(index),
        ],
        model=FakeModel(),
        out=out,
        log_path=tmp_path / "calls.jsonl",
    )

    printed = out.getvalue()
    facts = printed.split("\nFinancial Facts", 1)[1].split("\nSources", 1)[0]
    assert "NVDA Revenue Q3 FY2026 (3 months ended 2025-10-26): $57,006 million" in facts
    assert "derived" in facts
    assert "JPMorgan Chase & Co (JPM) is a Snapshot Company" in facts
    assert "Metrics: revenue" in printed
