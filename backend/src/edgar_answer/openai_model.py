"""The OpenAI implementation of the answer model (ADR 0004), over the official SDK.

Streams a Chat Completion with reasoning effort `low` and a completion-token cap of
2,500, which covers the reasoning tokens and a 300–600 word answer. Its
`finish_reason` becomes the Answer Call's stop reason: `length`, the cap, is
`token_cap`. The model defaults to `gpt-6-luna`; the `OPENAI_MODEL` environment
variable overrides it. The SDK reads the key from `OPENAI_API_KEY`.

It lives outside the core package, which stays on the standard library.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import Any

from edgar_rag.answer_model import StopReason, Usage
from edgar_rag.retrieval import PromptMessage

__all__ = [
    "DEFAULT_OPENAI_MODEL",
    "MAX_COMPLETION_TOKENS",
    "MODEL_ENV_VAR",
    "REASONING_EFFORT",
    "OpenAIAnswerModel",
]

DEFAULT_OPENAI_MODEL = "gpt-6-luna"
MODEL_ENV_VAR = "OPENAI_MODEL"
REASONING_EFFORT = "low"
MAX_COMPLETION_TOKENS = 2_500

_STOP_REASONS: dict[str, StopReason] = {"stop": "complete", "length": "token_cap"}
"""OpenAI's `finish_reason`s that the answer model's stop reasons name; any other is
`other`."""


class OpenAIAnswerModel:
    """An `AnswerModel` on OpenAI's Chat Completions API."""

    def __init__(self, model: str | None = None, *, client: Any = None):
        self.model = model or os.environ.get(MODEL_ENV_VAR) or DEFAULT_OPENAI_MODEL
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self._client = client

    def stream(self, messages: Sequence[PromptMessage]) -> Iterator[str | Usage]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            reasoning_effort=REASONING_EFFORT,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
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
