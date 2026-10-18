"""The retrieval seam: build the index, and prepare an Answer Context for a conversation.

Two entry points:

- `build_index(filings)` chunks every Filing from the Corpus seam and writes the derived
  SQLite file (ADR 0002): a `chunks` table holding each Company's distinct chunk texts
  once, a `chunk_filings` table listing every Filing (and Section and position) each
  chunk appears in, with the text of it that is new since the previous Filing of the
  same Form Type, an FTS5 table over the chunk text with the `porter` tokenizer, and the
  `companies`, `filings` and `sections` tables the Query Scope and retrieval plan read,
  and the `financial_facts` table: the Tracked Companies' Financial Facts as the
  Financial Facts seam reads them from each Filing (ADR 0001; never SEC XBRL data). The
  `filing_chunks` view joins the chunks back into one row per chunk per Filing, and the
  `settings` table records the chunk size the index was built with (`CHUNK_TOKENS`
  unless another is given, ADR 0010). `make index` runs it over the whole Corpus.
- `prepare_answer_context(messages)` resolves the latest user message's Query Scope,
  looks up the Financial Facts of any metric it names, retrieves chunks for each Company
  in it within the context budget (`CONTEXT_BUDGET_TOKENS` unless another is given, ADR
  0010), groups them into numbered Sources and renders the Answer Call's prompt. It is
  deterministic and makes no network calls.

A follow-up inherits each part of the Query Scope it does not name (the Companies, the
time window and named periods, the Section hints, the metric) from the most recent
earlier user message that named it, and a part it names replaces the inherited one (ADR
0003). A follow-up with no topic words of its own ("And what about Microsoft?") is also
searched with the words of the most recent earlier message that had some. The Query
Scope module (`_query_scope.inherit_scope`) decides which message each part comes from.

The GE Capital FY2014 10-K (a stale Filing) is left out of every answer unless the
question, or the message whose Companies it inherits, asks for GE Capital by name or
names a period the Filing covers (assumption 3). When it is left out, retrieval is held
to the remaining Filings even where the scope would otherwise search anywhere, so a
question naming no Company cannot reach it either. When it is asked for, nothing is
left out and holding retrieval would change nothing, so it is not held.

A question naming a metric (revenue, net income, a segment) gets the Financial Facts
table: one fixed parameterised query per Company and metric, cut to the Query Scope's
Filings, with derived fourth quarters and year-on-year changes labelled as derived and a
segment series stopped at a segment reorganisation. Each Filing the figures come from is
one Facts Source, numbered before the text Sources. A Company and metric the store can't
answer falls back to the text, and the prompt says the answer must say so.

Retrieval applies the Query Scope's Companies and time window as hard filters before
`bm25()` ranking, and each Company gets an even share of the context budget. A Section
hint is a preference: each Filing in the window is searched in the hinted Sections, or
whole when every one of them is missing or a stub (finding 14). A hint may plan several
Sections, and `QueryScope.sections` lists every Section planned. A legal proceedings
question also searches the Financial Statements, whose contingencies note is where a stub
Item 3 points ("see Note 15"), so a Filing whose Item 3 is a stub is searched in its
Financial Statements, not whole. A risk question is routed to the latest 10-K's Risk
Factors plus any later 10-Q that states risk text; a later 10-Q whose Risk Factors only
point back to the 10-K is cited as it stands, never ranked (finding 16). A cybersecurity
question is routed the same way, to the Cybersecurity Section, Risk Factors and MD&A of
the latest Filings. The Query Scope records the places searched (`QueryScope.searched`),
so the answer's reader, and the evaluation, can see where retrieval looked.

Repeated text costs the budget once (finding 17). A chunk repeated across a Company's
Filings is stored once and cited from the most recent Filing in the plan that holds it,
or from a Filing of a period the question names. Retrieved chunks that are near-
duplicates of more recent retrieved chunks are dropped, and the more recent chunk takes
their place in the ranking. A change question ("how have the risks changed") ranks the
chunks holding paragraphs new since the previous Filing of the same Form Type first, and
cites only those paragraphs, from the Filing they are new in.

Question text is reduced to quoted terms before it reaches FTS5 `MATCH`, so FTS5
operators in a question (`NOT`, `NEAR`, `*`, quotes, colons) are searched as words,
never run. The terms leave out generic words ("main", "key") and the phrases that set a
Section hint ("risks" on the risk route), which match nearly every passage of the
Section searched: the chunks matching only those words rank after every chunk matching
the question's other words, so they still fill the budget but never outrank the topic.
A question with nothing else naming a topic is searched with all its words.

The ranking step can be swapped: `prepare_answer_context` takes an optional `Ranker`,
which is given the question, every chunk inside the hard filters and the `bm25()`
ranking of them, and returns its own ranking. The evaluation's challenger Arms (dense
embeddings, a hybrid, a re-ranker) plug in here, so they are measured on exactly the
pipeline the product runs; without a ranker the `bm25()` ranking is used as it stands.

This module and everything it imports stay on the standard library.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from edgar_rag import _facts
from edgar_rag._chunks import (
    TARGET_TOKENS,
    Chunk,
    ChunkSize,
    _sentences,
    chunk_filing,
    count_tokens,
)
from edgar_rag._coverage import (
    DEFAULT_MISSING_COMPANIES,
    CompanyCoverage,
    CoverageGap,
    coverage_gaps,
    load_missing_companies,
    stale_filings_left_out,
)
from edgar_rag._facts import FactNote, FactRow
from edgar_rag._prompt import HISTORY_MAX_TOKENS, HISTORY_TURNS, PROMPT_VERSION, render
from edgar_rag._query_scope import (
    LATEST,
    MissingCompany,
    ScopeCompany,
    ScopeFiling,
    SectorPhrase,
    TimeWindow,
    in_window,
    inherit_scope,
    is_change_question,
    names_period,
)
from edgar_rag._repeats import GAP, NEAR_DUPLICATE, NEW_TEXT, new_text, shingles
from edgar_rag.corpus import Filing
from edgar_rag.paths import DERIVED_DIR

__all__ = [
    "CHUNK_TOKENS",
    "CONTEXT_BUDGET_TOKENS",
    "DEFAULT_INDEX",
    "DEFAULT_MISSING_COMPANIES",
    "HISTORY_MAX_TOKENS",
    "HISTORY_TURNS",
    "NEAR_DUPLICATE",
    "NEW_TEXT",
    "PROMPT_VERSION",
    "AnswerContext",
    "CompanyCoverage",
    "CoverageGap",
    "FactNote",
    "FactRow",
    "Message",
    "MissingCompany",
    "PromptMessage",
    "QueryScope",
    "RankRequest",
    "Ranker",
    "STUB_TOKENS",
    "ScopeCompany",
    "SearchedPlace",
    "ScopeFiling",
    "SectorPhrase",
    "Source",
    "TimeWindow",
    "build_index",
    "count_tokens",
    "index_chunk_tokens",
    "load_missing_companies",
    "prepare_answer_context",
]

DEFAULT_INDEX = DERIVED_DIR / "edgar_rag.sqlite"

CHUNK_TOKENS = TARGET_TOKENS
"""The chunk size `make index` builds with: prose chunks of about this many tokens, never
above four thirds of it (ADR 0010)."""

CONTEXT_BUDGET_TOKENS = 32_000
"""Tokens of Source text per Answer Call, split evenly across the Companies in scope
(ADR 0010)."""

STUB_TOKENS = 250
"""A Section with less text than this (about 1,000 characters) is a stub, usually a
pointer to a note or another Item, so it is not searched, and a Filing whose hinted
Sections are all stubs or missing is searched whole."""

RISK_FACTORS = "Risk Factors"

_CANDIDATES_PER_COMPANY = 200

INDEX_VERSION = 5
"""Bumped whenever the index's tables change, so an older index is rebuilt, not misread.
Version 2 adds the `filings` and `sections` tables; version 3 stores each Company's
repeated chunks once, listing their Filings in `chunk_filings`; version 4 adds the
`financial_facts` table of ADR 0001; version 5 adds the `settings` table."""

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
    ticker TEXT NOT NULL,
    company TEXT NOT NULL,
    sector TEXT,
    industry TEXT,
    coverage TEXT,
    kind TEXT NOT NULL,
    tokens INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX chunks_ticker ON chunks (ticker);
CREATE TABLE chunk_filings (
    chunk_id INTEGER NOT NULL REFERENCES chunks (id),
    filing_id TEXT NOT NULL,
    form_type TEXT NOT NULL,
    report_period TEXT NOT NULL,
    fiscal_period TEXT,
    section TEXT NOT NULL,
    item TEXT,
    ordinal INTEGER NOT NULL,
    new_text TEXT,
    PRIMARY KEY (filing_id, ordinal)
);
CREATE INDEX chunk_filings_chunk ON chunk_filings (chunk_id);
CREATE VIEW filing_chunks AS
SELECT c.id, f.filing_id, c.ticker, c.company, c.sector, c.industry, f.form_type,
       f.report_period, f.fiscal_period, c.coverage, f.section, f.item, c.kind, f.ordinal,
       c.tokens, c.text, f.new_text
FROM chunk_filings f JOIN chunks c ON c.id = f.chunk_id;
CREATE TABLE filings (
    filing_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    form_type TEXT NOT NULL,
    report_period TEXT NOT NULL,
    fiscal_period TEXT
);
CREATE TABLE sections (
    filing_id TEXT NOT NULL,
    section TEXT NOT NULL,
    tokens INTEGER NOT NULL,
    pointer INTEGER NOT NULL,
    PRIMARY KEY (filing_id, section)
);
CREATE TABLE settings (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='porter'
);
"""


