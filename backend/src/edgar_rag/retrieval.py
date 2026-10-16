"""The retrieval seam: build the index, and prepare an Answer Context for a conversation.

Two entry points:

- `build_index(filings)` chunks every Filing from the Corpus seam and writes the derived
  SQLite file (ADR 0002): a `chunks` table with each chunk's metadata, an FTS5 table over
  its text with the `porter` tokenizer, and a `companies` table the Query Scope parser
  reads. `make index` runs it over the whole Corpus.
- `prepare_answer_context(messages)` resolves the latest user message's Query Scope,
  retrieves chunks for each Company in it, groups them into numbered Sources and renders
  the Answer Call's prompt. It is deterministic and makes no network calls.

Retrieval applies the Query Scope's Companies as a hard filter before `bm25()` ranking,
so each Company gets its own share of the context budget. Question text is reduced to
quoted terms before it reaches FTS5 `MATCH`, so FTS5 operators in a question
(`NOT`, `NEAR`, `*`, quotes, colons) are searched as words, never run.

This module and everything it imports stay on the standard library.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from edgar_rag._chunks import Chunk, chunk_filing, count_tokens
from edgar_rag._prompt import PROMPT_VERSION, render
from edgar_rag._query_scope import ScopeCompany, find_companies
from edgar_rag.corpus import Filing

__all__ = [
    "CONTEXT_BUDGET_TOKENS",
    "DEFAULT_INDEX",
    "PROMPT_VERSION",
    "AnswerContext",
    "Message",
    "PromptMessage",
    "QueryScope",
    "ScopeCompany",
    "Source",
    "build_index",
    "count_tokens",
    "prepare_answer_context",
]

DEFAULT_INDEX = Path(__file__).resolve().parents[3] / "data" / "derived" / "edgar_rag.sqlite"

CONTEXT_BUDGET_TOKENS = 32_000
"""Tokens of Source text per Answer Call, split evenly across the Companies in scope."""

_CANDIDATES_PER_COMPANY = 200

_SCHEMA = """
CREATE TABLE companies (
    ticker TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sector TEXT,
    industry TEXT,
    coverage TEXT
);
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    filing_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    company TEXT NOT NULL,
    sector TEXT,
    industry TEXT,
    form_type TEXT NOT NULL,
    report_period TEXT NOT NULL,
    fiscal_period TEXT,
    coverage TEXT,
    section TEXT NOT NULL,
    item TEXT,
    kind TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    tokens INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX chunks_ticker ON chunks (ticker);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='porter'
);
"""

_CHUNK_COLUMNS = (
    "filing_id, ticker, company, sector, industry, form_type, report_period, fiscal_period, "
    "coverage, section, item, kind, ordinal, tokens, text"
)

# Words that carry no topic. Company names are taken out separately.
_STOPWORDS = frozenset(
    """a about above across after against all also among an and any are as at be been
    before being between both but by can could did do does doing during each either for
    from had has have having how i if in into is it its itself me more most my no nor
    not of off on once only or other our out over own same she should so some such than
    that the their them then there these they this those through to too under until up
    very was we were what when where which while who whom why will with would you your
    compare compared comparison describe explain tell give show list summarize summarise
    please facing face faced""".split()
)


@dataclass(frozen=True)
class Message:
    """One turn of a conversation, as the browser sends it. Anything with the same
    `role` and `content` will do, such as a Golden Set case's history."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class PromptMessage:
    """One message of the rendered Answer Call prompt."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class QueryScope:
    """What the rules resolved from the question before retrieval."""

    companies: tuple[ScopeCompany, ...]


@dataclass(frozen=True)
class Source:
    """One numbered, citable item: the retrieved text of one Section of one Filing."""

    number: int
    filing_id: str
    ticker: str
    company: str
    form_type: str
    report_period: str
    fiscal_period: str | None
    section: str
    item: str | None
    text: str
    """The retrieved chunks of the Section, in body order."""

    @property
    def tag(self) -> str:
        return f"S{self.number}"

    @property
    def label(self) -> str:
        """How the Source is named in the prompt and in citations."""
        period = f" {self.fiscal_period}" if self.fiscal_period else ""
        item = f" ({self.item})" if self.item else ""
        return (
            f"{self.ticker} {self.form_type}{period}, {self.section}{item}. "
            f"Filing ID {self.filing_id}, Report Period {self.report_period}."
        )


@dataclass(frozen=True)
class AnswerContext:
    """Everything the Answer Call needs, prepared deterministically."""

    query_scope: QueryScope
    sources: tuple[Source, ...]
    prompt_version: str
    messages: tuple[PromptMessage, ...]


def build_index(filings: Iterable[Filing], path: str | Path = DEFAULT_INDEX) -> Path:
    """Chunk every Filing and write the index to `path`, replacing any index there.

    The file is written beside `path` first and moved into place when complete, so a
    failed build never leaves a half-written index.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.unlink(missing_ok=True)
    db = sqlite3.connect(partial)
    try:
        db.executescript(_SCHEMA)
        companies: dict[str, tuple] = {}
        for filing in filings:
            companies.setdefault(
                filing.ticker,
                (filing.ticker, filing.company, filing.sector, filing.industry, filing.coverage),
            )
            db.executemany(
                f"INSERT INTO chunks ({_CHUNK_COLUMNS}) VALUES ({', '.join('?' * 15)})",
                (_row(chunk) for chunk in chunk_filing(filing)),
            )
        db.executemany("INSERT INTO companies VALUES (?, ?, ?, ?, ?)", companies.values())
        db.execute("INSERT INTO chunks_fts (chunks_fts) VALUES ('rebuild')")
        db.commit()
    finally:
        db.close()
    os.replace(partial, path)
    return path


