# SEC Filings RAG

A question-answering system for a private equity Client. It answers natural-language business questions ("How has NVIDIA's revenue and growth outlook changed over the last two years?") with answers grounded in, and cited to, a Corpus of SEC EDGAR 10-K and 10-Q Filings. Indexing and retrieval run beforehand; the answer itself comes from **one LLM request**, the Answer Call.

This repo is a take-home assessment for a Forward Deployed Engineer (AI Engineering) role. The brief is in [`docs/AI-RAG Assessment.md`](docs/AI-RAG%20Assessment.md). Domain terms used throughout (Filing, Corpus, Company, Tracked Company, Report Period, Financial Fact, Answer Call...) are defined in [`CONTEXT.md`](CONTEXT.md).

## Status

The work runs in phases. The exploratory data analysis (EDA) phase is complete; retrieval, the prompt and the front-end come next.

| Deliverable (from the brief) | Status | Where |
|---|---|---|
| README with setup and run instructions | Done | This file |
| Indexing and retrieval code | Partly done: Corpus loading, cleaning, Section splitting and Financial Facts extraction are built and tested. Chunking, the index and retrieval are next. | [`backend/src/edgar_rag/`](backend/src/edgar_rag/) |
| Log of prompt iterations | Not started | Planned with the Answer Call |
| Final prompt template | Not started | Planned with the Answer Call |
| Front-end | Not started | [`frontend/`](frontend/) (reserved for Next.js) |
| Example request, ready to execute | Not started | Planned with the API |
| Notes on how quality was evaluated | Partly done: Financial Facts extraction is measured against SEC XBRL data. Retrieval and answer evaluation are next. | [`docs/findings.md`](docs/findings.md) (findings 21–24), notebook analysis 7 |
| Documented assumptions and decisions | Done for the EDA | [`docs/findings.md`](docs/findings.md), [`docs/assumptions.md`](docs/assumptions.md), [`docs/adr/`](docs/adr/) |

## What the EDA found

The full write-up, each entry as Finding → Implication → Design decision, is [`docs/findings.md`](docs/findings.md); the evidence is in the executed notebook [`backend/notebooks/eda.ipynb`](backend/notebooks/eda.ipynb). In brief:

- **The Corpus is not what the brief describes.** It runs from 2022 to Filings made in February 2026, and includes a 2014 GE Capital report. Only 13 of the 54 Companies have the two years of quarterly Filings a trend question needs.
- **The metadata can be trusted once it is derived.** Every Filing gets a Report Period, a stable Filing ID, a Fiscal Period and a Sector, and every source of each agrees.
- **The text needs cleaning and careful chunking.** XBRL noise, a table of contents, flattened tables and very long lines would all break naive chunking. Item headings locate Sections in almost every Filing.
- **Everything is too big for one Answer Call, and much of it repeats.** A median 10-K is about 98k tokens and most text repeats from one period to the next, so retrieval must pick deduplicated passages per Company.
- **The example questions are answerable, each with a caveat** the answer has to state: mixed periods, Snapshot Companies, missing forward guidance.
- **Revenue and net income can be extracted exactly** for the Tracked Companies: every value matches the SEC's XBRL data to the dollar. So a small SQLite Financial Facts store will feed figures to the Answer Call ([ADR 0001](docs/adr/0001-sqlite-financial-facts-store.md)).

## Design

The planned flow for one question, following the [recommendations for the retrieval phase](docs/findings.md#recommendations-for-the-retrieval-phase):

```
question
  │
  ├─ rule-based parser ── Companies, Sector phrases, time window, Section hints, metric
  │                        (no LLM runs before the Answer Call)
  │
  ├─ retrieval ────────── chunks filtered by Company and period, preferring the right
  │                        Section, deduplicated, budgeted per Company
  │
  ├─ Financial Facts ──── fixed, parameterised SQLite queries for revenue, net income
  │                        and segment revenue
  │
  └─ Answer Call ──────── one LLM request: fixed prompt template + cited chunks
                           + facts table + each Company's coverage gaps
```

The index is built once from the Corpus. Every chunk carries its Filing ID, Company, Sector, Form Type, Report Period, Fiscal Period, Section and Item, so the answer can cite exactly where each claim comes from and say plainly when the data can't support a question.

Key decisions so far:

- **One generative LLM call per question, strictly.** Embeddings and rerankers are allowed because they score text and don't generate it. Query parsing is rule-based, which rules out text-to-SQL.
- **Answers come only from the Corpus.** The curated Sector table is the only outside data that can affect an answer, and it is disclosed. SEC XBRL data is used only to measure extraction accuracy, never to answer.
- **Every Filing is kept,** including those outside "2023–2025", and every citation shows its Report Period.
- **Figures come from a Financial Facts store**, not from the model reading flattened tables ([ADR 0001](docs/adr/0001-sqlite-financial-facts-store.md)).

These rest on assumptions about what the Client wants. Each one, and whether the Client has confirmed it, is in [`docs/assumptions.md`](docs/assumptions.md).

## Setup

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/) and `make`. The Corpus is committed, so there is nothing to download.