@dataclass(frozen=True)
class Message:
    """One turn of a conversation, as the browser sends it. Anything with the same
    `role` and `content` will do, such as a Golden Set case's history."""

    role: Literal["user", "assistant"]
    content: str
    sources: Mapping[str, str] = field(default_factory=dict, hash=False)
    """For an earlier answer, the Filing ID each of its Source tags cited ("S1" →
    "AAPL_10-K_2025-09-27"), so the prompt can name the Filings instead of tags that
    pointed at that turn's Sources. Tags it doesn't list are dropped."""


@dataclass(frozen=True)
class PromptMessage:
    """One message of the rendered Answer Call prompt."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class QueryScope:
    """What the rules resolved from the question before retrieval."""

    companies: tuple[ScopeCompany, ...]
    """The Companies the question names, by name, ticker or Sector phrase, in the order
    it first names them."""
    sector_phrases: tuple[SectorPhrase, ...]
    """The Sector phrases the question uses, each with the Sector table rows and the
    Companies it resolved to, so the answer and the front-end can name them."""
    time_window: TimeWindow
    """The window each Company's Filings are filtered to. A risk or cybersecurity
    question that names no time phrase and no Fiscal Period gets the latest window."""
    sections: tuple[str, ...]
    """The Sections the question's hints plan, preferred over the rest of each Filing
    (a cybersecurity question plans Cybersecurity, Risk Factors and MD&A, a legal
    proceedings question Legal Proceedings and Financial Statements)."""
    filings: tuple[ScopeFiling, ...]
    """The named Companies' Filings inside the window, by Company and then oldest
    first. A question naming no Company searches every Company's window."""
    periods: tuple[str, ...] = ()
    """The Fiscal Periods the question names ("FY2024", "Q2 FY2025"). A passage repeated
    across Filings is cited from one of these periods rather than the most recent."""
    change: bool = False
    """Whether the question asks how something changed, which routes it to the
    paragraphs new between periods."""
    metric: str | None = None
    """The Financial Facts metric the question names first (`revenue`, `net_income` or
    `segment_revenue`), or None."""
    metrics: tuple[str, ...] = ()
    """Every Financial Facts metric the question names, in order. Each is looked up in
    the Financial Facts store for every Company in scope."""
    segments: tuple[str, ...] = ()
    """The segments the question names, as the Filings print them. Empty with
    `segment_revenue` among the metrics means every segment."""
    missing_companies: tuple[str, ...] = ()
    """Companies the question names that are not in the Corpus, from the curated list
    of notable missing Companies, in the order it names them. They are Coverage Gaps,
    never answered."""
    searched: tuple[SearchedPlace, ...] = ()
    """Where retrieval searched: the Section plan's places, by Company in the order the
    question names them (every Company, by ticker, for a question naming none) and then
    oldest Filing first. A Filing searched whole has a Section of None. A risk pointer
    cited as it stands is not searched, so it is not listed. Empty when nothing was
    searched (a question naming only Companies missing from the Corpus)."""


