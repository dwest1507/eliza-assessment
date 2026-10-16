"""The Corpus seam: load the whole Corpus, or one Filing, as Filing objects.

At this stage only the header metadata is parsed, exactly as written. Fields
missing from the header (e.g. Report Period on some Filings) are left as None.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[3] / "data" / "edgar_corpus"

_HEADER_END = "=" * 60


@dataclass(frozen=True)
class Filing:
    """One 10-K or 10-Q submitted to the SEC by a single Company."""

    company: str
    ticker: str
    cik: str
    form_type: str
    filing_date: date
    report_period: date | None
    calendar_quarter: str | None
    source_url: str
    path: Path


def load_corpus(corpus_dir: str | Path = DEFAULT_CORPUS_DIR) -> list[Filing]:
    """Load every Filing listed in the Corpus manifest, in manifest order."""
    corpus_dir = Path(corpus_dir)
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    return [load_filing(corpus_dir / name) for name in manifest["files"]]


def load_filing(path: str | Path) -> Filing:
    """Load one Filing from its file in the Corpus."""
    path = Path(path)
    header = _read_header(path)
    report_period = header.get("Report Period")
    return Filing(
        company=header["Company"],
        ticker=header["Ticker"],
        cik=header["CIK"],
        form_type=header["Filing Type"].split(" ", 1)[0],
        filing_date=date.fromisoformat(header["Filing Date"]),
        report_period=date.fromisoformat(report_period) if report_period else None,
        calendar_quarter=header.get("Quarter"),
        source_url=header["URL"],
        path=path,
    )


def _read_header(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith(_HEADER_END):
                return fields
            key, sep, value = line.partition(":")
            if sep:
                fields[key.strip()] = value.strip()
    raise ValueError(f"{path.name}: header separator not found")
