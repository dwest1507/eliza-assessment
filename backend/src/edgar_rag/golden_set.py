"""The Golden Set: the labelled questions retrieval and answers are evaluated against.

The cases live in `data/eval/golden_set.json`, written before any retrieval Arm or prompt
ran. Each case is a question (with a scripted conversation before it, for follow-ups),
its question type, the (Filing ID, Section) pairs that should reach the Answer Call, the
Required Facts an answer must state (each with an evidence quote from its Section) and
the Coverage Gaps it must state. Six cases are the front-end's starter prompts.

Each Required Fact has a tier (`TIERS`): `must_state`, which any good answer covers and
Fact Recall is scored on, or `detail`, reported as detail recall but never counted as a
miss. Version 1's facts name no tier and load as `must_state`; later versions must name
one. Every case has a must-state fact unless it expects only Coverage Gaps.

Version 1's cases are split dev/holdout by a hash of each case id (`assign_splits`), so
prompt and Arm choices are tuned on dev and the holdout is scored once per final setup,
never to choose. Version 2 (`data/eval/golden_set_v2.json`, `DEFAULT_GOLDEN_SET_V2`)
records each case's split instead (`SPLIT_RULE_V2`): `dev`, `holdout`, or `pending` while
its new cases are drafted. A harness runs version 1 unless named another file, and
refuses a set with a pending case (`GoldenSet.require_frozen`).

The Brief Suite (`data/eval/brief_suite.json`, `load_brief_suite`) holds the brief's
example questions and variants of them, outside the split: a must-pass check that may be
tuned on. Its cases use the same schema with no split, every fact names its tier, and a
case rewritten from a version 1 case records which (`replaces`), and a variant of one of
the brief's questions names that question's case (`variant_of`). No id is in both it and
either Golden Set version.
Starter prompts may come from either (`starter_cases`): a Brief Suite case's starter
takes the place of the one on the case it replaces.

`load_golden_set` and `load_brief_suite` check the schema and raise `ValueError` on any
problem. Checking the labels against the Corpus is left to the tests, so loading needs
no Corpus.
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
    "DEFAULT_BRIEF_SUITE",
    "DEFAULT_GOLDEN_SET",
    "DEFAULT_GOLDEN_SET_V2",
    "QUESTION_TYPES",
    "SPLIT_RULE",
    "SPLIT_RULE_V2",
    "TIERS",
    "BriefSuite",
    "CoverageGapLabel",
    "ExpectedSource",
    "GoldenCase",
    "GoldenSet",
    "Message",
    "RequiredFact",
    "Starter",
    "load_brief_suite",
    "load_golden_set",
    "normalise_whitespace",
    "assign_splits",
    "starter_cases",
]

DEFAULT_GOLDEN_SET = DATA_DIR / "eval" / "golden_set.json"
"""Golden Set version 1, the harnesses' default until version 2's split is frozen."""

DEFAULT_GOLDEN_SET_V2 = DATA_DIR / "eval" / "golden_set_v2.json"

DEFAULT_BRIEF_SUITE = DATA_DIR / "eval" / "brief_suite.json"

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

Split = Literal["dev", "holdout", "pending"]
"""`pending` only in version 2 and later, and only until the split is frozen."""

Tier = Literal["must_state", "detail"]

TIERS: tuple[Tier, ...] = ("must_state", "detail")
"""A Required Fact's tier. Fact Recall is the share of must-state facts stated; detail
recall, reported beside it, the share of details."""

SPLIT_RULE = (
    "Sort the case ids by the SHA-256 hex digest of each id (UTF-8). The first third, "
    "rounded to the nearest whole case, are holdout; the rest are dev."
)
"""The split rule, also written in the file. Ranking by hash rather than thresholding
each hash keeps the holdout at exactly a third of a set this small. Version 1 only."""

SPLIT_RULE_V2 = (
    "Each case records its split, and no case ever moves. Version 1's cases rewritten "
    "here keep their ids and are dev. New cases are pending until all of them exist; "
    "then the 20 whose ids have the lowest SHA-256 hex digests (UTF-8) are holdout and "
    "the rest dev. A run refuses while any case is pending."
)
"""The split rule from version 2 on (ADR 0012), also written in the file."""


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
    tier: Tier = "must_state"
    """`must_state` (scored as Fact Recall) or `detail` (reported as detail recall)."""


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
    split: Split | None
    """None for a Brief Suite case, which is outside the split."""
    starter: Starter | None
    tags: tuple[str, ...]
    notes: str
    replaces: str | None = None
    """For a Brief Suite case rewritten from a Golden Set version 1 case, that case's id,
    so saved version 1 answers can be matched to the rewritten facts."""
    variant_of: str | None = None
    """For a Brief Suite variant of one of the brief's questions (a rephrasing, other
    Companies, another angle or a follow-up), the id of that question's case."""


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

    def require_frozen(self) -> None:
        """Raise ValueError if any case's split is still pending: a harness runs a set
        only once its split is frozen."""
        pending = [c.id for c in self.split("pending")]
        if pending:
            raise ValueError(
                f"Golden Set version {self.version} has {len(pending)} pending case(s), so "
                f"its split is not frozen yet: {', '.join(pending)}"
            )