@dataclass(frozen=True)
class SearchedPlace:
    """One place retrieval searched: a Section of a Filing, or the whole Filing."""

    ticker: str
    filing_id: str
    section: str | None
    """The Section searched, or None for the whole Filing."""


@dataclass(frozen=True)
class Source:
    """One numbered, citable item: the retrieved text of one Section of one Filing
    (`kind` "text"), or the Financial Facts taken from one Filing (`kind` "facts", whose
    `section` is "Financial Facts" and whose `facts` are the Filing's reported rows)."""

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
    """The retrieved chunks of the Section, in body order; for a Facts Source, its rows
    as text."""
    kind: Literal["text", "facts"] = "text"
    facts: tuple[FactRow, ...] = ()
    """A Facts Source's rows, as the Filing reports them."""

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
class RankRequest:
    """What a ranker is given for one Company's search (or the whole Corpus's, for a
    question naming no Company)."""

    question: str
    """The question as retrieval reads it: the latest message, after the message whose
    topic it inherits when it has none of its own."""
    ticker: str | None
    """The Company searched, or None for every Company."""
    eligible: tuple[int, ...]
    """Every chunk id inside the hard filters (the Company, the time window and the
    Section plan), ascending. Risk pointers are cited by rule and never ranked."""
    lexical: tuple[int, ...]
    """The eligible chunks the question's terms match, best `bm25()` score first, cut to
    the candidates the shipped seam considers."""


Ranker = Callable[[RankRequest], Sequence[int]]
"""Ranks the chunks of a `RankRequest`, best first. Ids outside `eligible` are ignored,
so a ranker can never reach past the hard filters; at most the first
`_CANDIDATES_PER_COMPANY` are used."""


@dataclass(frozen=True)
class AnswerContext:
    """Everything the Answer Call needs, prepared deterministically."""

    query_scope: QueryScope
    sources: tuple[Source, ...]
    """The Facts Sources first, then the text Sources."""
    prompt_version: str
    messages: tuple[PromptMessage, ...]
    coverage: tuple[CompanyCoverage, ...] = ()
    """What the Corpus holds for each Company in scope (or, for a question naming no
    Company, each Company a Source came from): its coverage class, its Filings, those in
    the time window and any stale Filing left out."""
    coverage_gaps: tuple[CoverageGap, ...] = ()
    """What the Corpus cannot answer, in fixed wordings the answer must state."""
    financial_facts: tuple[FactRow, ...] = ()
    """The Financial Facts table of the prompt: reported and derived rows, each citing
    the tags of the Facts Sources it comes from."""
    fact_notes: tuple[FactNote, ...] = ()
    """What the Financial Facts can't answer: a Company and metric that falls back to
    the Filing text, or a segment reorganisation the series stops at."""


