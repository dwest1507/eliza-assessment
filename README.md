# SEC Filings RAG

A question-answering system for a private equity Client. It answers natural-language business questions ("How has NVIDIA's revenue and growth outlook changed over the last two years?") with answers grounded in, and cited to, a Corpus of SEC EDGAR 10-K and 10-Q Filings. Indexing and retrieval run beforehand; the answer itself comes from **one LLM request**, the Answer Call.

This repo is a take-home assessment for a Forward Deployed Engineer (AI Engineering) role. The brief is in [`docs/AI-RAG Assessment.md`](docs/AI-RAG%20Assessment.md). Domain terms used throughout (Filing, Corpus, Company, Tracked Company, Report Period, Financial Fact, Answer Call...) are defined in [`CONTEXT.md`](CONTEXT.md).

## Status

The work runs in phases. The exploratory data analysis (EDA) phase is complete. The retrieval phase has its tracer bullet: a question asked from the command line, over the chat API or in the research workspace is answered end to end, from the index through one Answer Call, and the retrieval and generation harnesses measure it on the Golden Set. Coverage Gaps are computed by code and stated in the prompt, the stream and the workspace. Figure questions get exact, cited Financial Facts. The workspace is a chat: a follow-up inherits the parts of the Query Scope it does not name from earlier questions, and the conversation survives a page refresh. The retrieval Arm (FTS5) and the generator (`gpt-6-luna`) were chosen by fixed rules on the Golden Set's dev split, and the final configuration was scored once on its holdout split.

