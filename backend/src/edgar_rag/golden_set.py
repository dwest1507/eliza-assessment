"""The Golden Set: the labelled questions retrieval and answers are evaluated against.

The cases live in `data/eval/golden_set.json`, written before any retrieval Arm or prompt
ran. Each case is a question (with a scripted conversation before it, for follow-ups),
its question type, the (Filing ID, Section) pairs that should reach the Answer Call, the
Required Facts an answer must state (each with an evidence quote from its Section) and
the Coverage Gaps it must state. Six cases are the front-end's starter prompts.

Cases are split dev/holdout by a hash of each case id (`assign_splits`), so prompt and
Arm choices are tuned on dev and the holdout is scored once per final setup, never to
choose.

`load_golden_set` checks the schema and raises `ValueError` on any problem. Checking the
labels against the Corpus is left to the tests, so loading needs no Corpus.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from edgar_rag.paths import DATA_DIR

__all__ = [
    "COVERAGE_GAP_KINDS",
    "DEFAULT_GOLDEN_SET",
    "QUESTION_TYPES",
    "SPLIT_RULE",
    "CoverageGapLabel",
    "ExpectedSource",
    "GoldenCase",
    "GoldenSet",
    "Message",
    "RequiredFact",
    "Starter",
    "load_golden_set",
    "normalise_whitespace",
    "assign_splits",
]

DEFAULT_GOLDEN_SET = DATA_DIR / "eval" / "golden_set.json"

QUESTION_TYPES = (
    "risk",
    "figure_trend",
    "sector",
    "outlook",
    "missing_company",
    "stale_filing",
)
"""`risk` covers risk comparisons across Companies and single-Company risk questions,
including the Legal Proceedings and Market Risk Sections."""

COVERAGE_GAP_KINDS = (
    "snapshot_trend",
    "missing_company",
    "stale_filing",
    "no_guidance",
    "periods_differ",
)
"""The Coverage Gaps of EDA notebook section 8.6 that an answer must state in words."""

Split = Literal["dev", "holdout"]

SPLIT_RULE = (
    "Sort the case ids by the SHA-256 hex digest of each id (UTF-8). The first third, "
    "rounded to the nearest whole case, are holdout; the rest are dev."
)
"""The split rule, also written in the file. Ranking by hash rather than thresholding
each hash keeps the holdout at exactly a third of a set this small."""


@dataclass(frozen=True)
class Message:
    """One earlier turn of a scripted conversation."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class ExpectedSource:
    """A (Filing ID, Section) pair that should reach the Answer Call."""

    filing_id: str
    section: str


@dataclass(frozen=True)
class RequiredFact:
    """A self-contained sentence an answer must state, and where the Corpus says it."""

    fact: str
    filing_id: str
    section: str
    evidence: str
    """A quote from the Section, found word for word in it (up to whitespace)."""


@dataclass(frozen=True)
class CoverageGapLabel:
    """A Coverage Gap the answer must state, and the Companies it is about: tickers for
    Companies in the Corpus, names for those missing from it."""

    kind: str
    companies: tuple[str, ...]


@dataclass(frozen=True)
class Starter:
    """How the front-end shows a starter prompt: its position and button label."""

    order: int
    label: str


@dataclass(frozen=True)
class GoldenCase:
    id: str
    question: str
    """The latest user message: the question the Answer Call answers."""
    history: tuple[Message, ...]
    """Earlier turns, oldest first, ending with an assistant answer. Empty for a
    single-turn case."""
    question_type: str
    expected_sources: tuple[ExpectedSource, ...]
    required_facts: tuple[RequiredFact, ...]
    expected_coverage_gaps: tuple[CoverageGapLabel, ...]
    split: Split
    starter: Starter | None
    tags: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class GoldenSet:
    version: int
    split_rule: str
    cases: tuple[GoldenCase, ...]

    def starters(self) -> list[GoldenCase]:
        """The starter-prompt cases, in the order the front-end shows them."""
        return sorted((c for c in self.cases if c.starter), key=lambda c: c.starter.order)

    def split(self, split: Split) -> list[GoldenCase]:
        return [c for c in self.cases if c.split == split]


