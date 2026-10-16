"""The answer model seam: the one generative LLM request per question, the Answer Call.

No LLM framework (ADR 0004). `AnswerModel` is one small protocol that streams an
answer's text and reports its token usage, with one implementation per provider over
its official SDK (`edgar_rag.openai_model` for OpenAI). Tests use a fake.

`AnswerCall` runs one Answer Call for a prepared Answer Context: it streams the text
through and, when the stream ends, logs the model, prompt version, token usage and
latency as one JSON line. Without a framework this log is the tracing, and the
evaluation's cost and latency figures come from it.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from edgar_rag.retrieval import AnswerContext, PromptMessage

__all__ = [
    "DEFAULT_ANSWER_LOG",
    "AnswerCall",
    "AnswerCallRecord",
    "AnswerModel",
    "Usage",
]

DEFAULT_ANSWER_LOG = (
    Path(__file__).resolve().parents[3] / "data" / "derived" / "logs" / "answer_calls.jsonl"
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Usage:
    """Tokens one Answer Call consumed, as the provider reports them."""

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0
    """Reasoning tokens, already counted in `output_tokens`."""


class AnswerModel(Protocol):
    """A provider's model, streaming one answer to a rendered prompt."""

    @property
    def model(self) -> str:
        """The provider's model id, e.g. `gpt-6-luna`."""
        ...

    def stream(self, messages: Sequence[PromptMessage]) -> Iterator[str | Usage]:
        """Yield the answer's text as it arrives, then exactly one `Usage`."""
        ...


@dataclass(frozen=True)
class AnswerCallRecord:
    """One logged Answer Call."""

    timestamp: str
    model: str
    prompt_version: str
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    latency_s: float
    """From sending the request to the end of the stream."""
    first_token_s: float | None
    """From sending the request to the first text, or None if no text came."""
    sources: int
    completed: bool
    """False if the stream stopped early: the reader stopped or the provider failed."""


class AnswerCall:
    """One Answer Call. Iterate it for the answer's text; `record` is set at the end.

    ```python
    call = AnswerCall(context, model)
    for text in call:
        print(text, end="")
    call.record.output_tokens
    ```
    """

    def __init__(
        self,
        context: AnswerContext,
        model: AnswerModel,
        log_path: str | Path | None = DEFAULT_ANSWER_LOG,
    ):
        self.context = context
        self.model = model
        self.log_path = Path(log_path) if log_path is not None else None
        self.record: AnswerCallRecord | None = None

    def __iter__(self) -> Iterator[str]:
        started = time.perf_counter()
        first_token: float | None = None
        usage: Usage | None = None
        completed = False
        try:
            for part in self.model.stream(self.context.messages):
                if isinstance(part, Usage):
                    usage = part
                    continue
                if first_token is None and part:
                    first_token = time.perf_counter() - started
                yield part
            completed = True
        finally:
            self._log(time.perf_counter() - started, first_token, usage, completed)

    def _log(
        self, latency: float, first_token: float | None, usage: Usage | None, completed: bool
    ) -> None:
        self.record = AnswerCallRecord(
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
            model=self.model.model,
            prompt_version=self.context.prompt_version,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            reasoning_tokens=usage.reasoning_tokens if usage else None,
            latency_s=round(latency, 3),
            first_token_s=round(first_token, 3) if first_token is not None else None,
            sources=len(self.context.sources),
            completed=completed,
        )
        line = json.dumps(asdict(self.record))
        logger.info("answer call %s", line)
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