def build_index(
    filings: Iterable[Filing],
    path: str | Path = DEFAULT_INDEX,
    chunk_tokens: int = CHUNK_TOKENS,
) -> Path:
    """Chunk every Filing into chunks of about `chunk_tokens` tokens and write the index
    to `path`, replacing any index there.

    The file is written beside `path` first and moved into place when complete, so a
    failed build never leaves a half-written index. Within each Company, a chunk whose
    kind and text repeat an earlier chunk is stored once and listed under every Filing
    it appears in. Each listing records the chunk's new text: its paragraphs absent from
    the Company's previous Filing of the same Form Type.
    """
    path = Path(path)
    size = ChunkSize(chunk_tokens)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.unlink(missing_ok=True)
    db = sqlite3.connect(partial)
    try:
        db.executescript(_SCHEMA + _facts.SCHEMA)
        companies: dict[str, tuple] = {}
        stored: dict[tuple[str, str, str], int] = {}  # (ticker, kind, text) → chunk id
        previous: dict[tuple[str, str], set[int]] = {}  # (ticker, Form Type) → shingles
        for filing in sorted(filings, key=lambda f: (f.ticker, f.report_period, f.filing_id)):
            companies.setdefault(
                filing.ticker,
                (filing.ticker, filing.company, filing.sector, filing.industry, filing.coverage),
            )
            earlier = previous.get((filing.ticker, filing.form_type))
            seen: set[int] = set()
            for chunk in chunk_filing(filing, size):
                key = (chunk.ticker, chunk.kind, chunk.text)
                if key not in stored:
                    stored[key] = len(stored) + 1
                    db.execute(
                        "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (stored[key],) + _chunk_row(chunk),
                    )
                seen |= shingles(chunk.text)
                new = (
                    None
                    if chunk.kind == "risk_pointer"
                    else new_text(_sentences(chunk.text, size.ceiling), earlier)
                )
                db.execute(
                    "INSERT INTO chunk_filings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (stored[key],) + _listing_row(chunk) + (new,),
                )
            previous[(filing.ticker, filing.form_type)] = seen
            db.executemany(
                f"INSERT INTO financial_facts VALUES ({', '.join('?' * 12)})",
                _facts.store_rows(filing),
            )
        db.executemany("INSERT INTO companies VALUES (?, ?, ?, ?, ?)", companies.values())
        db.executescript(
            """
            INSERT INTO filings
            SELECT DISTINCT filing_id, ticker, form_type, report_period, fiscal_period
            FROM filing_chunks;
            INSERT INTO sections
            SELECT filing_id, section,
                   SUM(CASE WHEN kind = 'risk_pointer' THEN 0 ELSE tokens END),
                   MAX(kind = 'risk_pointer')
            FROM filing_chunks GROUP BY filing_id, section;
            """
        )
        db.execute("INSERT INTO settings VALUES ('chunk_tokens', ?)", (size.target,))
        db.execute("INSERT INTO chunks_fts (chunks_fts) VALUES ('rebuild')")
        db.execute(f"PRAGMA user_version = {INDEX_VERSION}")
        db.commit()
    finally:
        db.close()
    os.replace(partial, path)
    return path


def index_chunk_tokens(index: str | Path = DEFAULT_INDEX) -> int:
    """The chunk size the index was built with."""
    with _connect(index) as db:
        (value,) = db.execute("SELECT value FROM settings WHERE name = 'chunk_tokens'").fetchone()
    return value


