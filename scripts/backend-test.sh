#!/usr/bin/env bash
# Backend tests (pytest). The suite builds its own small indexes from the Corpus and fakes
# every answer model and the Jev judge, so it makes no network call and costs nothing.
# Called by `make backend-test` and .github/workflows/backend-ci.yml.
set -euo pipefail
cd "$(dirname "$0")/../backend"

# Unset the provider keys so no test can reach a paid API, even from a developer's shell
# or a backend/.env the Makefile exported.
unset OPENAI_API_KEY ANTHROPIC_API_KEY JEV_API_KEY

echo "==> Pytest"
uv run --frozen pytest

echo "backend-test: OK"
