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
- `docs/findings.md`: EDA findings, each as Finding → Implication → Design decision.

Run everything through the root `Makefile`: `make install` (uv sync), `make test`, `make lint`, `make format`, `make eda`.

The notebook source of truth is `backend/notebooks/eda.py` (jupytext percent format). `make eda` executes it and writes the paired `eda.ipynb` with outputs; commit both and never edit the `.ipynb` by hand.
