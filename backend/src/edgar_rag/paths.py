"""Where the repository's files live, defined once for every backend package.

Every module that reads or writes under `data/` (the Corpus, the curated reference
tables, the Golden Set and the gitignored derived files) builds its path from
`DATA_DIR` here, never from its own file location.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["DATA_DIR", "DERIVED_DIR", "REPO_ROOT"]

REPO_ROOT = Path(__file__).resolve().parents[3]
"""The repository root: `backend/src/edgar_rag/` is three levels below it."""

DATA_DIR = REPO_ROOT / "data"
"""The data directory: the Corpus, `reference/`, `eval/` and `derived/`."""

DERIVED_DIR = DATA_DIR / "derived"
"""Files derived from the Corpus and the evaluation (gitignored): the index, caches,
logs and reports."""
