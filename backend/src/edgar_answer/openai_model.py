"""The OpenAI implementation of the answer model (ADR 0004), over the official SDK.

Streams a Chat Completion at every provider's settings (`edgar_answer.generators`):
reasoning effort `low` and a completion-token cap of 32,000, which covers the
reasoning tokens and the answer. Its `finish_reason` becomes the Answer Call's stop
reason: `length`, the cap, is `token_cap`. The model is the one it is built with,
`gpt-6-luna` by default; the product picks it by `ANSWER_MODEL`
(`edgar_answer.generators.answer_model`). The SDK reads the key from `OPENAI_API_KEY`.

It lives outside the core package, which stays on the standard library.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import Any

from edgar_answer.generators import REASONING_EFFORT, TOKEN_CAP
from edgar_rag.answer_model import StopReason, Usage
from edgar_rag.retrieval import PromptMessage

__all__ = ["DEFAULT_OPENAI_MODEL", "OpenAIAnswerModel"]

DEFAULT_OPENAI_MODEL = "gpt-6-luna"

_STOP_REASONS: dict[str, StopReason] = {"stop": "complete", "length": "token_cap"}
"""OpenAI's `finish_reason`s that the answer model's stop reasons name; any other is
`other`."""


class OpenAIAnswerModel:
    """An `AnswerModel` on OpenAI's Chat Completions API."""

    def __init__(self, model: str | None = None, *, client: Any = None):
        self.model = model or DEFAULT_OPENAI_MODEL
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self._client = client

    def stream(self, messages: Sequence[PromptMessage]) -> Iterator[str | Usage]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            reasoning_effort=REASONING_EFFORT,
            max_completion_tokens=TOKEN_CAP,
            stream=True,
            stream_options={"include_usage": True},
        )
        usage = Usage(0, 0)
        finish_reason: str | None = None
        for chunk in response:
            for choice in chunk.choices or ():
                if choice.delta and choice.delta.content:
                    yield choice.delta.content
                finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            if chunk.usage:
                details = getattr(chunk.usage, "completion_tokens_details", None)
                usage = Usage(
                    input_tokens=chunk.usage.prompt_tokens,
                    output_tokens=chunk.usage.completion_tokens,
                    reasoning_tokens=getattr(details, "reasoning_tokens", 0) or 0,
                )
        yield replace(
            usage,
            stop_reason=_STOP_REASONS.get(finish_reason, "other") if finish_reason else None,
            raw_stop_reason=finish_reason,
        )
