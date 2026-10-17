#!/usr/bin/env bash
# Frontend quality gate: ESLint, Prettier check, TypeScript check.
# Called by `make frontend-quality` and .github/workflows/frontend-ci.yml.
set -euo pipefail
cd "$(dirname "$0")/../frontend"

if [ ! -d node_modules ]; then
  echo "error: frontend/node_modules missing — run 'make install' first" >&2
  exit 1
fi

echo "==> ESLint"
npm run --silent lint

echo "==> Prettier check"
npm run --silent format:check

echo "==> TypeScript check"
npm run --silent typecheck

echo "frontend-quality: OK"
