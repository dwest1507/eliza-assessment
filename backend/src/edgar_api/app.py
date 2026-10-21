"""The chat API: `POST /api/chat` and `GET /api/health`.

`POST /api/chat` takes the conversation's messages, prepares the Answer Context through
the retrieval seam and makes the one Answer Call. The response is the Vercel AI SDK UI
message stream (server-sent events, header `x-vercel-ai-ui-message-stream: v1`), so the
front-end's `useChat` reads it as is:

1. `start`;
2. `data-query-scope`: the Query Scope the rules resolved, shown as chips above the
   answer: the Companies, the Sector phrases and the Companies each resolved to, the
   time window, the Section hints, the metric and the places retrieval searched (each
   Filing's Section, or a `section` of null for a Filing searched whole);
3. `data-sources`: every numbered Source with its tag, Filing metadata (its calendar
   months among them, also in its label) and passage, so citations are clickable
   before the answer arrives;
4. `data-coverage-gaps`: every Coverage Gap (its kind, label, Companies and fixed
   wording), shown as a callout beside the answer; an empty list when there is none;
5. `start-step`, `text-start`, one `text-delta` per streamed piece of the answer,
   `text-end`, `finish-step`, `finish`;
6. `[DONE]`.

If the provider fails mid-answer, the text ends and an `error` part replaces the finish.

The backend is stateless: the browser sends the conversation every time and the Query
Scope is recomputed from it, a follow-up inheriting each part it does not name from the
most recent earlier question that named it (ADR 0003). An earlier answer may carry the
Filing ID each of its Source tags cited (a `sources` map, or its own `data-sources`
part), and the prompt's history names those Filings in place of the tags. Nothing about
one request is kept for the next. The answer model is built once, on the first question,
so `/api/health` works without a provider key.

The answer model is the generator `ANSWER_MODEL` names (`edgar_answer.generators`), of
either provider, `gpt-6-luna` by default. A model not in the generator table stops the
app as it is created, with an error naming the table's models. An answer that stops at
the token cap (stop reason `token_cap`) is cut off: it is still streamed and logged, and
the API logs a warning naming the model and the tokens used.

A request is answered with 400 and a `detail` saying why when it has no messages, more
than `MAX_MESSAGES` (the question and the `HISTORY_TURNS` messages before it, all the
prompt uses), an earlier message longer than `MAX_EARLIER_MESSAGE_CHARS`, or a latest
message that is not the user's, is blank, or is longer than `MAX_MESSAGE_CHARS`. The
front-end's chat proxy sends only the last `MAX_MESSAGES`, so a long conversation keeps
working there.

Run it with `make api`. Configuration comes from the environment: `CORS_ALLOWED_ORIGINS`
(comma-separated; none by default), `ANSWER_MODEL` and the key its provider needs
(`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`).
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
    HISTORY_TURNS,
    AnswerContext,
    CoverageGap,
    Message,
    QueryScope,
    Source,
    prepare_answer_context,
)

__all__ = [
    "CORS_ENV_VAR",
    "MAX_EARLIER_MESSAGE_CHARS",
    "MAX_MESSAGES",
    "MAX_MESSAGE_CHARS",
    "create_app",
]

MAX_MESSAGE_CHARS = 4_000
"""The longest latest message answered. A business question is a sentence or two."""

MAX_EARLIER_MESSAGE_CHARS = 20_000
"""The longest earlier message accepted. An earlier answer runs to 300–1,000 words, by the
number of Companies it covers, about 7,000 characters at most; this leaves it more than
twice that room and still bounds the request."""

MAX_MESSAGES = HISTORY_TURNS + 1
"""The most messages a conversation may send: the question and the earlier messages the
prompt keeps as history. Its one source of truth is the prompt's `HISTORY_TURNS`; the
front-end's chat proxy sends no more than this, dropping the oldest."""

CORS_ENV_VAR = "CORS_ALLOWED_ORIGINS"

STREAM_HEADERS = {
    "x-vercel-ai-ui-message-stream": "v1",
    "cache-control": "no-cache",
    "x-accel-buffering": "no",
}