def prepare_answer_context(
    messages: Sequence[Message],
    index: str | Path = DEFAULT_INDEX,
    ranker: Ranker | None = None,
    *,
    context_budget: int = CONTEXT_BUDGET_TOKENS,
) -> AnswerContext:
    """The Answer Context for the latest user message of a conversation.

    `messages` is the conversation so far, oldest first, ending with the user message
    to answer. Its earlier user messages supply the parts of the Query Scope the latest
    one does not name, and the last turns go into the prompt as history. `ranker`
    replaces the `bm25()` ranking inside the hard filters; None keeps it.
    `context_budget` is the tokens of Source text retrieved, split evenly across the
    Companies in scope.
    """
    if not messages or messages[-1].role != "user" or not messages[-1].content.strip():
        raise ValueError("the conversation must end with a non-empty user message")
    question = messages[-1].content
    with _connect(index) as db:
        known = _companies(db)
        # Each part of the Query Scope the question does not name comes from the most
        # recent earlier user message that named it (ADR 0003).
        inherited = inherit_scope(
            [m.content for m in messages if m.role == "user"], known, load_missing_companies()
        )
        who = inherited.companies_from
        companies, sector_phrases, missing = who.companies, who.sector_phrases, who.missing
        sections = inherited.sections_from.sections
        periods = inherited.period_from.periods
        # A risk or cybersecurity question (whose hint plans Risk Factors) that names no
        # time phrase and no Fiscal Period reads the latest Filings.
        window = inherited.period_from.window or (
            LATEST if RISK_FACTORS in sections and not periods else TimeWindow("all")
        )
        # The question as retrieval reads it: its own words, plus the words of the
        # message whose topic it inherits ("And what about Microsoft?").
        focus = "\n".join(n.text for n in inherited.asked)
        everything = _filings(db, [c.ticker for c in companies] or None)
        left_out = stale_filings_left_out(
            "\n".join(dict.fromkeys([who.text, question])),
            periods,
            (f for own in everything.values() for f in own),
        )
        filings = {
            ticker: [f for f in own if f.filing_id not in left_out]
            for ticker, own in everything.items()
        }
        scope = QueryScope(
            companies=companies,
            sector_phrases=sector_phrases,
            time_window=window,
            sections=sections,
            filings=tuple(
                f for c in companies for f in in_window(window, filings.get(c.ticker, []))
            ),
            periods=periods,
            change=is_change_question(focus),
            missing_companies=missing,
        )
        metrics, segments = inherited.metrics(
            n
            for own in _facts.segment_names(db, [c.ticker for c in companies]).values()
            for n in own
        )
        scope = replace(
            scope,
            metric=metrics[0] if metrics else None,
            metrics=metrics,
            segments=segments,
        )
        facts = _facts.lookup(db, companies, metrics, segments, scope.filings, scope.periods)
        fact_sources, rows = _facts_sources(db, facts)
        terms = _terms(*(n.terms for n in inherited.asked))
        every_word = _terms(*(n.words for n in inherited.asked))
        text_sources, searched = _sources(
            db,
            scope,
            filings,
            _Search(focus, terms, ranker, every_word if every_word != terms else None),
            context_budget,
            explicit=bool(left_out),
            first_number=len(fact_sources) + 1,
        )
        sources = fact_sources + text_sources
        scope = replace(scope, searched=searched)
    by_ticker = {c.ticker: c for c in known}
    covered = list(companies) or [by_ticker[t] for t in dict.fromkeys(s.ticker for s in sources)]
    coverage = tuple(
        CompanyCoverage(
            ticker=c.ticker,
            name=c.name,
            coverage=c.coverage,
            filings=tuple(everything.get(c.ticker, ())),
            in_scope=tuple(in_window(window, filings.get(c.ticker, []))),
            left_out=tuple(f for f in everything.get(c.ticker, ()) if f.filing_id in left_out),
        )
        for c in covered
    )
    gaps = coverage_gaps(focus, scope, coverage)
    rendered = render(sources, messages[:-1], question, scope, coverage, gaps, rows, facts.notes)
    return AnswerContext(
        query_scope=scope,
        sources=sources,
        prompt_version=PROMPT_VERSION,
        messages=tuple(PromptMessage(role, content) for role, content in rendered),
        coverage=coverage,
        coverage_gaps=gaps,
        financial_facts=rows,
        fact_notes=facts.notes,
    )


def _facts_sources(
    db: sqlite3.Connection, facts: _facts.Lookup
) -> tuple[tuple[Source, ...], tuple[FactRow, ...]]:
    """One Facts Source per Filing the Financial Facts come from, numbered from S1, and
    the table's rows citing their tags. A Facts Source's text states its reported rows,
    their year-on-year changes and the fourth quarters derived from it first, so a
    citation of any figure in the table leads to text that states it."""
    tags = {filing_id: f"S{n}" for n, (_, filing_id) in enumerate(facts.filings, start=1)}
    rows = _facts.with_tags(facts, tags)
    sources: list[Source] = []
    for number, (ticker, filing_id) in enumerate(facts.filings, start=1):
        filing = db.execute(
            "SELECT f.*, c.name FROM filings f JOIN companies c USING (ticker) "
            "WHERE f.filing_id = ?",
            (filing_id,),
        ).fetchone()
        tag = tags[filing_id]
        own = tuple(replace(r, sources=(tag,)) for r in facts.reported[filing_id])
        sources.append(
            Source(
                number=number,
                filing_id=filing_id,
                ticker=ticker,
                company=filing["name"],
                form_type=filing["form_type"],
                report_period=filing["report_period"],
                fiscal_period=filing["fiscal_period"],
                section=_facts.FACTS_SECTION,
                item=None,
                text=_facts.as_text(tag, own, rows),
                kind="facts",
                facts=own,
            )
        )
    return tuple(sources), rows


def _chunk_row(chunk: Chunk) -> tuple:
    return (
        chunk.ticker,
        chunk.company,
        chunk.sector,
        chunk.industry,
        chunk.coverage,
        chunk.kind,
        count_tokens(chunk.text),
        chunk.text,
    )


