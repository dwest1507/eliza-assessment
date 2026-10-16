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
- `frontend/`: reserved for the Next.js front-end.
- `data/edgar_corpus/`: the Corpus, read-only (see `data/README.md`). Derived files go in `data/derived/` (gitignored).
- `data/reference/sectors.csv`: the curated Sector table, one row per Company (see `data/README.md`).
- `data/eval/golden_set.json`: the Golden Set, the evaluation's labelled questions, including the front-end's starter prompts (see `docs/golden-set.md`). Its tests check every label against the Corpus.
- `backend/src/edgar_rag/`: `corpus.py` (the Corpus seam), `financial_facts.py` (the Financial Facts seam), `sec_reference.py` (fetches and reads the SEC company-facts evaluation reference), `golden_set.py` (loads and validates the Golden Set, and computes its dev/holdout split).
- `docs/findings.md`: EDA findings, each as Finding → Implication → Design decision, ending with recommendations for the retrieval phase.
- `docs/assumptions.md`: every assumption we build under, each marked `confirmed` or `not confirmed` by the Client. `docs/client-email.md` (gitignored, local only) is the draft email asking the Client about the three that matter most, sent by the developer, never by an agent.
- `docs/adr/`: architecture decisions, numbered `NNNN-slug.md` (0001: the SQLite Financial Facts store).

Run everything through the root `Makefile`: `make install` (uv sync), `make test`, `make lint`, `make format`, `make eda`, `make sec-facts`.

`make sec-facts` caches the SEC XBRL company-facts data (an evaluation reference for Financial Facts, never an answer source) in `data/derived/sec_companyfacts/`; `make eda` runs it when that cache is missing. The SEC requires a User-Agent with a contact email, read from the `SEC_USER_AGENT` environment variable, which the Makefile loads from `backend/.env`.

Environment files are per app: each app has a gitignored `.env` and a committed `.env.example` with placeholders only, and the app's `.dockerignore` keeps `.env` out of images. The developer fills in `.env`; an agent never creates or edits it and never writes a real value into code, the Makefile, docs, tests, notebook outputs, `.env.example` files or commit messages. A new variable goes into that app's `.env.example` with a placeholder.

The notebook source of truth is `backend/notebooks/eda.py` (jupytext percent format). `make eda` executes it and writes the paired `eda.ipynb` with outputs; commit both and never edit the `.ipynb` by hand.
