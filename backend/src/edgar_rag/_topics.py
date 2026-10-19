"""The topic table, internal to the retrieval seam: the Filings' own wording for common
topics, added to a question's search terms.

A question names a topic in its own words ("regulatory risks", "supply chain"), and a
Filing often states it in others ("the Inflation Reduction Act", "sole source"), so a
passage worded differently from the question can rank below passages that merely share
its words. Each topic is recognised by phrases in the question and adds search terms in
the Filings' wording. The added terms are ORed with the question's own, so they widen
the match and never narrow it, and a question with no topic phrase searches exactly as
before.

A topic may be held to Companies of some Sectors: drug-pricing regulation is added for
health care Companies only, so "What regulatory risks does JPMorgan face?" searches as
before. Retrieval asks for each Company's terms with that Company's Sector
(`added_terms`).

Every term comes from the Corpus, never from a Golden Set or Brief Suite evidence quote:
each `Wording` names a Filing and the phrase of it that uses the term, and a test checks
that every term matches a chunk of the full index and that no phrase is copied from an
evidence quote. The table is general SEC vocabulary, kept small so it can be reviewed;
it must not grow into a list fitted to the evaluation's cases.

Rule-based, standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["TOPICS", "Topic", "Wording", "added_terms"]


@dataclass(frozen=True)
class Wording:
    """One added search term, and where the Filings use it."""

    term: str
    """Searched as one FTS5 phrase: a few words, letters and digits only."""
    filing_id: str
    """A Filing that uses the term."""
    phrase: str
    """The phrase of that Filing the term comes from, word for word."""


@dataclass(frozen=True)
class Topic:
    """A topic: the question phrases that name it, the Sectors of the Companies it is
    added for (None for every Company) and the Filings' wording for it."""

    name: str
    pattern: re.Pattern[str]
    sectors: frozenset[str] | None
    wording: tuple[Wording, ...]


TOPICS: tuple[Topic, ...] = (
    Topic(
        # Drug makers state their regulatory risk as the IRA's Medicare price negotiation,
        # government price setting and the 340B program, words a question about
        # "regulation" or "drug pricing" seldom uses.
        name="drug-pricing regulation",
        pattern=re.compile(
            r"\bregulat\w*|\bdrug\s+pric\w*|\bpric(?:e|es|ing)\s+(?:controls?|regulation)\b",
            re.I,
        ),
        sectors=frozenset({"Health Care"}),
        wording=(
            Wording(
                "Inflation Reduction Act",
                "LLY_10-K_2025-12-31",
                "government enacted the Inflation Reduction Act of 2022 (IRA).",
            ),
            Wording(
                "IRA",
                "UNH_10-Q_2025-03-31",
                "the IRA-driven impacts on Medicare Part D plans and elevated care patterns.",
            ),
            Wording(
                "price negotiation",
                "PFE_10-Q_2025-03-30",
                "Eliquis was among the first ten medicines subject to the Medicare Drug Price"
                " Negotiation Program.",
            ),
            Wording(
                "government price setting",
                "MRK_10-K_2024-12-31",
                "Government price setting may also impact pricing in the private market"
                " negatively affecting the Company’s performance.",
            ),
            Wording(
                "price controls",
                "MRK_10-K_2024-12-31",
                "These types of revenue generating or cost saving proposals include additional"
                " direct price controls.",
            ),
            Wording(
                "340B",
                "LLY_10-K_2025-12-31",
                "Changes to the 340B program or the Medicaid programs could have a material"
                " adverse impact on our business.",
            ),
        ),
    ),
    Topic(
        name="supply chain",
        pattern=re.compile(r"\bsupply[\s-]+chains?\b|\bsuppliers?\b|\bsourcing\b", re.I),
        sectors=None,
        wording=(
            Wording(
                "suppliers",
                "AAPL_10-K_2022-09-24",
                "The Company purchases these components directly from suppliers.",
            ),
            Wording(
                "sole source",
                "ORCL_10-K_2025-05-31",
                "However, we do rely on sole sources for certain hardware components.",
            ),
            Wording(
                "single source",
                "LLY_10-K_2025-12-31",
                "However, certain materials are procured from a single source.",
            ),
            Wording(
                "contract manufacturers",
                "MSFT_10-K_2022-06-30",
                "Our devices are primarily manufactured by third-party contract manufacturers.",
            ),
            Wording(
                "shortages",
                "INTC_10-K_2025-12-27",
                "supply constraints, labor shortages and other adverse market conditions;",
            ),
        ),
    ),
    Topic(
        name="competition",
        pattern=re.compile(r"\bcompet\w*|\brivals?\b", re.I),
        sectors=None,
        wording=(
            Wording(
                "competitors",
                "GS_10-K_2024-12-31",
                "competitors, could impact our ability to compete effectively.",
            ),
            Wording(
                "compete",
                "MA_10-K_2025-12-31",
                "We compete with ATM and point-of-sale debit networks.",
            ),
            Wording(
                "market share",
                "PG_10-K_2025-06-30",
                "Global market share of the Beauty segment decreased 0.3 points.",
            ),
            Wording(
                "new entrants",
                "LMT_10-K_2025-12-31",
                "We are facing increased competition from new entrants, startups and"
                " non-traditional defense contractors.",
            ),
        ),
    ),
    Topic(
        name="cybersecurity",
        pattern=re.compile(
            r"\bcyber\w*|\bdata\s+breach\w*|\binformation\s+security\b|\bransomware\b", re.I
        ),
        sectors=None,
        wording=(
            Wording(
                "cyberattacks",
                "TGT_10-K_2025-02-01",
                "Cyberattacks are being carried out by groups and individuals with a wide range"
                " of expertise and motives.",
            ),
            Wording(
                "security breaches",
                "T_10-K_2025-12-31",
                "the effect of security breaches related to the network or customer information;",
            ),
            Wording(
                "ransomware",
                "IBM_10-K_2024-12-31",
                "the loss of access to critical data or systems through ransomware, crypto"
                " mining, destructive attacks or other means;",
            ),
            Wording(
                "malware",
                "MSFT_10-Q_2024-12-31",
                "Malicious actors may employ the supply chain to introduce malware through"
                " software updates or compromised supplier accounts or hardware.",
            ),
            Wording(
                "unauthorized access",
                "CVX_10-K_2024-12-31",
                "attempts to gain unauthorized access to our data and systems;",
            ),
            Wording(
                "security incidents",
                "UNH_10-K_2022-12-31",
                "Our facilities and services may also be vulnerable to security incidents or"
                " security attacks;",
            ),
            Wording(
                "data breaches",
                "CVX_10-K_2024-12-31",
                "data breaches by employees, insiders or others with authorized access;",
            ),
        ),
    ),
)


def added_terms(text: str, sector: str | None) -> tuple[str, ...]:
    """The search terms the topic table adds for a question's text, for a Company of
    `sector` (None when the question names no Company): every term of every topic the
    text names and the Sector allows, each once, in table order."""
    terms = [
        w.term
        for topic in TOPICS
        if topic.pattern.search(text)
        and (topic.sectors is None or (sector is not None and sector in topic.sectors))
        for w in topic.wording
    ]
    return tuple(dict.fromkeys(terms))