def _listing_row(chunk: Chunk) -> tuple:
    return (
        chunk.filing_id,
        chunk.form_type,
        chunk.report_period,
        chunk.fiscal_period,
        chunk.section,
        chunk.item,
        chunk.ordinal,
    )


class _connect:
    """A read-only connection to the index, closed on exit."""

    def __init__(self, index: str | Path):
        path = Path(index)
        if not path.exists():
            raise FileNotFoundError(f"no index at {path}; build it with `make index`")
        self.db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        (version,) = self.db.execute("PRAGMA user_version").fetchone()
        if version != INDEX_VERSION:
            self.db.close()
            raise RuntimeError(
                f"the index at {path} is version {version}, not {INDEX_VERSION}; "
                "rebuild it with `make index`"
            )

    def __enter__(self) -> sqlite3.Connection:
        return self.db

    def __exit__(self, *exc: object) -> None:
        self.db.close()


def _companies(db: sqlite3.Connection) -> list[ScopeCompany]:
    return [
        ScopeCompany(row["ticker"], row["name"], row["coverage"], row["sector"], row["industry"])
        for row in db.execute(
            "SELECT ticker, name, coverage, sector, industry FROM companies ORDER BY ticker"
        )
    ]


def _filings(db: sqlite3.Connection, tickers: list[str] | None) -> dict[str, list[ScopeFiling]]:
    """Each Company's Filings, oldest first: the named Companies', or every Company's."""
    where = f"WHERE ticker IN ({', '.join('?' * len(tickers))})" if tickers else ""
    by_ticker: dict[str, list[ScopeFiling]] = {}
    for row in db.execute(
        f"SELECT * FROM filings {where} ORDER BY ticker, report_period", tickers or ()
    ):
        by_ticker.setdefault(row["ticker"], []).append(ScopeFiling(*row))
    return by_ticker


def _terms(*words: Iterable[str]) -> str | None:
    """The words as an FTS5 query of quoted terms joined by OR, or None if there is no
    term. Every term is a run of letters and digits inside double quotes, so FTS5 reads
    it as a string to match, never as an operator or a column filter."""
    terms = dict.fromkeys(w for own in words for w in own)
    return " OR ".join(f'"{term}"' for term in terms) or None


@dataclass(frozen=True)
class _Search:
    """What retrieval searches for: the question, its FTS5 terms (None if it has none),
    the ranker, if any, that replaces `bm25()`, and the terms with the generic and hint
    words kept (None if they are the same terms)."""

    question: str
    terms: str | None
    ranker: Ranker | None = None
    every_word: str | None = None
    """Ranked after every chunk the terms match: the chunks matching only a generic or
    hint word ("risks" in Risk Factors) still fill the budget, but never outrank one
    matching the question's topic."""


@dataclass(frozen=True)
class _Plan:
    """Where retrieval may look: (Filing ID, Section) pairs, with a Section of None for
    a whole Filing, and the risk pointers to cite as they stand. `None` places means
    anywhere."""

    places: list[tuple[str, str | None]] | None
    pointers: list[tuple[str, str]]


def _plan(db: sqlite3.Connection, scope: QueryScope, filings: Sequence[ScopeFiling]) -> _Plan:
    """Apply the time window and Section hints to the Filings in scope.

    Each Filing is searched in its hinted Sections that have real text, or whole when it
    has none. On the risk route, a 10-Q whose Risk Factors only point back to the 10-K
    (or that has none) is not searched: its pointer is cited instead.
    """
    if scope.time_window.kind == "all" and not scope.sections:
        return _Plan(places=None, pointers=[])
    in_scope = [f.filing_id for f in filings]
    sizes: dict[str, dict[str, tuple[int, bool]]] = {}
    if scope.sections:
        for chunk in range(0, len(in_scope), 500):
            ids = in_scope[chunk : chunk + 500]
            for row in db.execute(
                f"SELECT * FROM sections WHERE filing_id IN ({', '.join('?' * len(ids))})", ids
            ):
                sizes.setdefault(row["filing_id"], {})[row["section"]] = (
                    row["tokens"],
                    bool(row["pointer"]),
                )
    risk_only = scope.sections == (RISK_FACTORS,)
    places: list[tuple[str, str | None]] = []
    pointers: list[tuple[str, str]] = []
    for filing in filings:
        if not scope.sections:
            places.append((filing.filing_id, None))
            continue
        own = sizes.get(filing.filing_id, {})
        hinted = [s for s in scope.sections if own.get(s, (0, False))[0] >= STUB_TOKENS]
        if RISK_FACTORS in scope.sections and own.get(RISK_FACTORS, (0, False))[1]:
            pointers.append((filing.filing_id, RISK_FACTORS))
        if hinted:
            places += [(filing.filing_id, s) for s in hinted]
        elif not (risk_only and filing.form_type == "10-Q"):
            places.append((filing.filing_id, None))
    return _Plan(places=places, pointers=pointers)