def prepare_answer_context(
    messages: Sequence[Message], index: str | Path = DEFAULT_INDEX
) -> AnswerContext:
    """The Answer Context for the latest user message of a conversation.

    `messages` is the conversation so far, oldest first, ending with the user message
    to answer.
    """
    if not messages or messages[-1].role != "user" or not messages[-1].content.strip():
        raise ValueError("the conversation must end with a non-empty user message")
    question = messages[-1].content
    with _connect(index) as db:
        companies, spans = find_companies(question, _companies(db))
        scope = QueryScope(companies=companies)
        terms = _terms(_without_spans(question, spans))
        sources = _sources(db, scope, terms)
    rendered = render(sources, messages[:-1], question)
    return AnswerContext(
        query_scope=scope,
        sources=sources,
        prompt_version=PROMPT_VERSION,
        messages=tuple(PromptMessage(role, content) for role, content in rendered),
    )


def _row(chunk: Chunk) -> tuple:
    return (
        chunk.filing_id,
        chunk.ticker,
        chunk.company,
        chunk.sector,
        chunk.industry,
        chunk.form_type,
        chunk.report_period,
        chunk.fiscal_period,
        chunk.coverage,
        chunk.section,
        chunk.item,
        chunk.kind,
        chunk.ordinal,
        count_tokens(chunk.text),
        chunk.text,
    )


class _connect:
    """A read-only connection to the index, closed on exit."""

    def __init__(self, index: str | Path):
        path = Path(index)
        if not path.exists():
            raise FileNotFoundError(f"no index at {path}; build it with `make index`")
        self.db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row

    def __enter__(self) -> sqlite3.Connection:
        return self.db

    def __exit__(self, *exc: object) -> None:
        self.db.close()


def _companies(db: sqlite3.Connection) -> list[ScopeCompany]:
    return [
        ScopeCompany(row["ticker"], row["name"], row["coverage"])
        for row in db.execute("SELECT ticker, name, coverage FROM companies ORDER BY ticker")
    ]


def _without_spans(text: str, spans: list[tuple[int, int]]) -> str:
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + " " + text[end:]
    return text


def _terms(question: str) -> str | None:
    """The question as an FTS5 query of quoted terms joined by OR, or None if no term
    is left. Every term is a run of letters and digits inside double quotes, so FTS5
    reads it as a string to match, never as an operator or a column filter."""
    words = re.findall(r"[^\W_]+", question.lower())
    terms = dict.fromkeys(w for w in words if w not in _STOPWORDS and len(w) > 1)
    return " OR ".join(f'"{term}"' for term in terms) or None


def _sources(db: sqlite3.Connection, scope: QueryScope, terms: str | None) -> tuple[Source, ...]:
    tickers: list[str | None] = [c.ticker for c in scope.companies] or [None]
    budget = CONTEXT_BUDGET_TOKENS // len(tickers)
    sources: list[Source] = []
    for ticker in tickers:
        chosen: list[sqlite3.Row] = []
        seen_text: set[str] = set()
        spent = 0
        for row in _ranked(db, ticker, terms):
            if row["text"] in seen_text:
                continue  # the same passage in an older Filing
            if spent + row["tokens"] > budget:
                break
            seen_text.add(row["text"])
            spent += row["tokens"]
            chosen.append(row)
        sources += _group(chosen, first_number=len(sources) + 1)
    return tuple(sources)


def _ranked(db: sqlite3.Connection, ticker: str | None, terms: str | None) -> list[sqlite3.Row]:
    """The Company's best chunks for the terms, best first. A repeated passage ranks
    its most recent Filing first. Risk pointers ("no material changes since the 10-K")
    are indexed so they can be cited, but never retrieved as an answer (finding 16)."""
    if terms is None:
        return []
    company_filter = "AND c.ticker = :ticker" if ticker else ""
    return db.execute(
        f"""
        SELECT c.*, bm25(chunks_fts) AS score
        FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
        WHERE chunks_fts MATCH :terms AND c.kind != 'risk_pointer' {company_filter}
        ORDER BY score, c.report_period DESC
        LIMIT :limit
        """,
        {"terms": terms, "ticker": ticker, "limit": _CANDIDATES_PER_COMPANY},
    ).fetchall()


def _group(rows: list[sqlite3.Row], first_number: int) -> list[Source]:
    """One Source per (Filing, Section), numbered in order of each group's best chunk."""
    groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault((row["filing_id"], row["section"]), []).append(row)
    sources = []
    for number, group in enumerate(groups.values(), start=first_number):
        first = group[0]
        in_order = sorted(group, key=lambda r: r["ordinal"])
        sources.append(
            Source(
                number=number,
                filing_id=first["filing_id"],
                ticker=first["ticker"],
                company=first["company"],
                form_type=first["form_type"],
                report_period=first["report_period"],
                fiscal_period=first["fiscal_period"],
                section=first["section"],
                item=first["item"] if len({r["item"] for r in group}) == 1 else None,
                text="\n[…]\n".join(r["text"] for r in in_order),
            )
        )
    return sources


if __name__ == "__main__":
    from edgar_rag.corpus import load_corpus

    print(f"Index written to {build_index(load_corpus())}")
