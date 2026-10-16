# SEC Filings RAG

A question-answering system for a private equity Client. It answers natural-language business questions ("How has NVIDIA's revenue and growth outlook changed over the last two years?") with answers grounded in, and cited to, a Corpus of SEC EDGAR 10-K and 10-Q Filings. Indexing and retrieval run beforehand; the answer itself comes from **one LLM request**, the Answer Call.

This repo is a take-home assessment for a Forward Deployed Engineer (AI Engineering) role. The brief is in [`docs/AI-RAG Assessment.md`](docs/AI-RAG%20Assessment.md). Domain terms used throughout (Filing, Corpus, Company, Tracked Company, Report Period, Financial Fact, Answer Call...) are defined in [`CONTEXT.md`](CONTEXT.md).

## Status

The work runs in phases. The exploratory data analysis (EDA) phase is complete. The retrieval phase has its tracer bullet: a question asked from the command line, over the chat API or in the research workspace is answered end to end, from the index through one Answer Call, and the retrieval and generation harnesses measure it on the Golden Set. Coverage Gaps are computed by code and stated in the prompt, the stream and the workspace. Follow-up inheritance and Financial Facts in the context come next.

| Deliverable (from the brief) | Status | Where |
|---|---|---|
| README with setup and run instructions | Done | This file |
| Indexing and retrieval code | Partly done: Corpus loading, cleaning, Section splitting, Financial Facts extraction, chunking, the FTS5 index, Company recognition, Sector phrases resolved through the Sector table, time windows, Section hints, the metric, risk routing, deduplication of repeated text, "how has it changed" routing, retrieval into numbered Sources budgeted per Company, and Coverage Gaps (Snapshot trends, Companies missing from the Corpus, the stale GE Capital Filing, missing guidance, periods that differ) are built and tested. Follow-ups and Financial Facts in the answer are next. | [`backend/src/edgar_rag/`](backend/src/edgar_rag/) |
| Log of prompt iterations | Started: v1 to v3 | [`docs/prompt-iterations.md`](docs/prompt-iterations.md) |
| Final prompt template | v3 in place; the final version follows the prompt iterations | [`docs/prompt-iterations.md`](docs/prompt-iterations.md), [`backend/src/edgar_rag/_prompt.py`](backend/src/edgar_rag/_prompt.py) |
| Front-end | Started: the research workspace streams answers, opens each `[Sn]` citation's passage in a Sources panel, shows each answer's Query Scope as chips and its Coverage Gaps as a callout, and offers the six starter prompts. A "How it works" page shows the architecture, the evaluation scoreboard (from `make eval-export`) and the Corpus coverage grid. Session history comes next. | [`frontend/`](frontend/), [Running the full stack](#running-the-full-stack) |
| Example request, ready to execute | Done: `make ask` answers a question from the command line, and `backend/scripts/chat.sh` calls the chat API with `curl` | [Asking a question](#asking-a-question), [The chat API](#the-chat-api) |
| Notes on how quality was evaluated | Partly done: Financial Facts extraction is measured against SEC XBRL data, the Golden Set of 30 labelled questions is written and checked against the Corpus, the retrieval harness scores the FTS5 Arm on it (hit@10 0.71 on dev), and the generation harness scores the answers in code and with the Jev judge (Fact Recall 0.55, Faithfulness 0.90 and Coverage Gaps stated 0.91 on dev with prompt v3, at $0.0024 per answer). | [`docs/evaluation.md`](docs/evaluation.md), [`docs/findings.md`](docs/findings.md) (findings 21–24), notebook analysis 7, [`docs/golden-set.md`](docs/golden-set.md) |
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

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22+ with npm (`frontend/.nvmrc` names the version used), and `make`. The Corpus is committed, so there is nothing to download.

```sh
git clone https://github.com/dwest1507/eliza-assessment.git
cd eliza-assessment
make install   # create backend/.venv with uv and install frontend/node_modules with npm
make test      # run the backend and front-end test suites
```

Every command runs through the root `Makefile` (`make help` lists them):

| Command | What it does |
|---|---|
| `make install` | Install the backend environment with uv and the front-end's dependencies with npm |
| `make test` | Run the backend (pytest) and front-end (Vitest) test suites |
| `make lint` | Lint and check formatting (ruff; ESLint, TypeScript and Prettier) |
| `make format` | Auto-fix lint issues and format both halves |
| `make eda` | Execute the EDA notebook from its source and write `eda.ipynb` with outputs |
| `make sec-facts` | Fetch the SEC XBRL company-facts reference for the Tracked Companies |
| `make index` | Rebuild the retrieval index (`data/derived/edgar_rag.sqlite`) from the Corpus |
| `make ask Q="..."` | Answer a question from the command line, without a server (needs `OPENAI_API_KEY`) |
| `make api` | Run the chat API on http://localhost:8000 (`API_PORT` to change; answers need `OPENAI_API_KEY`) |
| `make eval-retrieval` | Score the retrieval Arms on the Golden Set's dev split (`SPLIT=holdout` or `all` to change it); no LLM call |
| `make dev` | Run the chat API and the research workspace together on http://localhost:3000 (`WEB_PORT` to change) |
| `make eval-generation` | Answer the Golden Set's dev split and score the answers, with cost and latency (`SPLIT=`, `MODEL=`; needs `OPENAI_API_KEY` and `JEV_API_KEY`, costs money) |
| `make eval-export` | Export the harnesses' latest results and the Corpus coverage for the workspace's "How it works" page (`SPLIT=` to change the split); no LLM call |

### Asking a question

`make index` chunks every Filing and writes the index, one SQLite file under `data/derived/` (about 25 seconds). An index written by an earlier version of the code is refused with a message to run `make index` again. `make ask` answers one question through one Answer Call to OpenAI, so it needs an OpenAI API key in `backend/.env`:

```sh
cp backend/.env.example backend/.env   # then set OPENAI_API_KEY (unquoted)
make index
make ask Q="What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"
```

`make ask` builds the index first if it is missing. It prints the Query Scope (the Companies the question names, each Sector phrase and the Companies the Sector table resolved it to, the time window, any Section hints, the metric, and each Company's Filings inside the window), the numbered Sources the answer may cite, the Coverage Gaps the answer must state, then the answer as it streams, and a last line with the model, prompt version, token usage and latency. The model defaults to `gpt-6-luna`; set `OPENAI_MODEL` in `backend/.env` to try another. Every Answer Call is also logged as one JSON line in `data/derived/logs/answer_calls.jsonl`.

### The chat API

`make api` serves the same pipeline over HTTP with FastAPI, for the front-end (it builds the index first if it is missing). With it running, the `curl` example asks the brief's first question and prints the stream as it arrives:

```sh
make api                                   # terminal 1
backend/scripts/chat.sh                    # terminal 2: the brief's first example question
backend/scripts/chat.sh "What are NVIDIA's main supply chain risks?"
API_URL=http://localhost:8001 backend/scripts/chat.sh   # another server
```

The script is a single `curl` call:

```sh
curl --no-buffer -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages": [{"role": "user", "content": "What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"}]}'
```

- **`POST /api/chat`** takes the whole conversation, oldest first, ending with the question: `{"messages": [{"role": "user" | "assistant", "content": "..."}]}`. Messages in the AI SDK's `useChat` shape (`parts: [{"type": "text", "text": "..."}]`) are read too. It answers with the [Vercel AI SDK UI message stream](https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol) (server-sent events, header `x-vercel-ai-ui-message-stream: v1`): first a `data-query-scope` part with the Query Scope the rules resolved (`companies`; `sectorPhrases`, each with its `phrase`, the Sector table `column` and `values` it was read against and the `tickers` it resolved to; `timeWindow`; `sections`; `metric`), then a `data-sources` part with every numbered Source (`tag`, `filingId`, `company`, `ticker`, `formType`, `reportPeriod`, `fiscalPeriod`, `section`, `item`, `label`, `text`), so citations are clickable before the answer arrives, then a `data-coverage-gaps` part with every Coverage Gap (`kind`, `label`, `companies`, and the fixed wording `text` the answer states; an empty list when there is none), then the answer as `text-delta` parts, `finish` and `[DONE]`. If the provider fails mid-answer, an `error` part replaces `finish`.
- An empty latest message, one longer than 4,000 characters, or a conversation that does not end with the user's question is rejected with `400`; a body of the wrong shape with `422`. If the index is missing or the answer model can't be created (no key), the API answers `503`.
- **`GET /api/health`** returns `{"status": "ok"}` and needs no key.

The backend is stateless: nothing is kept between requests, so the browser sends the whole conversation each time. Cross-origin browser calls are refused unless their origin is listed in `CORS_ALLOWED_ORIGINS` in `backend/.env` (comma-separated). The front-end calls the API through its own server-side route, which needs none. Each Answer Call is logged like `make ask`'s.

### Running the full stack

`make dev` runs the chat API and the research workspace together, then serves the workspace on http://localhost:3000. Answers need `OPENAI_API_KEY` in `backend/.env`, as for `make ask`:

```sh
cp backend/.env.example backend/.env   # then set OPENAI_API_KEY (unquoted)
make dev                               # API on :8000, workspace on http://localhost:3000
make dev API_PORT=8001 WEB_PORT=3001   # other ports
```

`make dev` builds the index first if it is missing, and installs the front-end's dependencies if they are missing or `package-lock.json` changed. If either server exits, it stops the other, and Ctrl+C stops both.

In the workspace, type a question or click one of the six starter prompts, which are the Golden Set's starter cases. The answer streams in as Markdown. Every `[Sn]` citation is a link: clicking it opens the Sources panel at that Source, showing its Filing ID, Form Type, Report Period, Fiscal Period, Section, Item and passage text. The answer's Sources are also listed under it, and they are clickable as soon as the answer starts.

The browser never calls the API directly. It posts to the workspace's own route (`frontend/app/api/chat/route.ts`), which forwards the conversation to the API and streams the answer back, so the API's URL stays on the server. That URL comes from `BACKEND_URL` in `frontend/.env` (copy `frontend/.env.example`); it defaults to `http://127.0.0.1:8000`, and `make dev` points it at the API it starts. To run the halves separately, use `make api` and `cd frontend && npm run dev`. [`frontend/README.md`](frontend/README.md) describes the app's layout and tests.

### Measuring retrieval

```sh
make eval-retrieval
```

runs every Golden Set case on the dev split through each retrieval Arm (today only FTS5, the Shipped Arm), with no LLM call, and prints hit@k, recall@k and MRR overall and per question type, then each challenger Arm's comparison with the Shipped Arm by McNemar's exact test. The report is also written to `data/derived/eval/retrieval-dev.json`. The method and the first numbers are in [`docs/evaluation.md`](docs/evaluation.md).


### Measuring answers

```sh
make eval-generation
```

answers every Golden Set case on the dev split through one real Answer Call each, then scores the answers: citation validity, figure exactness and Coverage Gap statements are checked in code, and Fact Recall and Faithfulness are judged by Jev, TypeSafe's judgment model, pinned to an exact version. Each answer's cost and latency, from the Answer Call log, are reported next to the scores. It needs `OPENAI_API_KEY` and `JEV_API_KEY` in `backend/.env` and costs about $0.07 per run. `MODEL=` picks another generator. The report, with every answer, is written to `data/derived/eval/generation-dev.json`; the method and the first scores are in [`docs/evaluation.md`](docs/evaluation.md#generation-harness).

### Showing the results in the workspace

```sh
make eval-export
```

collects the harnesses' latest reports for the dev split (every Arm's retrieval scores and comparison with the Shipped Arm, and every generator's scores, cost and latency) and the Corpus coverage grid (each Company's Filings by Report Period, Tracked Companies first) into `frontend/data/eval-export.json`. The workspace's "How it works" page (http://localhost:3000/how-it-works, linked from its header) shows them with the architecture. The export runs the retrieval harness first if its report is missing, but never the generation harness, which costs money: until `make eval-generation` has run, the page says so instead of showing answer scores. The export is committed, so the page shows the last exported results without anyone rerunning the harnesses; rerun it and commit the file after a harness run worth publishing.

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

The retrieval seam works on the index `make index` builds. Preparing an Answer Context makes no network call:

```python
from edgar_rag.retrieval import Message, prepare_answer_context

context = prepare_answer_context([Message("user", "What are NVIDIA's main supply risks?")])
context.query_scope.companies
context.query_scope.time_window.label  # "latest": a risk question with no time phrase
context.query_scope.sections           # ("Risk Factors",)
[f.filing_id for f in context.query_scope.filings]
[(s.tag, s.label) for s in context.sources]
context.messages  # the rendered prompt for the Answer Call
```

## Repository layout

```
.
├── backend/                   uv-managed Python project
│   ├── src/edgar_rag/         the core package (standard library only)
│   │   ├── corpus.py          the Corpus seam: Filings with metadata, cleaned body, Sections
│   │   ├── financial_facts.py the Financial Facts seam: revenue, net income, segment revenue
│   │   ├── retrieval.py       the retrieval seam: build the index, prepare an Answer Context
│   │   ├── answer_model.py    the answer model protocol and the logged Answer Call
│   │   ├── sec_reference.py   fetches and reads the SEC company-facts evaluation reference
│   │   └── golden_set.py      loads and validates the Golden Set and its dev/holdout split
│   ├── src/edgar_answer/      provider implementations (OpenAI) and the `make ask` CLI
│   ├── src/edgar_api/         the FastAPI chat API (`make api`)
│   ├── src/edgar_eval/        evaluation harnesses: retrieval Arms and metrics, answer checks, the Jev judge, the export
│   ├── scripts/chat.sh        the `curl` example against the chat API
│   ├── tests/                 pytest suite
│   └── notebooks/             eda.py (source) and eda.ipynb (executed)
├── frontend/                  the Next.js research workspace (`make dev`) and its "How it works" page
├── data/
│   ├── edgar_corpus/          the Corpus, read-only, exactly as supplied
│   ├── reference/sectors.csv  the curated Sector table, one row per Company
│   ├── reference/missing_companies.csv  notable Companies not in the Corpus
│   ├── eval/golden_set.json   the Golden Set: labelled evaluation questions and starter prompts
│   └── derived/               anything built from the Corpus (gitignored)
├── docs/
│   ├── AI-RAG Assessment.md   the assessment brief
│   ├── findings.md            EDA findings and recommendations for retrieval
│   ├── assumptions.md         working assumptions, confirmed or not by the Client
│   ├── golden-set.md          the Golden Set's fields, split rule and review
│   ├── evaluation.md          how quality is measured, and the scores
│   ├── prompt-iterations.md   every version of the Answer Call's prompt template
│   └── adr/                   architecture decision records
├── CONTEXT.md                 domain glossary
└── Makefile                   single entry point
```

The core package depends on nothing outside the Python standard library and must not depend on a web framework, so the API and front-end can sit on top of it; a guard test enforces this. Code that needs a provider's SDK lives in `edgar_answer` ([ADR 0005](docs/adr/0005-provider-sdks-outside-the-core-package.md)), the web API in `edgar_api`, the evaluation harnesses in `edgar_eval` ([ADR 0006](docs/adr/0006-evaluation-harnesses-outside-the-core-package.md)), and the research workspace in `frontend/`, which reaches the API only through its own server-side route.

## Data

The Corpus in [`data/edgar_corpus/`](data/edgar_corpus/) is the assessment's zip committed exactly as extracted: 246 Filings from 54 Companies plus `manifest.json`. It is read-only; every cleaning step happens in code. [`data/README.md`](data/README.md) records its source, checksum and how to verify it, and documents the Sector table and the SEC reference data.
