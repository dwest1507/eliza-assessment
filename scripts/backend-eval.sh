#!/usr/bin/env bash
# Retrieval quality gate: rebuilds the index from the Corpus, scores the Shipped Arm
# (FTS5) on the Golden Set's dev split, and fails if hit@10, recall@10 or MRR drops below
# its Floor in data/eval/retrieval_floors.json, or that record is stale (ADR 0011).
# Called by `make eval-gate` and .github/workflows/backend-ci.yml.
#
# Retrieval makes no LLM call and FTS5 needs no embeddings, so this costs nothing. The
# generation harness, which does cost money, never runs in CI.
#
# Set RECORD_FLOORS=1 to re-record the Floors from this run instead of checking them
# (`make eval-floors`), after a change to the Golden Set or the shipped settings.
set -euo pipefail
cd "$(dirname "$0")/../backend"

unset OPENAI_API_KEY ANTHROPIC_API_KEY JEV_API_KEY

# Its own report path, so the gate never overwrites `make eval-retrieval`'s report.
REPORT=../data/derived/eval/retrieval-gate.json

# Always rebuilt: an index left by older code would measure that code, not this one.
echo "==> Build the index"
uv run --frozen python -m edgar_rag.retrieval

echo "==> Retrieval eval (Shipped Arm, dev split)"
uv run --frozen python -m edgar_eval.retrieval --split dev --arm fts5 --json "$REPORT"

if [ "${RECORD_FLOORS:-0}" = "1" ]; then
  echo "==> Record the retrieval Floors"
  uv run --frozen python -m edgar_eval.floors record "$REPORT"
else
  echo "==> Check the retrieval Floors"
  uv run --frozen python -m edgar_eval.floors check "$REPORT"
fi

echo "backend-eval: OK"
