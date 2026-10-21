"""The Anthropic implementation of the answer model (ADR 0004), over the official SDK.

Streams a Message with adaptive thinking at every provider's settings
(`edgar_answer.generators`): effort `low` and a token cap of 32,000, which covers the
thinking and the answer, the same as the OpenAI implementation's reasoning effort and
completion-token cap, so the generator comparison measures the models rather than their
settings. The thinking is not shown
(the API's default display omits it) and counts in the output tokens. Its `stop_reason`
becomes the Answer Call's stop reason: `max_tokens`, the cap, is `token_cap`. The SDK
reads the key from `ANTHROPIC_API_KEY`.

No refusal fallback is configured: a fallback would answer with a different model, and
the comparison would no longer measure the one it names. A refused answer raises
instead, so the harness reports the case as not answered.

It lives outside the core package, which stays on the standard library.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from edgar_answer.generators import REASONING_EFFORT, TOKEN_CAP
from edgar_rag.answer_model import StopReason, Usage
from edgar_rag.retrieval import PromptMessage

__all__ = ["AnswerRefused", "AnthropicAnswerModel"]

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "complete",
    "stop_sequence": "complete",
    "max_tokens": "token_cap",
}
"""Anthropic's `stop_reason`s that the answer model's stop reasons name; any other is
`other`."""


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
            "max_tokens": TOKEN_CAP,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": REASONING_EFFORT},
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
            stop_reason=_STOP_REASONS.get(message.stop_reason, "other")
            if message.stop_reason
            else None,
            raw_stop_reason=message.stop_reason,
        )
