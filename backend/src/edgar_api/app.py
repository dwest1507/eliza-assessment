"""The chat API: `POST /api/chat` and `GET /api/health`.

`POST /api/chat` takes the conversation's messages, prepares the Answer Context through
the retrieval seam and makes the one Answer Call. The response is the Vercel AI SDK UI
message stream (server-sent events, header `x-vercel-ai-ui-message-stream: v1`), so the
front-end's `useChat` reads it as is:

1. `start`;
2. `data-query-scope`: the Query Scope the rules resolved, shown as chips above the
   answer: the Companies, the Sector phrases and the Companies each resolved to, the
   time window, the Section hints and the metric;
3. `data-sources`: every numbered Source with its tag, Filing metadata and passage, so
   citations are clickable before the answer arrives;
4. `data-coverage-gaps`: every Coverage Gap (its kind, label, Companies and fixed
   wording), shown as a callout beside the answer; an empty list when there is none;
5. `start-step`, `text-start`, one `text-delta` per streamed piece of the answer,
   `text-end`, `finish-step`, `finish`;
6. `[DONE]`.

If the provider fails mid-answer, the text ends and an `error` part replaces the finish.

The backend is stateless: the browser sends the whole conversation every time and the
Query Scope is recomputed from it (ADR 0003). Nothing about one request is kept for the
next. The answer model is built once, on the first question, so `/api/health` works
without a provider key.

Run it with `make api`. Configuration comes from the environment: `CORS_ALLOWED_ORIGINS`
(comma-separated; none by default) and the answer model's own variables (`OPENAI_API_KEY`,
`OPENAI_MODEL`).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from edgar_rag.answer_model import DEFAULT_ANSWER_LOG, AnswerCall, AnswerModel
from edgar_rag.retrieval import (
    DEFAULT_INDEX,
    AnswerContext,
    CoverageGap,
    Message,
    QueryScope,
    Source,
    prepare_answer_context,
)

__all__ = ["CORS_ENV_VAR", "MAX_MESSAGE_CHARS", "create_app"]

MAX_MESSAGE_CHARS = 4_000
"""The longest latest message answered. A business question is a sentence or two."""

CORS_ENV_VAR = "CORS_ALLOWED_ORIGINS"

STREAM_HEADERS = {
    "x-vercel-ai-ui-message-stream": "v1",
    "cache-control": "no-cache",
    "x-accel-buffering": "no",
}

ERROR_TEXT = "The answer could not be completed. Please try again."

logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    """One message as `useChat` sends it (`parts`), or as plain `content` (for `curl`)."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant"]
    content: str | None = None
    parts: list[dict[str, Any]] | None = None

    @property
    def text(self) -> str:
        if self.content is not None:
            return self.content
        return "".join(
            part["text"]
            for part in self.parts or ()
            if part.get("type") == "text" and isinstance(part.get("text"), str)
        )


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messages: list[ChatMessage]


