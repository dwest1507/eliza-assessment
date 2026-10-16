"""The Anthropic implementation of the answer model (ADR 0004), over the official SDK.

Streams a Message with adaptive thinking at effort `low` and a token cap of 2,500, which
covers the thinking and a 300–600 word answer: the same settings as the OpenAI
implementation's reasoning effort `low` and completion-token cap, so the generator
comparison measures the models rather than their settings. The thinking is not shown
(the API's default display omits it) and counts in the output tokens. The SDK reads the
key from `ANTHROPIC_API_KEY`.

No refusal fallback is configured: a fallback would answer with a different model, and
the comparison would no longer measure the one it names. A refused answer raises
instead, so the harness reports the case as not answered.

It lives outside the core package, which stays on the standard library.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from edgar_rag.answer_model import Usage
from edgar_rag.retrieval import PromptMessage

__all__ = ["EFFORT", "MAX_TOKENS", "AnswerRefused", "AnthropicAnswerModel"]

EFFORT = "low"
MAX_TOKENS = 2_500


class AnswerRefused(RuntimeError):
    """The model declined to answer (`stop_reason` `refusal`)."""


class AnthropicAnswerModel:
    """An `AnswerModel` on Anthropic's Messages API, e.g. `claude-sonnet-5-5`."""

    def __init__(self, model: str, *, client: Any = None):
        self.model = model
        if client is None:
            from anthropic import Anthropic

            client = Anthropic()
        self._client = client

    def stream(self, messages: Sequence[PromptMessage]) -> Iterator[str | Usage]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": EFFORT},
            "messages": [
                {"role": m.role, "content": m.content} for m in messages if m.role != "system"
            ],
        }
        if system:
            request["system"] = system
        with self._client.messages.stream(**request) as stream:
            yield from stream.text_stream
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None)
            raise AnswerRefused(f"{self.model} declined to answer (category: {category})")
        usage = message.usage
        details = getattr(usage, "output_tokens_details", None)
        yield Usage(
            input_tokens=usage.input_tokens
            + (getattr(usage, "cache_creation_input_tokens", None) or 0)
            + (getattr(usage, "cache_read_input_tokens", None) or 0),
            output_tokens=usage.output_tokens,
            reasoning_tokens=getattr(details, "thinking_tokens", 0) or 0,
        )