def _sources(
    db: sqlite3.Connection,
    scope: QueryScope,
    filings: dict[str, list[ScopeFiling]],
    search: _Search,
    context_budget: int,
    explicit: bool = False,
    first_number: int = 1,
) -> tuple[tuple[Source, ...], tuple[SearchedPlace, ...]]:
    """The numbered Sources for the Query Scope, and the places searched for them.
    `filings` holds the Filings retrieval may use; with `explicit`, some were left out
    (a stale Filing), so retrieval is held to the Filings listed even when the scope
    would otherwise search anywhere. A question that names only Companies missing from
    the Corpus gets no Sources and searches nowhere."""
    tickers: list[str | None] = [c.ticker for c in scope.companies]
    if not tickers:
        if scope.missing_companies:
            return (), ()
        tickers = [None]
    budget = context_budget // len(tickers)
    sources: list[Source] = []
    searched: list[SearchedPlace] = []
    for ticker in tickers:
        windowed = [
            f
            for t, own in filings.items()
            if ticker in (None, t)
            for f in in_window(scope.time_window, own)
        ]
        if not windowed:
            continue  # every Filing of the Company was left out
        plan = _plan(db, scope, windowed)
        if explicit and plan.places is None:
            plan = _Plan(places=[(f.filing_id, None) for f in windowed], pointers=[])
        owner = {f.filing_id: f.ticker for f in windowed}
        places = plan.places if plan.places is not None else [(f.filing_id, None) for f in windowed]
        searched += [SearchedPlace(owner[f], f, section) for f, section in places]
        pointers = _pointer_rows(db, plan.pointers)
        chosen: list[_Row] = []
        spent = sum(row["tokens"] for row in pointers)
        for row in _without_near_duplicates(_candidates(db, scope, ticker, search, plan)):
            if spent + row["tokens"] > budget:
                break
            spent += row["tokens"]
            chosen.append(row)
        sources += _group(chosen + pointers, first_number=first_number + len(sources))
    return tuple(sources), tuple(searched)


def _pointer_rows(db: sqlite3.Connection, pointers: list[tuple[str, str]]) -> list[sqlite3.Row]:
    """The risk-pointer chunks of these (Filing ID, Section) pairs, latest Filing first."""
    rows: list[sqlite3.Row] = []
    for filing_id, section in pointers:
        rows += db.execute(
            "SELECT * FROM filing_chunks "
            "WHERE filing_id = ? AND section = ? AND kind = 'risk_pointer'",
            (filing_id, section),
        ).fetchall()
    return sorted(rows, key=lambda r: r["report_period"], reverse=True)


def _ranked(
    db: sqlite3.Connection,
    ticker: str | None,
    search: _Search,
    places: list[tuple[str, str | None]] | None,
) -> list[sqlite3.Row]:
    """The Company's best chunks for the search within the planned places, best first,
    with one row for each planned Filing a chunk appears in, most recent first. Risk
    pointers ("no material changes since the 10-K") are cited by the risk route but
    never ranked (finding 16). The ranking is `bm25()`'s, or the search's ranker's."""
    if search.terms is None or places == []:
        return []
    company_filter = "AND c.ticker = :ticker" if ticker else ""
    place_filter = listing_filter = ""
    if places is not None:
        db.execute("CREATE TEMP TABLE IF NOT EXISTS places (filing_id TEXT, section TEXT)")
        db.execute("DELETE FROM temp.places")
        db.executemany("INSERT INTO temp.places VALUES (?, ?)", places)
        in_place = """EXISTS (
            SELECT 1 FROM temp.places p
            WHERE p.filing_id = f.filing_id AND (p.section IS NULL OR p.section = f.section)
        )"""
        place_filter = (
            f"AND EXISTS (SELECT 1 FROM chunk_filings f WHERE f.chunk_id = c.id AND {in_place})"
        )
        listing_filter = f"AND {in_place}"
    params = {"ticker": ticker, "limit": _CANDIDATES_PER_COMPANY}

    def matching(terms: str) -> list[int]:
        return [
            row["id"]
            for row in db.execute(
                f"""
                SELECT c.id
                FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
                WHERE chunks_fts MATCH :terms AND c.kind != 'risk_pointer' {company_filter}
                {place_filter}
                ORDER BY bm25(chunks_fts), c.id
                LIMIT :limit
                """,
                params | {"terms": terms},
            )
        ]

    ranking = matching(search.terms)
    if search.every_word is not None and len(ranking) < _CANDIDATES_PER_COMPANY:
        seen = set(ranking)
        ranking += [i for i in matching(search.every_word) if i not in seen][
            : _CANDIDATES_PER_COMPANY - len(ranking)
        ]
    if search.ranker is not None:
        eligible = tuple(
            row["id"]
            for row in db.execute(
                f"""
                SELECT c.id FROM chunks c
                WHERE c.kind != 'risk_pointer' {company_filter} {place_filter}
                ORDER BY c.id
                """,
                params,
            )
        )
        allowed = set(eligible)
        ranked = search.ranker(RankRequest(search.question, ticker, eligible, tuple(ranking)))
        ranking = [i for i in dict.fromkeys(ranked) if i in allowed][:_CANDIDATES_PER_COMPANY]
    db.execute("CREATE TEMP TABLE IF NOT EXISTS ranking (id INTEGER, position INTEGER)")
    db.execute("DELETE FROM temp.ranking")
    db.executemany(
        "INSERT INTO temp.ranking VALUES (?, ?)", ((i, n) for n, i in enumerate(ranking))
    )
    return db.execute(
        f"""
        SELECT f.*
        FROM temp.ranking r JOIN filing_chunks f ON f.id = r.id
        WHERE 1 {listing_filter}
        ORDER BY r.position, f.report_period DESC
        """
    ).fetchall()