def create_app(
    *,
    index: str | Path = DEFAULT_INDEX,
    model: AnswerModel | None = None,
    model_factory: Callable[[], AnswerModel] | None = None,
    allowed_origins: Sequence[str] | None = None,
    log_path: str | Path | None = DEFAULT_ANSWER_LOG,
) -> FastAPI:
    """The API app. `model` (or else `model_factory`, called once, on the first question)
    is the answer model; the default is OpenAI's. `allowed_origins` defaults to the
    `CORS_ALLOWED_ORIGINS` environment variable."""
    get_model = _model_getter(model, model_factory)
    if allowed_origins is None:
        allowed_origins = _origins_from_env()

    app = FastAPI(title="SEC Filings RAG", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> StreamingResponse:
        messages = _conversation(request.messages)
        try:
            context = prepare_answer_context(messages, index)
            answer_model = get_model()
        except FileNotFoundError as error:
            logger.error("%s", error)
            raise HTTPException(503, "The index is not built yet.") from error
        except Exception as error:
            logger.exception("the answer model could not be created")
            raise HTTPException(503, "The answer model is not available.") from error
        return StreamingResponse(
            _ui_message_stream(context, answer_model, log_path),
            media_type="text/event-stream",
            headers=STREAM_HEADERS,
        )

    return app


def _conversation(messages: Sequence[ChatMessage]) -> list[Message]:
    """The conversation for the retrieval seam, or a 400 if its latest message is not a
    question we can answer."""
    if not messages:
        raise HTTPException(400, "The conversation has no messages.")
    latest = messages[-1]
    if latest.role != "user":
        raise HTTPException(400, "The latest message must be the user's question.")
    if not latest.text.strip():
        raise HTTPException(400, "The question is empty.")
    if len(latest.text) > MAX_MESSAGE_CHARS:
        raise HTTPException(400, f"The question is longer than {MAX_MESSAGE_CHARS} characters.")
    return [Message(m.role, m.text) for m in messages if m.role != "system"]


def _ui_message_stream(
    context: AnswerContext, model: AnswerModel, log_path: str | Path | None
) -> Iterator[str]:
    yield _event({"type": "start", "messageId": f"msg-{uuid4().hex}"})
    yield _event({"type": "data-query-scope", "data": _query_scope(context.query_scope)})
    yield _event({"type": "data-sources", "data": {"sources": _sources(context.sources)}})
    yield _event({"type": "data-coverage-gaps", "data": {"gaps": _gaps(context.coverage_gaps)}})
    yield _event({"type": "start-step"})
    text_id = f"text-{uuid4().hex}"
    yield _event({"type": "text-start", "id": text_id})
    answer = iter(AnswerCall(context, model, log_path=log_path))
    try:
        for text in answer:
            if text:
                yield _event({"type": "text-delta", "id": text_id, "delta": text})
    except Exception:
        logger.exception("the Answer Call failed")
        yield _event({"type": "text-end", "id": text_id})
        yield _event({"type": "error", "errorText": ERROR_TEXT})
    else:
        yield _event({"type": "text-end", "id": text_id})
        yield _event({"type": "finish-step"})
        yield _event({"type": "finish"})
    finally:
        answer.close()  # logs the call, as incomplete if the browser went away
    yield "data: [DONE]\n\n"


def _event(part: dict[str, Any]) -> str:
    return f"data: {json.dumps(part, ensure_ascii=False)}\n\n"


def _query_scope(scope: QueryScope) -> dict[str, Any]:
    window = scope.time_window
    return {
        "companies": [
            {"ticker": c.ticker, "name": c.name, "coverage": c.coverage} for c in scope.companies
        ],
        "sectorPhrases": [
            {
                "phrase": p.phrase,
                "column": p.column,
                "values": list(p.values),
                "tickers": list(p.tickers),
            }
            for p in scope.sector_phrases
        ],
        "timeWindow": {"kind": window.kind, "count": window.count, "label": window.label},
        "sections": list(scope.sections),
        "metric": scope.metric,
    }


def _sources(sources: Sequence[Source]) -> list[dict[str, Any]]:
    return [_source(s) for s in sources]


def _source(s: Source) -> dict[str, Any]:
    sent: dict[str, Any] = {
        "tag": s.tag,
        "filingId": s.filing_id,
        "company": s.company,
        "ticker": s.ticker,
        "formType": s.form_type,
        "reportPeriod": s.report_period,
        "fiscalPeriod": s.fiscal_period,
        "section": s.section,
        "item": s.item,
        "label": s.label,
        "text": s.text,
        "kind": s.kind,
    }
    if s.kind == "facts":
        sent["rows"] = [
            {
                "metric": r.metric,
                "metricName": r.metric_name,
                "segment": r.segment,
                "months": r.months,
                "reportPeriod": r.report_period,
                "value": r.value,
                "valueText": r.value_text,
                "label": r.label,
            }
            for r in s.facts
        ]
    return sent


def _gaps(gaps: Sequence[CoverageGap]) -> list[dict[str, Any]]:
    return [
        {"kind": g.kind, "label": g.label, "companies": list(g.companies), "text": g.text}
        for g in gaps
    ]


def _origins_from_env() -> list[str]:
    return [o.strip() for o in os.environ.get(CORS_ENV_VAR, "").split(",") if o.strip()]


def _model_getter(
    model: AnswerModel | None, factory: Callable[[], AnswerModel] | None
) -> Callable[[], AnswerModel]:
    if model is not None:
        return lambda: model
    if factory is None:
        factory = _openai_model
    built: list[AnswerModel] = []
    lock = threading.Lock()

    def get() -> AnswerModel:
        with lock:
            if not built:
                built.append(factory())
            return built[0]

    return get


def _openai_model() -> AnswerModel:
    from edgar_answer.openai_model import OpenAIAnswerModel

    return OpenAIAnswerModel()
