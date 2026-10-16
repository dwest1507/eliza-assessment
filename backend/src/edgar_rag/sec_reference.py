"""SEC XBRL company-facts data, used only to evaluate Financial Facts extraction.

The SEC's company-facts API publishes every XBRL fact a Company has filed. The EDA
compares the Financial Facts extracted from the Corpus with it to measure extraction
accuracy. It is an evaluation reference and nothing more: no answer is ever built from
it, and nothing outside the EDA reads it.

The data is fetched once per Company (`make sec-facts`) and cached under
`data/derived/sec_companyfacts/`, which is gitignored. The SEC asks every automated
client to identify itself with a User-Agent naming the requester and a contact email,
so fetching requires the `SEC_USER_AGENT` environment variable, e.g.
`SEC_USER_AGENT=Your Name you@example.com`. This module reads it from the environment
only; locally it comes from the gitignored `backend/.env`, which the Makefile loads.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections.abc import Iterable
from datetime import date
from pathlib import Path

__all__ = [
    "COMPANY_FACTS_URL",
    "DEFAULT_CACHE_DIR",
    "USER_AGENT_ENV",
    "UserAgentMissing",
    "fetch_company_facts",
    "load_company_facts",
]

COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "derived" / "sec_companyfacts"
USER_AGENT_ENV = "SEC_USER_AGENT"
INDEX_FILE = "index.json"

# The SEC allows at most 10 requests a second; stay well under it.
_REQUEST_INTERVAL_SECONDS = 0.25

_USER_AGENT_HELP = (
    f"{USER_AGENT_ENV} is not set. The SEC requires every request to carry a User-Agent "
    "naming you and a contact email. Copy backend/.env.example to backend/.env and "
    "fill it in (the Makefile reads it), or export it in your shell."
)


class UserAgentMissing(RuntimeError):
    """Raised when the SEC User-Agent is not configured."""

    def __init__(self) -> None:
        super().__init__(_USER_AGENT_HELP)


def fetch_company_facts(
    ciks: Iterable[str],
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    user_agent: str | None = None,
) -> list[Path]:
    """Download the company-facts JSON for each CIK into `cache_dir`.

    The User-Agent comes from `user_agent`, else the `SEC_USER_AGENT` environment
    variable; without one nothing is fetched. An `index.json` listing the CIKs and the
    retrieval date is written last, so its presence means the cache is complete.
    """
    user_agent = user_agent or os.environ.get(USER_AGENT_ENV, "").strip()
    if not user_agent:
        raise UserAgentMissing()

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, cik in enumerate(sorted(set(ciks))):
        if i:
            time.sleep(_REQUEST_INTERVAL_SECONDS)
        url = COMPANY_FACTS_URL.format(cik=cik)
        request = urllib.request.Request(
            url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
        json.loads(payload)  # fail here, not later, if the SEC sent something else
        path = cache_dir / f"CIK{cik}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(payload)
        tmp.replace(path)
        paths.append(path)

    index = {
        "source": COMPANY_FACTS_URL,
        "retrieved": date.today().isoformat(),
        "ciks": [p.stem.removeprefix("CIK") for p in paths],
        "purpose": "evaluation reference only; never an answer source",
    }
    (cache_dir / INDEX_FILE).write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return paths


def load_company_facts(cik: str, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> dict:
    """The cached company-facts JSON for one CIK. Run `make sec-facts` first."""
    path = Path(cache_dir) / f"CIK{cik}.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; run `make sec-facts` to fetch it")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    """Fetch company-facts for every Tracked Company in the Corpus."""
    from edgar_rag.corpus import load_corpus

    ciks = {f.cik for f in load_corpus() if f.coverage == "tracked"}
    try:
        paths = fetch_company_facts(ciks)
    except UserAgentMissing as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Fetched SEC company-facts for {len(paths)} Companies into {DEFAULT_CACHE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