def assign_splits(case_ids: Iterable[str]) -> dict[str, Split]:
    """Each case id's split under `SPLIT_RULE`. Depends only on the ids."""
    ranked = sorted(case_ids, key=lambda i: hashlib.sha256(i.encode("utf-8")).hexdigest())
    holdout = round(len(ranked) / 3)
    return {case_id: "holdout" if rank < holdout else "dev" for rank, case_id in enumerate(ranked)}


def normalise_whitespace(text: str) -> str:
    """Collapse every run of whitespace (including non-breaking spaces and newlines) to
    one space. Evidence quotes are compared after this and nothing else."""
    return re.sub(r"\s+", " ", text).strip()


def load_golden_set(path: str | Path = DEFAULT_GOLDEN_SET) -> GoldenSet:
    """Read and validate the Golden Set file. Raises ValueError on a schema problem."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = tuple(_case(raw) for raw in _field(data, "cases", list, "Golden Set"))
    return GoldenSet(
        version=_field(data, "version", int, "Golden Set"),
        split_rule=_field(data, "split_rule", str, "Golden Set"),
        cases=cases,
    )


def _case(raw: dict) -> GoldenCase:
    case_id = _field(raw, "id", str, "case")
    where = f"case {case_id}"
    question_type = _field(raw, "question_type", str, where)
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"{where}: unknown question_type {question_type!r}")
    split = _field(raw, "split", str, where)
    if split not in ("dev", "holdout"):
        raise ValueError(f"{where}: split must be 'dev' or 'holdout', not {split!r}")

    history = tuple(
        Message(role=_role(m, where), content=_field(m, "content", str, where))
        for m in _field(raw, "history", list, where)
    )
    sources = tuple(
        ExpectedSource(_field(s, "filing_id", str, where), _field(s, "section", str, where))
        for s in _field(raw, "expected_sources", list, where)
    )
    facts = tuple(
        RequiredFact(
            fact=_field(f, "fact", str, where),
            filing_id=_field(f, "filing_id", str, where),
            section=_field(f, "section", str, where),
            evidence=_field(f, "evidence", str, where),
        )
        for f in _field(raw, "required_facts", list, where)
    )
    gaps = tuple(_gap(g, where) for g in _field(raw, "expected_coverage_gaps", list, where))
    starter_raw = raw.get("starter")
    starter = (
        Starter(_field(starter_raw, "order", int, where), _field(starter_raw, "label", str, where))
        if starter_raw is not None
        else None
    )
    return GoldenCase(
        id=case_id,
        question=_field(raw, "question", str, where),
        history=history,
        question_type=question_type,
        expected_sources=sources,
        required_facts=facts,
        expected_coverage_gaps=gaps,
        split=split,
        starter=starter,
        tags=tuple(raw.get("tags", ())),
        notes=raw.get("notes", ""),
    )


def _role(message: dict, where: str) -> Literal["user", "assistant"]:
    role = _field(message, "role", str, where)
    if role not in ("user", "assistant"):
        raise ValueError(f"{where}: history role must be 'user' or 'assistant', not {role!r}")
    return role


def _gap(raw: dict, where: str) -> CoverageGapLabel:
    kind = _field(raw, "kind", str, where)
    if kind not in COVERAGE_GAP_KINDS:
        raise ValueError(f"{where}: unknown Coverage Gap kind {kind!r}")
    companies = _field(raw, "companies", list, where)
    if not companies:
        raise ValueError(f"{where}: Coverage Gap {kind!r} names no Company")
    return CoverageGapLabel(kind=kind, companies=tuple(companies))


def _field(raw: object, name: str, kind: type, where: str):
    if not isinstance(raw, dict) or name not in raw:
        raise ValueError(f"{where}: missing field {name!r}")
    value = raw[name]
    if not isinstance(value, kind) or isinstance(value, bool) and kind is int:
        raise ValueError(f"{where}: field {name!r} must be {kind.__name__}")
    return value