| Deliverable (from the brief) | Status | Where |
|---|---|---|
| README with setup and run instructions | Done | This file |
| Indexing and retrieval code | Partly done: Corpus loading, cleaning, Section splitting, Financial Facts extraction, chunking, the FTS5 index, Company recognition, Sector phrases resolved through the Sector table, time windows, Section hints, the metric (revenue, net income, segment names), risk routing, outlook routing to the latest MD&A, deduplication of repeated text, "how has it changed" routing, retrieval into numbered Sources budgeted per Company (each Source's chunks joined into continuous passages where they are adjacent in the Filing, their overlap shown once and a marker only where text was skipped), the Financial Facts store queried into a cited table with derived fourth quarters and year-on-year changes, Coverage Gaps (Snapshot trends, Companies missing from the Corpus, the stale GE Capital Filing, missing guidance, periods that differ) and follow-up questions that inherit their Query Scope by rules ([ADR 0003](docs/adr/0003-follow-ups-inherit-query-scope-by-rules.md)) are built and tested. | [`backend/src/edgar_rag/`](backend/src/edgar_rag/) |
| Log of prompt iterations | Done: v1 to v14, each with what changed, why (the failing dev cases or metric) and its dev scores before and after; v8 to v14 were tried and discarded | [`docs/prompt-iterations.md`](docs/prompt-iterations.md) |
| Final prompt template | Done: v7, after the prompt iterations, scored with all four generators and on the holdout split | [The Answer Call's prompt](#the-answer-calls-prompt), [`docs/prompt-iterations.md`](docs/prompt-iterations.md#the-final-template-v7), [`backend/src/edgar_rag/_prompt.py`](backend/src/edgar_rag/_prompt.py) |
| Front-end | Started: the research workspace streams answers, opens each `[Sn]` citation's passage (or, for a Financial Facts Source, its table of figures) in the Sources tab of one right-hand side panel, which an always-visible toolbar (a rail on the right edge, buttons above the question box on a narrow screen) opens and closes (every retrieved Source numbered S1…SN, cited and uncited styled apart; each headed by a readable line, its Filing details a click away, its passage tables shown as tables, a "passage skipped" break only where retrieval skipped text, and glued sentences spaced), and whose Calendar tab shows a Company Calendar for each Company the conversation asked about (fiscal quarters and years beside their calendar months, Filings and revenue, banded by calendar year), shows each answer's short direct answer first with its full analysis a click away, and, once the answer is complete, its Coverage Gaps as Coverage notes below it, one "Sources" disclosure (its Query Scope chips and the Sections it was searched in, its cited Sources, then a collapsed "Also retrieved (N)"), and up to three follow-up questions built from templates, and offers the six starter prompts above a line saying how many Companies are covered. The conversation is kept for the browser session, and a "New conversation" control clears it. A "How it works" page opens with a plain overview (how an answer is made, what's covered, the shipped run's headline numbers in plain words and the known limits), then, under "Technical details", shows the architecture, the evaluation scoreboard on Golden Set version 2 (from `make eval-export`: the shipped run beside its Control Run, the Arms' screen, the Arm and settings comparisons and the generator comparison), the Brief Suite's verdicts, the holdout run beside dev and the Corpus coverage grid. | [`frontend/`](frontend/), [Running the full stack](#running-the-full-stack) |
| Example request, ready to execute | Done: `make ask` answers a question from the command line, and `backend/scripts/chat.sh` calls the chat API with `curl` | [Asking a question](#asking-a-question), [The chat API](#the-chat-api) |
| Notes on how quality was evaluated | Done: Financial Facts extraction is measured against SEC XBRL data, the Golden Set of 30 labelled questions is written and checked against the Corpus, the retrieval harness scores the FTS5 Arm on it (hit@10 0.88 on dev), three challenger Arms (dense, hybrid, cross-encoder re-ranking) were measured in both harnesses and none beat FTS5 ([ADR 0008](docs/adr/0008-fts5-stays-the-shipped-arm.md)), the generation harness scores the answers in code and with the Jev judge, four generators (`gpt-6-luna`, `gpt-6.1-sol`, Claude Sonnet 5.5, Claude Opus 5.5) were compared on dev and none beat `gpt-6-luna` at 20 to 65 times its cost ([ADR 0009](docs/adr/0009-gpt-6-luna-stays-the-generator.md)), 16 chunk sizes and context budgets were scored on dev and none beat 600-token chunks and a 32k budget ([ADR 0010](docs/adr/0010-chunk-size-and-context-budget.md)), and the final configuration was run once on the holdout split (Fact Recall 0.67, Faithfulness 0.95, Coverage Gaps stated 1.00, every citation valid and hit@10 0.90, at $0.0030 per answer). Golden Set version 2 (60 dev and 20 holdout cases) confirmed every choice on dev under one-sided thresholds with a Control Run, and its holdout, scored once on that setup, is in line with dev (Fact Recall 0.74, Faithfulness 0.95, hit@10 0.89, at $0.0028 per answer). | [`docs/evaluation.md`](docs/evaluation.md), [`docs/findings.md`](docs/findings.md) (findings 21–24), notebook analysis 7, [`docs/golden-set.md`](docs/golden-set.md) |
| Presentation: value case and future state | Drafted, awaiting the developer's review: eight slides (the Client's problem, the value case, the demo hand-off, the holdout numbers, how the choices were made, risks and limits, the future state), each linking the documents its numbers come from; a test checks every figure on a slide is in one of them | [`docs/deck.md`](docs/deck.md), [The slide deck](#the-slide-deck) |
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
  ├─ rule-based parser ── Companies, Sector phrases, time window, Section hints, metric;
  │                        a follow-up inherits what it leaves out from earlier questions
  │                        (no LLM runs before the Answer Call)
  │
  ├─ retrieval ────────── chunks filtered by Company and period, preferring the right
  │                        Section, deduplicated, budgeted per Company
  │
  ├─ Financial Facts ──── fixed, parameterised SQLite queries for revenue, net income
  │                        and segment revenue; one Facts Source per Filing
  │
  └─ Answer Call ──────── one LLM request: fixed prompt template + cited chunks
                           + facts table + each Company's coverage gaps
```

The index is built once from the Corpus. Every chunk carries its Filing ID, Company, Sector, Form Type, Report Period, Fiscal Period, Section and Item, so the answer can cite exactly where each claim comes from and say plainly when the data can't support a question.

Key decisions so far:

- **One API call per question, strictly: the Answer Call.** Local models inside retrieval (a local embedding model, a cross-encoder re-ranker) are allowed because they make no request; a hosted embedding call is not (the stricter reading, accepted on 2026-10-17). Query parsing is rule-based, which rules out text-to-SQL.
- **Answers come only from the Corpus.** The curated Sector table is the only outside data that can affect an answer, and it is disclosed. SEC XBRL data is used only to measure extraction accuracy, never to answer.
- **Every Filing is kept,** including those outside "2023–2025", and every citation shows its Report Period.
- **Figures come from a Financial Facts store**, not from the model reading flattened tables ([ADR 0001](docs/adr/0001-sqlite-financial-facts-store.md)).

These rest on assumptions about what the Client wants. Each one, and whether the Client has confirmed it, is in [`docs/assumptions.md`](docs/assumptions.md).

### The Answer Call's prompt

The Answer Call sends one fixed template, version v15 ([`backend/src/edgar_rag/_prompt.py`](backend/src/edgar_rag/_prompt.py)), as two messages. The system message holds the rules below. The user message holds, in order: the Coverage Gaps (or "None."), which the product shows below the answer as Coverage notes and the answer acknowledges only where one leaves part of the question unanswered ([ADR 0016](docs/adr/0016-coverage-gaps-shown-by-the-product.md)), the Companies each Sector phrase resolved to, each Company's coverage (its class, Filings, Report Periods and Fiscal Periods), the Financial Facts table when the question names a metric, the Sources grouped by Company, the earlier conversation (the last 10 turns, about 6k tokens at most, each earlier Source tag named as the Filing ID it cited), and the question. How each part came to be, and its dev scores, is in the [prompt iteration log](docs/prompt-iterations.md).

```text
You are a research assistant for private equity analysts. You answer business questions about public companies using only the excerpts from their SEC 10-K and 10-Q filings given to you as numbered Sources.

Rules:
1. Use only the Sources. Never use general knowledge, memory or any outside data, even for well-known facts. If the Sources do not answer part of the question, say so plainly.
2. Cite every claim with the tag of the Source it comes from, e.g. [S3], placed right after the claim. Use several tags when a claim rests on several Sources. Cite only tags listed in this turn's Sources.
3. The earlier conversation is there to help you understand the question. It is not evidence: never repeat a claim from an earlier answer unless a Source in this turn supports it, and then cite that Source.
4. When you use a Company's filings, give the filing's form type, fiscal period and report period, as listed under "Coverage".
5. Take revenue, net income and segment revenue from the Financial Facts table when it has them, cite the row's Source tags, and quote figures exactly with their units and periods. Label a derived figure as derived: a fourth quarter computed from a 10-K less three 10-Qs, a growth rate, or any figure you compute yourself, citing the rows it comes from. When a figure is not in the table and you read it from a Source's text instead, say it was read from the Filing text. When a Source's text states a change itself ("Revenue increased $36.6 billion or 15%") or what drove it, give that too, in its words and with its tag, rather than computing the change yourself.
6. When the question names a group of companies ("the major banks"), it was resolved through a curated Sector table to the Companies listed under "Companies in scope". Name those Companies near the start of the answer, say they come from the Sector table, and cover no other company for that group.
7. "Coverage Gaps" lists what the filings cannot answer: a trend asked of a company with only a snapshot of filings, a company not in the filings, a stale filing, guidance the filings do not contain, or periods that differ. Every gap listed there is shown below your answer, in its own wording, so do not repeat the list. Where a gap leaves part of the question unanswered (a company not in the filings, a trend asked of a snapshot company, a stale filing left out, guidance the filings do not contain), say so briefly, in your own words, where that part of the answer would be: name the company and what the filings cannot answer about it, without citing the "Coverage Gaps" list. Never mention that the companies' periods differ for its own sake: rule 4 gives each filing's period, and the difference is shown below your answer. Never fill a gap from general knowledge: say nothing more about a company the filings do not include, never use a filing listed as left out, and never present MD&A commentary as the company's guidance.
8. Be specific. For each point, give the particulars the Sources state: the laws and programs, products, people, places, dates, amounts and percentages they name, in their words. Never reduce them to broad categories ("regulatory risk", "pricing pressure") that would fit any company.

Structure the answer for a PE analyst, in Markdown:
- Open with the direct answer: two or three sentences of prose that answer the question from the Sources, citing them like any other claim. Put nothing before it: no heading, list, table or note on what the filings lack.
- When the question compares two or more Companies on the same dimensions, give a comparison table first, one row per Company, then each Company's detail under its own heading. Otherwise give the points for each Company under its own heading.
- End with the last point. Add no closing "Coverage" or "Limitations" section: the Coverage Gaps are shown below your answer.
- Write 300 to 600 words. When the question is narrow, reach 300 words with the specifics of rule 8 that bear on it (what drove a figure, the segments, periods or plans behind it, the risks the Sources attach to it), never with repetition or general knowledge. When the Sources hold more than 600 words can carry, keep the most material points. Only an answer whose question the Sources cannot answer at all may be shorter.
```

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
| `make ask Q="..."` | Answer a question from the command line, without a server, with the answer model `ANSWER_MODEL` names (needs its provider's key: `OPENAI_API_KEY` for the default, `gpt-6-luna`) |
| `make api` | Run the chat API on http://localhost:8000 (`API_PORT` to change; answers with `ANSWER_MODEL` and need its provider's key) |
| `make embeddings` | Embed every chunk with OpenAI for the dense and hybrid challenger Arms (evaluation only; needs `OPENAI_API_KEY`, about 35 cents) |
| `make local-embeddings` | Embed every chunk with a local model for the `dense-local` and `hybrid-local` challenger Arms (evaluation only; no API call, no cost, about 30 minutes on the CPU) |
| `make eval-retrieval` | Score the retrieval Arms on the Golden Set's dev split (`SPLIT=holdout` or `all` to change it, `ARMS=` to pick Arms, `CHUNK_TOKENS=` and `CONTEXT_BUDGET=` for another chunk size or context budget); no LLM call |
| `make dev` | Run the chat API and the research workspace together on http://localhost:3000 (`WEB_PORT` to change) |
| `make eval-generation` | Answer the Golden Set's dev split and score the answers, with cost and latency (`SPLIT=`, `MODEL=`, `CHUNK_TOKENS=`, `CONTEXT_BUDGET=`; needs `OPENAI_API_KEY` and `JEV_API_KEY`, costs money) |
| `make eval-rescore` | Re-score saved reports from their stored answers, in place, with no LLM call: it redoes the figure check and drops Jev's verdicts on expected Coverage Gap sentences and the uncited claims the claim split no longer makes. By default it re-scores the current round's shipped run, Control Run and Brief Suite; `REPORTS="..."` names other reports, and `REPORTS=all` re-scores every saved one |
| `make eval-arms` | Screen every retrieval Arm on Evidence Reached, answer the dev split through the shippable ones kept and choose the Shipped Arm by the selection rule (needs `OPENAI_API_KEY` and `JEV_API_KEY`, costs money) |
| `make eval-generators` | Answer the dev split with the default comparison, `COMPARISON` in `backend/src/edgar_eval/generators.py` (version 2's: `gpt-6-luna` and Claude Haiku 5.5), and choose the generator by the selection rule (needs `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and `JEV_API_KEY`, costs about $0.37 on dev for Claude Haiku 5.5's run). `MODELS="..."` names other generators from the table, `GENERATORS` in `backend/src/edgar_answer/generators.py`; `MODELS=` (empty) runs every one, version 1's four (`gpt-6-luna`, `gpt-6.1-sol`, Claude Sonnet 5.5, Claude Opus 5.5), Claude Haiku 5.5 and terra (`gpt-5.6-terra`). It lists every answer of each run that stopped at the token cap |
| `make eval-export` | Export the harnesses' latest results, the Corpus coverage and each Company's Company Calendar for the workspace's "How it works" page and Calendar tab (`SPLIT=` to change the split); no LLM call |
| `make ci-cd` | Run every CI check locally: lint, tests, the retrieval gate, the front-end build, the dependency audits and Lighthouse (no paid API call) |
| `make deck` | Render the slide deck (`docs/deck.md`) to `data/derived/deck/deck.html` with the Marp CLI, which `npx` fetches |

### Continuous integration

GitHub Actions runs the same scripts as `make ci-cd` (in [`scripts/`](scripts/)), and none of them calls a paid API: the generation harness never runs in CI ([ADR 0014](docs/adr/0014-ci-runs-no-paid-api.md)).

| Workflow | Runs on | What it checks | Locally |
|---|---|---|---|
| Backend CI | backend, `data/` or `docs/` changes | the uv lockfile, ruff, pytest, and the retrieval gate: FTS5 on the dev split against the Floors in `data/eval/retrieval_floors.json` | `make backend-lint`, `make backend-test`, `make eval-gate` |
| Frontend CI | front-end changes | ESLint, Prettier, TypeScript, Vitest, the production build | `make frontend-quality`, `make frontend-test`, `make frontend-build` |
| Lighthouse | front-end pull requests | accessibility, best practices and SEO of at least 0.9 (performance warns) | `make lighthouse` |
| Security | every pull request and push to main, and weekly | CodeQL, gitleaks, npm audit, pip-audit, dependency review | `make security-audit` |
| Release Please | pushes to main | opens a release pull request that bumps the version and writes `CHANGELOG.md` from the conventional commits | |

A change meant to move the retrieval scores (a new Golden Set version, Shipped Arm, chunk size or context budget, or a change to the Query Scope rules) re-records the Floors with `make eval-floors` and commits them with it. Dependabot opens weekly npm and uv update pull requests and monthly GitHub Actions ones.

### Asking a question

`make index` chunks every Filing, extracts the Tracked Companies' Financial Facts, and writes both to the index, one SQLite file under `data/derived/` (about 45 seconds). An index written by an earlier version of the code is refused with a message to run `make index` again. `make ask` answers one question through one Answer Call to the answer model, OpenAI's `gpt-6-luna` by default, so it needs an OpenAI API key in `backend/.env`:

```sh
cp backend/.env.example backend/.env   # then set OPENAI_API_KEY (unquoted)
make index
make ask Q="What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"
```

`make ask` builds the index first if it is missing. It prints the Query Scope (the Companies the question names, each Sector phrase and the Companies the Sector table resolved it to, the time window, any Section hints, the metrics and segments, and each Company's Filings inside the window), the Financial Facts table when the question names a metric (each row with its Source tags, derived rows labelled, and a note for each Company and metric that falls back to the Filing text), the numbered Sources the answer may cite, the Coverage Gaps (which the workspace shows below the answer as Coverage notes), then the answer as it streams, and a last line with the model, prompt version, token usage and latency. The model defaults to `gpt-6-luna`; set `ANSWER_MODEL` in `backend/.env` to another model of the generator table, `GENERATORS` in `backend/src/edgar_answer/generators.py`, OpenAI's or Anthropic's, and the key its provider needs (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`). The same setting chooses the chat API's model, so the generator that wins the comparison ships by configuration alone; a model not in the table is refused with a message listing the table's models. Every model answers at reasoning effort medium with a cap of 32,000 output tokens, reasoning included; an answer that reaches the cap is cut off, and `make ask` says so after it. Every Answer Call is also logged as one JSON line in `data/derived/logs/answer_calls.jsonl`, with its stop reason.

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

- **`POST /api/chat`** takes the conversation, oldest first, ending with the question: `{"messages": [{"role": "user" | "assistant", "content": "..."}]}`. Messages in the AI SDK's `useChat` shape (`parts: [{"type": "text", "text": "..."}]`) are read too. An earlier answer may say which Filing each of its Source tags cited, as `"sources": {"S1": "AAPL_10-K_2025-09-27"}` or as its own `data-sources` part, and the prompt's history then names those Filings in place of the tags (tags it can't resolve are dropped). A follow-up inherits each part of the Query Scope it does not name (the Companies, the time window, the Section hints, the metric, and the topic words when it names none of its own) from the most recent earlier question that named it ([ADR 0003](docs/adr/0003-follow-ups-inherit-query-scope-by-rules.md)). It answers with the [Vercel AI SDK UI message stream](https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol) (server-sent events, header `x-vercel-ai-ui-message-stream: v1`): first a `data-query-scope` part with the Query Scope the rules resolved (`companies`; `sectorPhrases`, each with its `phrase`, the Sector table `column` and `values` it was read against and the `tickers` it resolved to; `timeWindow`; `sections`; `metric`; and `searched`, the places retrieval searched, each a `ticker`, `filingId` and `section`, `null` for a Filing searched whole), then a `data-sources` part with every numbered Source (`tag`, `filingId`, `company`, `ticker`, `formType`, `reportPeriod`, `fiscalPeriod`, `section`, `item`, `label`, `text`, and `kind`: `text`, or `facts` for the Financial Facts of one Filing, which also carries its reported `rows`, each with `metric`, `metricName`, `segment`, `months`, `reportPeriod`, `value`, `valueText` and the `label` the Filing prints), so citations are clickable before the answer arrives, then a `data-coverage-gaps` part with every Coverage Gap (`kind`, `label`, `companies`, and the fixed wording `text` the answer states; an empty list when there is none), then the answer as `text-delta` parts, `finish` and `[DONE]`. If the provider fails mid-answer, an `error` part replaces `finish`.
- A conversation is rejected with `400` and a `detail` giving the reason when it has more than 11 messages (the question and the 10 earlier messages the prompt keeps as history, `HISTORY_TURNS` in `backend/src/edgar_rag/_prompt.py`), when an earlier message is longer than 20,000 characters (an answer runs to 300–600 words, about 4,000 characters), or when its latest message is empty, longer than 4,000 characters, or not the user's question; a body of the wrong shape is rejected with `422`. A follow-up therefore inherits its Query Scope only from the questions among those 11 messages. If the index is missing or the answer model can't be created (no key), the API answers `503`. An `ANSWER_MODEL` not in the generator table stops the API as it starts, with a message listing the table's models. An answer that stops at the token cap is still streamed, and the API logs a warning naming the model and the tokens used.
- **`GET /api/health`** returns `{"status": "ok"}` and needs no key.

The backend is stateless: nothing is kept between requests, so the browser sends the conversation each time (its last 11 messages, the turns the prompt uses). Cross-origin browser calls are refused unless their origin is listed in `CORS_ALLOWED_ORIGINS` in `backend/.env` (comma-separated). The front-end calls the API through its own server-side route, which needs none. Each Answer Call is logged like `make ask`'s.

### Running the full stack

`make dev` runs the chat API and the research workspace together, then serves the workspace on http://localhost:3000. Answers need the answer model's provider key in `backend/.env` (`OPENAI_API_KEY` for the default, `gpt-6-luna`; `ANSWER_MODEL` chooses another), as for `make ask`:

```sh
cp backend/.env.example backend/.env   # then set OPENAI_API_KEY (unquoted)
make dev                               # API on :8000, workspace on http://localhost:3000
make dev API_PORT=8001 WEB_PORT=3001   # other ports
```

`make dev` builds the index first if it is missing, and installs the front-end's dependencies if they are missing or `package-lock.json` changed. If either server exits, it stops the other, and Ctrl+C stops both.

In the workspace, type a question or click one of the six starter prompts, which are labelled cases: the brief's three questions from the Brief Suite and three from the Golden Set. Below the starters, a line says how many Companies are covered and how many have two or more years of quarterly Filings, linking to the "What's covered" list on "How it works". The answer streams in as Markdown, showing only its opening paragraph at first, the two or three sentence direct answer; "Show full analysis" reveals the rest (the comparison table and the per-Company detail), while it streams too. Every `[Sn]` citation is a link: clicking it opens the side panel's Sources tab at that Source, whatever the panel showed. The panel sits on the right (a full-screen sheet on a narrow screen), beside a toolbar that is always visible: a rail on the right edge with a document icon, or, on a narrow screen, buttons above the question box. The Sources icon opens the panel at the latest answer's first Source, S1, and closes it when Sources is already showing; the open tab's icon is highlighted. The Sources tab numbers every Source the answer was given, S1…SN, the cited ones in the accent colour and the rest muted, and shows the open one headed by its tag and one readable line naming its Company, form, period and Section (for example "NVIDIA 10-Q, Q2 FY2025 · MD&A"), with its passage below (tables in it shown as tables) and its Filing ID, Form Type, Report Period, Fiscal Period, Section and Item under a collapsed "Filing details". A Financial Facts Source shows a table of the figures that Filing reports instead of a passage. The toolbar's calendar icon opens the Calendar tab: a ticker tab for every Company any answer's Query Scope named, in alphabetical order, each showing that Company's Company Calendar. It says when the fiscal year ends ("Fiscal year ends late January") and lists every fiscal quarter from the Company's first Filing in the Corpus to its latest, newest first, with its calendar months (NVIDIA's Q3 FY2026 is Aug–Oct 2025), its Filing (or "not in the filings", in grey) and its revenue (a hover names the Filing and the label it prints; a derived fourth quarter is marked as derived), each fiscal year in bold beside its fourth quarter, and the rows banded by calendar year. A Snapshot Company's calendar shows its Filings without revenue, saying revenue figures are extracted for companies with two or more years of filings. The citations are clickable as soon as the answer starts. Once it is complete, its Coverage Gaps follow it as "Coverage notes", each in its fixed wording, in plain words and neutral styling, never above the answer: the answer leads with its finding and mentions a gap, in its own words, only where it leaves part of the question unanswered (a Company not in the Corpus, a trend asked of a Snapshot Company, the stale Filing, missing guidance; [ADR 0016](docs/adr/0016-coverage-gaps-shown-by-the-product.md)). Then one collapsed "Sources" disclosure follows: a line of its Query Scope chips and the Sections it was searched in (each with how many Filings, hover for their Filing IDs), then the Sources it cites, then, under a collapsed "Also retrieved (N)", the Sources it was given but doesn't cite; under the latest answer, up to three suggested follow-up questions, built from fixed templates over its Query Scope and never by a model, send on a click. Follow-up questions build on earlier ones ("Which of them has the most regulatory exposure?", "And what about Microsoft?"), and each answer's Query Scope chips show what was inherited. The page doesn't scroll while an answer streams, and a "Jump to latest" button catches up. The conversation is kept in the browser's session storage, so a refresh keeps it; "New conversation" in the header clears it.

The browser never calls the API directly. It posts to the workspace's own route (`frontend/app/api/chat/route.ts`), which forwards the conversation's last 11 messages (the turns the prompt uses, so a long conversation keeps working) to the API and streams the answer back, so the API's URL stays on the server. When the API rejects a request, the workspace shows its reason. That URL comes from `BACKEND_URL` in `frontend/.env` (copy `frontend/.env.example`); it defaults to `http://127.0.0.1:8000`, and `make dev` points it at the API it starts. To run the halves separately, use `make api` and `cd frontend && npm run dev`. [`frontend/README.md`](frontend/README.md) describes the app's layout and tests.

### Measuring retrieval

```sh
make eval-retrieval
```

runs every Golden Set case on the dev split through each retrieval Arm (FTS5, the Shipped Arm, and five challengers: OpenAI dense embeddings, a reciprocal-rank-fusion hybrid of them, a cross-encoder re-ranker, and local dense embeddings and their hybrid), with no LLM call, and prints hit@k, recall@k and MRR overall and per question type, then each challenger Arm's comparison with the Shipped Arm by McNemar's exact test. The report is also written to `data/derived/eval/retrieval-dev.json`. The method and the first numbers are in [`docs/evaluation.md`](docs/evaluation.md). The dense and hybrid Arms need chunk embeddings, which `make embeddings` builds once (OpenAI `text-embedding-3-small`; it needs `OPENAI_API_KEY`, costs about 35 cents and runs automatically when they are missing); `ARMS=fts5` skips them. The `dense-local` and `hybrid-local` Arms read local chunk embeddings, which `make local-embeddings` builds once with `BAAI/bge-small-en-v1.5` (pinned, run by ONNX Runtime; free, no API call). The OpenAI Arms embed each question with a second API call, so under the one-call rule they are measured but can't ship. `make eval-arms` answers the dev split through the shippable Arms the screen keeps and applies the spec's selection rule. The comparison, which kept FTS5, is in [`docs/evaluation.md`](docs/evaluation.md#arm-comparison) and [ADR 0008](docs/adr/0008-fts5-stays-the-shipped-arm.md). It also reports how many Required Facts' evidence quotes reach the prompt. `CHUNK_TOKENS=450` and `CONTEXT_BUDGET=24000` score another chunk size or context budget without editing code (an index of that chunk size is built beside the shipped one when missing); the grid that kept 600-token chunks and a 32k budget is in [`docs/evaluation.md`](docs/evaluation.md#chunk-size-and-context-budget) and [ADR 0010](docs/adr/0010-chunk-size-and-context-budget.md).


### Measuring answers

```sh
make eval-generation
```

answers every Golden Set case on the dev split through one real Answer Call each, then scores the answers: citation validity, figure exactness, Coverage Gaps (the answer acknowledges, in any wording, each gap that leaves part of the question unanswered; "periods differ" is shown by the product and not checked) and the answer's structure (a direct answer first, points per Company or a comparison table, 300–600 words; from prompt v15 no closing Coverage note, [ADR 0016](docs/adr/0016-coverage-gaps-shown-by-the-product.md)) are checked in code, and Fact Recall and Faithfulness are judged by Jev, TypeSafe's judgment model, pinned to an exact version; a claim Jev judges contradicted by its Sources (a Contradicted Claim) fails the answer, and the run counts the answers with one. Each answer's cost and latency, from the Answer Call log, are reported next to the scores. It needs `OPENAI_API_KEY` and `JEV_API_KEY` in `backend/.env` and costs about $0.25 per run on version 2's 60 dev cases. `MODEL=` picks another generator from the table (unset, `ANSWER_MODEL`, else `gpt-6-luna`): an OpenAI model, or a Claude model (`MODEL=claude-sonnet-5-5`), which needs `ANTHROPIC_API_KEY` instead of `OPENAI_API_KEY`. Every generator answers at reasoning effort medium with a 32,000-token cap; an answer that stops at the cap is scored as truncated, and the report lists it (`capped`) and prints it. `make eval-generators` runs the default comparison, `COMPARISON` in `backend/src/edgar_eval/generators.py` (or the generators named in `MODELS=`; every one when it is empty) and applies the selection rule; the comparison, which kept `gpt-6-luna`, is in [`docs/evaluation.md`](docs/evaluation.md#generator-comparison) and [ADR 0009](docs/adr/0009-gpt-6-luna-stays-the-generator.md). `SPLIT=holdout` scores the holdout split, which was run once on Golden Set version 1, at the end ([The holdout run](docs/evaluation.md#the-holdout-run)). Both harnesses now run Golden Set version 2 by default, whose holdout has also been scored once, on the same setup ([The version 2 holdout run](docs/evaluation.md#the-version-2-holdout-run)), and once more after spec #116's retrieval rules changed what ships ([The holdout on the new retrieval](docs/evaluation.md#the-holdout-on-the-new-retrieval-130-2026-10-18)); naming version 1's file (`python -m edgar_eval.generation --golden-set ../data/eval/golden_set.json`, likewise `edgar_eval.retrieval`) runs version 1. The report, with every answer, is written to `data/derived/eval/generation-dev.json`; the method and the first scores are in [`docs/evaluation.md`](docs/evaluation.md#generation-harness). `make eval-rescore` reruns a corrected check on the saved reports' answers offline, with no Answer Call and no Jev call: the current round's reports by default, others only when named in `REPORTS=`.

### Showing the results in the workspace

```sh
make eval-export
```

collects the harnesses' latest reports on Golden Set version 2's dev split (every Arm's retrieval scores, its comparison with the Shipped Arm on Evidence Reached and the screen's result; the round's shipped run and Control Run; the Arm and settings comparisons, fact by fact under ADR 0015 with the facts stated split by where their evidence reached; the generator comparison's sign tests, intervals and choice, with each challenger generator's scores, cost and latency; and the Brief Suite's verdicts), the holdout run's reports once the holdout has been scored, the Corpus coverage grid (each Company's Filings by Report Period, Tracked Companies first), each Company's Company Calendar (`companies`: its ticker, name, Sector, coverage class and fiscal year end, and each fiscal quarter and year from its first Filing to its latest with its calendar months, its Filing and, for a Tracked Company, its revenue Financial Fact, read from the Filing by the Financial Facts seam, fourth quarters derived in the export and marked as derived) and the curated Companies missing from the Corpus (`missingCompanies`) into `frontend/data/eval-export.json`. The workspace's "How it works" page (http://localhost:3000/how-it-works, linked from its header) shows them with the architecture, and its Calendar tab shows the calendars. The export runs the retrieval harness first if its report is missing, but never the generation harness, which costs money: until `make eval-generation` has run, the page says so instead of showing answer scores. The export is committed, so the page shows the last exported results without anyone rerunning the harnesses; rerun it and commit the file after a harness run worth publishing.

### The slide deck

The presentation around the demo is [`docs/deck.md`](docs/deck.md), Markdown for [Marp](https://marp.app/): one slide per `---`, with speaker notes in HTML comments. It speaks to the Client in plain language: the choices slide says what was tried and what stayed, with its p-values and Control Runs in the speaker notes, and the value slide carries the illustrative value model of [assumption 12](docs/assumptions.md#12-an-illustrative-value-model), not confirmed. It reads as plain Markdown on GitHub, and `make deck` renders it to `data/derived/deck/deck.html` (it needs Node.js and network access the first time, for `npx` to fetch the pinned Marp CLI; open the HTML in a browser and press `p` for presenter view). Every slide ends with links to the documents its numbers come from, and `backend/tests/test_deck.py` checks that every figure on a slide, speaker notes included, is found word for word in one of them, so a changed evaluation number fails the test until the slide is updated.

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
│   │   ├── golden_set.py      loads and validates the Golden Set and its dev/holdout split
│   │   └── paths.py           the data directory, defined once for every backend package
│   ├── src/edgar_answer/      provider implementations (OpenAI, Anthropic) and the `make ask` CLI
│   ├── src/edgar_api/         the FastAPI chat API (`make api`)
│   ├── src/edgar_eval/        evaluation harnesses: retrieval Arms, their rankers and embeddings, metrics, the selection rule, answer checks, the Jev judge, the export
│   ├── scripts/chat.sh        the `curl` example against the chat API
│   ├── tests/                 pytest suite
│   └── notebooks/             eda.py (source) and eda.ipynb (executed)
├── frontend/                  the Next.js research workspace (`make dev`) and its "How it works" page
├── data/
│   ├── edgar_corpus/          the Corpus, read-only, exactly as supplied
│   ├── reference/sectors.csv  the curated Sector table, one row per Company
│   ├── reference/missing_companies.csv  notable Companies not in the Corpus
│   ├── eval/golden_set.json   Golden Set version 1: labelled evaluation questions and starter prompts
│   ├── eval/golden_set_v2.json  Golden Set version 2, the harnesses' default: 60 dev and 20 holdout cases
│   ├── eval/brief_suite.json  the Brief Suite: the brief's questions and variants, a must-pass check
│   ├── eval/retrieval_floors.json  the lowest retrieval scores CI accepts (ADR 0014)
│   └── derived/               anything built from the Corpus (gitignored)
├── docs/
│   ├── AI-RAG Assessment.md   the assessment brief
│   ├── findings.md            EDA findings and recommendations for retrieval
│   ├── assumptions.md         working assumptions, confirmed or not by the Client
│   ├── golden-set.md          the Golden Set's fields, split rule and review
│   ├── evaluation.md          how quality is measured, and the scores
│   ├── prompt-iterations.md   every version of the Answer Call's prompt template
│   ├── deck.md                the slide deck (Marp Markdown; `make deck` renders it)
│   └── adr/                   architecture decision records
├── scripts/                   the CI checks, run by GitHub Actions and `make ci-cd`
├── .github/                   the GitHub Actions workflows, Dependabot and CODEOWNERS
├── CONTEXT.md                 domain glossary
└── Makefile                   single entry point
```

The core package depends on nothing outside the Python standard library and must not depend on a web framework, so the API and front-end can sit on top of it; a guard test enforces this. Code that needs a provider's SDK lives in `edgar_answer` ([ADR 0005](docs/adr/0005-provider-sdks-outside-the-core-package.md)), the web API in `edgar_api`, the evaluation harnesses in `edgar_eval` ([ADR 0006](docs/adr/0006-evaluation-harnesses-outside-the-core-package.md)), and the research workspace in `frontend/`, which reaches the API only through its own server-side route.

## Data

The Corpus in [`data/edgar_corpus/`](data/edgar_corpus/) is the assessment's zip committed exactly as extracted: 246 Filings from 54 Companies plus `manifest.json`. It is read-only; every cleaning step happens in code. [`data/README.md`](data/README.md) records its source, checksum and how to verify it, and documents the Sector table and the SEC reference data.
