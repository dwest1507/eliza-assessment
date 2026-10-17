#!/usr/bin/env bash
# Lighthouse CI budget check against the production build.
# Assertions live in frontend/lighthouserc.json (>= 0.9 on a11y/BP/SEO; perf warns).
# The audited pages render without the chat API, so no backend runs and no answer is asked.
# Called by `make lighthouse` and .github/workflows/lighthouse.yml.
set -euo pipefail
cd "$(dirname "$0")/../frontend"

if [ ! -d node_modules ]; then
  echo "error: frontend/node_modules missing — run 'make install' first" >&2
  exit 1
fi

echo "==> Next.js production build"
npm run --silent build

echo "==> Lighthouse CI (autorun)"
npx --yes @lhci/cli@0.14.x autorun

echo "lighthouse: OK"