_Row = Mapping[str, Any]


@dataclass
class _Candidate:
    """One retrieved chunk, cited from one of the Filings it appears in."""

    row: _Row
    """The chunk's listing in the cited Filing; on the change route, a new chunk's text
    is only its new paragraphs."""
    shingles: set[int]
    new: bool
    """Whether the chunk holds paragraphs new in the cited Filing (change route only)."""
    preference: tuple[bool, str]
    """Higher is preferred: from a period the question names, then more recent."""


def _candidates(
    db: sqlite3.Connection,
    scope: QueryScope,
    ticker: str | None,
    search: _Search,
    plan: _Plan,
) -> list[_Candidate]:
    """The ranked chunks, each cited from one Filing: on the change route the Filing it
    holds new paragraphs in, otherwise a Filing of a period the question names, else the
    most recent. On the change route the chunks holding new paragraphs rank first, cut
    down to those paragraphs."""
    listings: dict[int, list[sqlite3.Row]] = {}
    for row in _ranked(db, ticker, search, plan.places):
        listings.setdefault(row["id"], []).append(row)
    candidates = []
    for rows in listings.values():
        chosen = max(rows, key=lambda r: (_is_new(r, scope), _preference(r, scope)))
        row: dict[str, Any] = dict(chosen)
        new = _is_new(chosen, scope)
        if new:
            row |= {"text": row["new_text"], "tokens": count_tokens(row["new_text"])}
        candidates.append(
            _Candidate(
                row=row,
                shingles=shingles(row["text"]),
                new=new,
                preference=_preference(chosen, scope),
            )
        )
    if scope.change:
        candidates.sort(key=lambda c: not c.new)
    return candidates


def _is_new(row: sqlite3.Row, scope: QueryScope) -> bool:
    return scope.change and row["new_text"] is not None


def _preference(row: sqlite3.Row, scope: QueryScope) -> tuple[bool, str]:
    return names_period(row["fiscal_period"], scope.periods), row["report_period"]


def _without_near_duplicates(candidates: list[_Candidate]) -> list[_Row]:
    """The ranked chunks without near-duplicates, as rows to cite.

    A chunk is a near-duplicate when most of its text is in preferred chunks (more
    recent, or from a period the question names). Chunk boundaries shift between
    Filings, so its text is usually spread over two preferred chunks: what is measured
    is how much of it the preferred chunks hold together. It gives up its place in the
    ranking to the preferred chunk sharing the most of it. On the change route new
    paragraphs are kept, since when they appeared is the answer.
    """
    covered = [0] * len(candidates)
    union: set[int] = set()
    by_preference = sorted(
        range(len(candidates)), key=lambda i: candidates[i].preference, reverse=True
    )
    group: list[int] = []
    for i in [*by_preference, None]:
        if group and (i is None or candidates[i].preference != candidates[group[0]].preference):
            for j in group:
                union |= candidates[j].shingles
            group = []
        if i is not None:
            covered[i] = len(candidates[i].shingles & union)
            group.append(i)

    def is_duplicate(i: int) -> bool:
        c = candidates[i]
        return not c.new and bool(c.shingles) and covered[i] >= NEAR_DUPLICATE * len(c.shingles)

    def kept(i: int) -> int:
        while is_duplicate(i):
            c = candidates[i]
            i = max(
                (j for j, d in enumerate(candidates) if d.preference > c.preference),
                key=lambda j: len(c.shingles & candidates[j].shingles),
            )
        return i

    placed: dict[int, None] = {}
    for i in range(len(candidates)):
        placed.setdefault(kept(i))
    return [candidates[i].row for i in placed]


def _group(rows: Sequence[_Row], first_number: int) -> list[Source]:
    """One Source per (Filing, Section), numbered in order of each group's best chunk."""
    groups: dict[tuple[str, str], list[_Row]] = {}
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
                text=GAP.join(r["text"] for r in in_order),
            )
        )
    return sources


if __name__ == "__main__":
    import argparse

    from edgar_rag.corpus import load_corpus

    parser = argparse.ArgumentParser(description="Build the retrieval index from the Corpus.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="where to write it")
    parser.add_argument(
        "--chunk-tokens", type=int, default=CHUNK_TOKENS, help="the chunk size (ADR 0010)"
    )
    args = parser.parse_args()
    path = build_index(load_corpus(), args.index, chunk_tokens=args.chunk_tokens)
    print(f"Index of {args.chunk_tokens}-token chunks written to {path}")