@dataclass(frozen=True)
class BriefSuite:
    version: int
    cases: tuple[GoldenCase, ...]

    def starters(self) -> list[GoldenCase]:
        """The starter-prompt cases, in the order the front-end shows them."""
        return sorted((c for c in self.cases if c.starter), key=lambda c: c.starter.order)


def starter_cases(golden_set: GoldenSet, brief_suite: BriefSuite) -> list[GoldenCase]:
    """The front-end's starter prompts, in order: the Brief Suite's, and the Golden Set's
    whose case no Brief Suite case replaces."""
    replaced = {c.replaces for c in brief_suite.cases}
    golden = [c for c in golden_set.starters() if c.id not in replaced]
    return sorted([*golden, *brief_suite.starters()], key=lambda c: c.starter.order)


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
    version = _field(data, "version", int, "Golden Set")
    cases = tuple(_case(raw, version) for raw in _field(data, "cases", list, "Golden Set"))
    return GoldenSet(
        version=version,
        split_rule=_field(data, "split_rule", str, "Golden Set"),
        cases=cases,
    )


def load_brief_suite(
    path: str | Path = DEFAULT_BRIEF_SUITE,
    golden_sets: Iterable[str | Path] = (DEFAULT_GOLDEN_SET, DEFAULT_GOLDEN_SET_V2),
) -> BriefSuite:
    """Read and validate the Brief Suite file. Raises ValueError on a schema problem, on an
    id that is also a case's in one of `golden_sets`, or on a `replaces` naming no case
    there, or on a `variant_of` naming no Brief Suite case that replaces one."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    version = _field(data, "version", int, "Brief Suite")
    cases = tuple(
        _case(raw, version, brief=True) for raw in _field(data, "cases", list, "Brief Suite")
    )
    golden_ids = {c.id for p in golden_sets for c in load_golden_set(p).cases}
    for case in cases:
        if case.id in golden_ids:
            raise ValueError(f"case {case.id}: the id is also a Golden Set case's")
        if case.replaces is not None and case.replaces not in golden_ids:
            raise ValueError(f"case {case.id}: replaces {case.replaces!r}, no Golden Set case")
    brief_questions = {c.id for c in cases if c.replaces is not None}
    for case in cases:
        if case.variant_of is not None and case.variant_of not in brief_questions:
            raise ValueError(
                f"case {case.id}: variant_of {case.variant_of!r}, no brief question's case"
            )
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Brief Suite: case ids are not unique")
    return BriefSuite(version=version, cases=cases)


def _case(raw: dict, version: int, *, brief: bool = False) -> GoldenCase:
    case_id = _field(raw, "id", str, "case")
    where = f"case {case_id}"
    question_type = _field(raw, "question_type", str, where)
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"{where}: unknown question_type {question_type!r}")
    if brief:
        if "split" in raw:
            raise ValueError(f"{where}: a Brief Suite case is outside the split and has none")
        split = None
    else:
        split = _field(raw, "split", str, where)
        allowed = ("dev", "holdout") if version == 1 else ("dev", "holdout", "pending")
        if split not in allowed:
            raise ValueError(f"{where}: split must be one of {allowed}, not {split!r}")
    replaces = raw.get("replaces")
    if replaces is not None and (not brief or not isinstance(replaces, str)):
        raise ValueError(f"{where}: only a Brief Suite case replaces one, by its id")
    variant_of = raw.get("variant_of")
    if variant_of is not None and (not brief or not isinstance(variant_of, str)):
        raise ValueError(f"{where}: only a Brief Suite case is a variant of one, by its id")

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
            tier=_tier(f, version if not brief else None, where),
        )
        for f in _field(raw, "required_facts", list, where)
    )
    gaps = tuple(_gap(g, where) for g in _field(raw, "expected_coverage_gaps", list, where))
    if not any(f.tier == "must_state" for f in facts) and (facts or not gaps):
        raise ValueError(
            f"{where}: no must-state Required Fact, and it does not expect only Coverage Gaps"
        )
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
        replaces=replaces,
        variant_of=variant_of,
    )


def _role(message: dict, where: str) -> Literal["user", "assistant"]:
    role = _field(message, "role", str, where)
    if role not in ("user", "assistant"):
        raise ValueError(f"{where}: history role must be 'user' or 'assistant', not {role!r}")
    return role


def _tier(fact: dict, version: int | None, where: str) -> Tier:
    """The fact's tier. Golden Set version 1 predates tiers, so its facts are all
    must-state; every other file's facts (`version` None for the Brief Suite) name one."""
    if version == 1 and "tier" not in fact:
        return "must_state"
    tier = _field(fact, "tier", str, where)
    if tier not in TIERS:
        raise ValueError(f"{where}: a Required Fact's tier must be one of {TIERS}, not {tier!r}")
    return tier


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