ERROR_TEXT = "The answer could not be completed. Please try again."

logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    """One message as `useChat` sends it (`parts`), or as plain `content` (for `curl`).

    An earlier answer may say which Filing each of its Source tags cited, as a `sources`
    map ({"S1": "AAPL_10-K_2025-09-27"}) or as its `data-sources` part, so the prompt's
    history names those Filings instead of tags that meant that turn's Sources."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant"]
    content: str | None = None
    parts: list[dict[str, Any]] | None = None
    sources: dict[str, str] | None = None

    @property
    def cited(self) -> dict[str, str]:
        """The Filing ID each Source tag of this message cited."""
        if self.sources is not None:
            return self.sources
        for part in self.parts or ():
            if part.get("type") == "data-sources" and isinstance(part.get("data"), dict):
                return {
                    s["tag"]: s["filingId"]
                    for s in part["data"].get("sources") or ()
                    if isinstance(s, dict)
                    and isinstance(s.get("tag"), str)
                    and isinstance(s.get("filingId"), str)
                }
        return {}

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
    is the answer model; the default is the generator `ANSWER_MODEL` names, refused here
    with `UnknownAnswerModel` when it is not in the generator table. `allowed_origins`
    defaults to the `CORS_ALLOWED_ORIGINS` environment variable."""
    if model is None and model_factory is None:
        model_factory = _configured_model_factory()
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
    """The conversation for the retrieval seam, or a 400 if it holds more messages than the
    prompt uses, an earlier message over its length cap, or a latest message that is not a
    question we can answer."""
    if not messages:
        raise HTTPException(400, "The conversation has no messages.")
    if len(messages) > MAX_MESSAGES:
        raise HTTPException(
            400,
            f"The conversation has {len(messages)} messages; send at most {MAX_MESSAGES}, "
            f"the question and the {HISTORY_TURNS} messages before it that the prompt uses.",
        )
    for number, message in enumerate(messages[:-1], start=1):
        if len(message.text) > MAX_EARLIER_MESSAGE_CHARS:
            raise HTTPException(
                400,
                f"Message {number} of the conversation is longer than "
                f"{MAX_EARLIER_MESSAGE_CHARS:,} characters.",
            )
    latest = messages[-1]
    if latest.role != "user":
        raise HTTPException(400, "The latest message must be the user's question.")
    if not latest.text.strip():
        raise HTTPException(400, "The question is empty.")
    if len(latest.text) > MAX_MESSAGE_CHARS:
        raise HTTPException(400, f"The question is longer than {MAX_MESSAGE_CHARS} characters.")
    return [Message(m.role, m.text, m.cited) for m in messages if m.role != "system"]


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
    call = AnswerCall(context, model, log_path=log_path)
    answer = iter(call)
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
        _warn_on_cap(call)
    yield "data: [DONE]\n\n"


def _warn_on_cap(call: AnswerCall) -> None:
    """Log a warning when the answer stopped at the token cap, so a cut-off answer is
    never silent."""
    record = call.record
    if record is not None and record.stop_reason == "token_cap":
        logger.warning(
            "the answer stopped at the token cap and is cut off: model %s, prompt %s, "
            "%s output tokens (%s reasoning)",
            record.model,
            record.prompt_version,
            record.output_tokens,
            record.reasoning_tokens,
        )


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
        "searched": [
            {"ticker": p.ticker, "filingId": p.filing_id, "section": p.section}
            for p in scope.searched
        ],
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
        "calendarMonths": s.calendar_months,
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
    assert factory is not None
    built: list[AnswerModel] = []
    lock = threading.Lock()

    def get() -> AnswerModel:
        with lock:
            if not built:
                built.append(factory())
            return built[0]

    return get


def _configured_model_factory() -> Callable[[], AnswerModel]:
    """The factory of the answer model `ANSWER_MODEL` names, checked against the
    generator table now, so a misnamed model stops the app before it serves."""
    from edgar_answer.generators import answer_model, require

    model = require().model
    return lambda: answer_model(model)
