# AGENTS.md

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (dwest1507/eliza-assessment) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one root `CONTEXT.md` plus `docs/adr/`. See `docs/agents/domain.md`.

## Repo layout and commands

- `backend/`: uv-managed Python project holding the `edgar_rag` core package (`src/`), its tests (`tests/`) and the EDA notebook (`notebooks/`). The core package must not depend on a web framework.
- `frontend/`: the Next.js research workspace (npm-managed; Tailwind, AI SDK `useChat`, Vitest). Its server-side route `app/api/chat/route.ts` proxies to the backend's chat API, so the backend URL (`BACKEND_URL`) stays on the server. `lib/starters.ts` copies the Golden Set's starter prompts, and a test keeps the copy in sync. The "How it works" page (`app/how-it-works/page.tsx`) renders the committed evaluation export, `data/eval-export.json`, typed by `lib/evalExport.ts`. See `frontend/README.md`.
- `data/edgar_corpus/`: the Corpus, read-only (see `data/README.md`). Derived files go in `data/derived/` (gitignored).
- `data/reference/sectors.csv`: the curated Sector table, one row per Company (see `data/README.md`).
- `data/reference/missing_companies.csv`: the curated list of notable Companies not in the Corpus, named as Coverage Gaps (see `data/README.md`).
- `data/eval/golden_set.json`: the Golden Set, the evaluation's labelled questions, including the front-end's starter prompts (see `docs/golden-set.md`). Its tests check every label against the Corpus.
- `backend/src/edgar_rag/`: `corpus.py` (the Corpus seam), `financial_facts.py` (the Financial Facts seam), `retrieval.py` (the retrieval seam: build the index, prepare an Answer Context), `answer_model.py` (the answer model protocol and the logged Answer Call), `sec_reference.py` (fetches and reads the SEC company-facts evaluation reference), `golden_set.py` (loads and validates the Golden Set, and computes its dev/holdout split). Standard library only; a guard test enforces it.
- `backend/src/edgar_answer/`: code that needs a provider SDK, kept outside the core package (ADR 0005): `openai_model.py` and `ask.py` (`make ask`).
- `backend/src/edgar_api/`: the FastAPI chat API (`app.py`, `make api`), outside the core package: `POST /api/chat` streams the AI SDK UI message stream (Query Scope and Sources as data parts, then the answer), `GET /api/health`. Stateless. `backend/scripts/chat.sh` is the `curl` example.
- `backend/src/edgar_eval/`: the evaluation harnesses, kept outside the core package (ADR 0006): `retrieval.py` (the retrieval harness, `make eval-retrieval`), `arms.py` (every retrieval Arm, one marked shipped), `metrics.py` (hit@k, recall@k, MRR and McNemar's exact test), `generation.py` (the generation harness, `make eval-generation`, with answer cost per model in `PRICES`), `answer_checks.py` (citation, figure and Coverage Gap checks in code), `judge.py` (Fact Recall and Faithfulness by Jev, pinned in `JEV_MODEL`), `export.py` (the evaluation export for the front-end, `make eval-export`).
- `docs/evaluation.md`: how quality is measured and the scores: each harness's method and its first numbers on dev.
- `docs/findings.md`: EDA findings, each as Finding → Implication → Design decision, ending with recommendations for the retrieval phase.
- `docs/assumptions.md`: every assumption we build under, each marked `confirmed` or `not confirmed` by the Client. `docs/client-email.md` (gitignored, local only) is the draft email asking the Client about the three that matter most, sent by the developer, never by an agent.
- `docs/prompt-iterations.md`: every version of the Answer Call's prompt template. A change to `backend/src/edgar_rag/_prompt.py` bumps `PROMPT_VERSION` and adds an entry.
- `docs/adr/`: architecture decisions, numbered `NNNN-slug.md` (0001: the SQLite Financial Facts store).

Run everything through the root `Makefile`: `make install` (uv sync and npm ci), `make test`, `make lint`, `make format` (each covers the backend and the front-end), `make eda`, `make sec-facts`, `make index`, `make ask Q="..."`, `make api`, `make eval-retrieval`, `make eval-generation`, `make eval-export`, `make dev` (the API and the front-end together; stops both if either exits).

`make index` rebuilds the retrieval index, `data/derived/edgar_rag.sqlite`, from the Corpus. `make ask` answers one question through one Answer Call (it needs `OPENAI_API_KEY` from `backend/.env`, and costs money) and logs it to `data/derived/logs/answer_calls.jsonl`. `make api` serves the same pipeline on port 8000 (`API_PORT` overrides); its tests use FastAPI's test client. Tests never call a provider: they use a fake answer model.

`make eval-retrieval` scores every retrieval Arm on the Golden Set's dev split (`SPLIT=holdout` or `SPLIT=all` to change it) with no LLM call, and writes the report to `data/derived/eval/retrieval-<split>.json`. Tune on dev only; the holdout is scored once, at the end.

`make eval-generation` answers the same split through real Answer Calls and scores the answers (checks in code, Jev judgments, cost and latency), writing `data/derived/eval/generation-<split>.json`. It needs `OPENAI_API_KEY` and `JEV_API_KEY` from `backend/.env` and costs money (about $0.07 per dev run), so run it only when a change to the prompt, retrieval or generator needs scoring. Jev stays pinned to an exact version, never `jev-latest`; a new version is a deliberate change that re-baselines every score.

`make eval-export` writes the latest reports of a split (`SPLIT=`, dev by default) and the Corpus coverage grid to `frontend/data/eval-export.json`, which the "How it works" page renders. It runs the retrieval harness when its report is missing, never the generation harness. The export is committed: regenerate it with `make eval-export`, never edit it by hand, and keep its shape in step with `frontend/lib/evalExport.ts` (the type check fails when they drift).

`make sec-facts` caches the SEC XBRL company-facts data (an evaluation reference for Financial Facts, never an answer source) in `data/derived/sec_companyfacts/`; `make eda` runs it when that cache is missing. The SEC requires a User-Agent with a contact email, read from the `SEC_USER_AGENT` environment variable, which the Makefile loads from `backend/.env`.

Environment files are per app: each app has a gitignored `.env` and a committed `.env.example` with placeholders only, and the app's `.dockerignore` keeps `.env` out of images. The developer fills in `.env`; an agent never creates or edits it and never writes a real value into code, the Makefile, docs, tests, notebook outputs, `.env.example` files or commit messages. A new variable goes into that app's `.env.example` with a placeholder.

The notebook source of truth is `backend/notebooks/eda.py` (jupytext percent format). `make eda` executes it and writes the paired `eda.ipynb` with outputs; commit both and never edit the `.ipynb` by hand.