```sh
git clone https://github.com/dwest1507/eliza-assessment.git
cd eliza-assessment
make install   # create backend/.venv with uv
make test      # run the test suite
```

Every command runs through the root `Makefile` (`make help` lists them):

| Command | What it does |
|---|---|
| `make install` | Install the backend environment with uv |
| `make test` | Run the backend test suite (pytest) |
| `make lint` | Lint and check formatting (ruff) |
| `make format` | Auto-fix lint issues and format |
| `make eda` | Execute the EDA notebook from its source and write `eda.ipynb` with outputs |
| `make sec-facts` | Fetch the SEC XBRL company-facts reference for the Tracked Companies |

### Running the EDA

`make eda` compares extracted Financial Facts with the SEC's XBRL company-facts data, so it needs that data cached first. It fetches it automatically when the cache is missing. The SEC requires every automated request to carry a User-Agent naming the requester and a contact email, which is read from the `SEC_USER_AGENT` environment variable. Put it in `backend/.env`, which is gitignored and loaded by the `Makefile`:

```sh
cp backend/.env.example backend/.env   # then edit SEC_USER_AGENT (unquoted)
make eda
```

Each app keeps its own `.env` beside a committed `.env.example`, so a container gets only its own variables.

The notebook's source of truth is [`backend/notebooks/eda.py`](backend/notebooks/eda.py) (jupytext percent format). `make eda` writes the paired `eda.ipynb`; edit the `.py`, never the `.ipynb`. The committed `.ipynb` already has its outputs, so you can read the analysis on GitHub without running anything.

### Using the core package

```sh
cd backend && uv run python
```

```python
from edgar_rag.corpus import load_corpus
from edgar_rag.financial_facts import extract_financial_facts

filings = load_corpus()  # all 246 Filings, cleaned and split into Sections
nvda = [f for f in filings if f.ticker == "NVDA"]
latest = max(nvda, key=lambda f: f.report_period)

latest.filing_id, latest.fiscal_period, latest.coverage
[(s.name, s.item) for s in latest.sections]

for fact in extract_financial_facts(latest):
    print(fact.metric, fact.segment, fact.value, fact.label)
```

## Repository layout

```
.
├── backend/                   uv-managed Python project
│   ├── src/edgar_rag/
│   │   ├── corpus.py          the Corpus seam: Filings with metadata, cleaned body, Sections
│   │   ├── financial_facts.py the Financial Facts seam: revenue, net income, segment revenue
│   │   └── sec_reference.py   fetches and reads the SEC company-facts evaluation reference
│   ├── tests/                 pytest suite
│   └── notebooks/             eda.py (source) and eda.ipynb (executed)
├── frontend/                  reserved for the Next.js front-end
├── data/
│   ├── edgar_corpus/          the Corpus, read-only, exactly as supplied
│   ├── reference/sectors.csv  the curated Sector table, one row per Company
│   └── derived/               anything built from the Corpus (gitignored)
├── docs/
│   ├── AI-RAG Assessment.md   the assessment brief
│   ├── findings.md            EDA findings and recommendations for retrieval
│   ├── assumptions.md         working assumptions, confirmed or not by the Client
│   └── adr/                   architecture decision records
├── CONTEXT.md                 domain glossary
└── Makefile                   single entry point
```

The core package depends on nothing outside the Python standard library and must not depend on a web framework, so the API and front-end can sit on top of it.

## Data

The Corpus in [`data/edgar_corpus/`](data/edgar_corpus/) is the assessment's zip committed exactly as extracted: 246 Filings from 54 Companies plus `manifest.json`. It is read-only; every cleaning step happens in code. [`data/README.md`](data/README.md) records its source, checksum and how to verify it, and documents the Sector table and the SEC reference data.
