#!/usr/bin/env bash
# Frontend production build.
# Called by `make frontend-build` and .github/workflows/frontend-ci.yml.
set -euo pipefail
cd "$(dirname "$0")/../frontend"

if [ ! -d node_modules ]; then
  echo "error: frontend/node_modules missing — run 'make install' first" >&2
  exit 1
fi

echo "==> Next.js production build"
npm run --silent build

echo "frontend-build: OK"
