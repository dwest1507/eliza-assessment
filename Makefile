# Single entry point for the project. Run `make help` for the targets.

# `dev` uses bash builtins (wait -n, trap).
SHELL := /bin/bash

BACKEND := backend
FRONTEND := frontend
UV := cd $(BACKEND) && uv run
NPM := cd $(FRONTEND) && npm run --silent

SEC_FACTS_INDEX := data/derived/sec_companyfacts/index.json
INDEX := data/derived/edgar_rag.sqlite
API_PORT ?= 8000
WEB_PORT ?= 3000

# Local settings for the backend (copy backend/.env.example). Optional; the variables
# it defines are exported to the recipes. Make syntax, so values are unquoted.
ENV_FILE := $(BACKEND)/.env
-include $(ENV_FILE)
export $(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' $(ENV_FILE) 2>/dev/null)

.PHONY: help install test lint format eda sec-facts index ask api eval-retrieval dev frontend-deps

help: ## List targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

install: ## Install the backend (uv) and front-end (npm) dependencies
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && npm ci
	@sha256sum $(FRONTEND)/package-lock.json | cut -d' ' -f1 > $(FRONTEND)/node_modules/.deps-stamp

test: frontend-deps ## Run the backend (pytest) and front-end (Vitest) test suites
	$(UV) pytest
	$(NPM) test

lint: frontend-deps ## Lint, type-check and check formatting of the backend and front-end
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(NPM) lint
	$(NPM) typecheck
	$(NPM) format:check

format: frontend-deps ## Auto-fix lint issues and format the backend and front-end
	$(UV) ruff check --fix .
	$(UV) ruff format .
	$(NPM) format

eda: $(SEC_FACTS_INDEX) ## Execute the EDA notebook from its script source and write the paired .ipynb
	$(UV) env JUPYTER_PREFER_ENV_PATH=1 jupytext --to ipynb --set-kernel python3 --execute notebooks/eda.py

sec-facts: ## Fetch SEC XBRL company-facts for Tracked Companies (evaluation only; needs SEC_USER_AGENT)
	@if [ -z "$$SEC_USER_AGENT" ]; then \
		echo 'error: SEC_USER_AGENT is not set. The SEC requires every request to carry a' >&2; \
		echo 'User-Agent naming you and a contact email. Copy backend/.env.example to' >&2; \
		echo 'backend/.env and fill it in.' >&2; \
		exit 1; \
	fi
	$(UV) python -m edgar_rag.sec_reference

index: ## Rebuild the retrieval index (data/derived/edgar_rag.sqlite) from the Corpus
	$(UV) python -m edgar_rag.retrieval

ask: $(INDEX) ## Answer a question from the command line: make ask Q="..." (needs OPENAI_API_KEY)
	@if [ -z "$$Q" ]; then echo 'usage: make ask Q="your question"' >&2; exit 1; fi
	@if [ -z "$$OPENAI_API_KEY" ]; then \
		echo 'error: OPENAI_API_KEY is not set. Copy backend/.env.example to backend/.env' >&2; \
		echo 'and fill it in.' >&2; \
		exit 1; \
	fi
	$(UV) python -m edgar_answer.ask "$$Q"

api: $(INDEX) ## Run the chat API on http://localhost:8000, or API_PORT (answers need OPENAI_API_KEY)
	$(UV) uvicorn edgar_api.app:create_app --factory --host 127.0.0.1 --port $(API_PORT)

eval-retrieval: $(INDEX) ## Score retrieval Arms on the Golden Set: make eval-retrieval [SPLIT=dev|holdout|all]
	$(UV) python -m edgar_eval.retrieval --split $(SPLIT) --json ../data/derived/eval/retrieval-$(SPLIT).json

SPLIT ?= dev

dev: $(INDEX) frontend-deps ## Run the API and the front-end together on http://localhost:3000 (WEB_PORT)
	@echo "API on http://127.0.0.1:$(API_PORT), workspace on http://localhost:$(WEB_PORT). Ctrl+C stops both."
	@set -m; \
	( cd $(BACKEND) && exec uv run uvicorn edgar_api.app:create_app --factory --host 127.0.0.1 --port $(API_PORT) ) & api=$$!; \
	( cd $(FRONTEND) && BACKEND_URL=http://127.0.0.1:$(API_PORT) exec npm run --silent dev -- --port $(WEB_PORT) ) & web=$$!; \
	trap 'kill -- -$$api -$$web 2>/dev/null' EXIT INT TERM; \
	wait -n $$api $$web; \
	echo "A server exited, so the other one is being stopped."; \
	kill -- -$$api -$$web 2>/dev/null; \
	wait $$api $$web 2>/dev/null; true

# Installs the front-end's dependencies when node_modules is missing or package-lock.json
# changed since the last install. The stamp holds the lockfile's hash, not its mtime, so
# a checkout that only touches the file does not reinstall.
frontend-deps:
	@want=$$(sha256sum $(FRONTEND)/package-lock.json | cut -d' ' -f1); \
	stamp=$(FRONTEND)/node_modules/.deps-stamp; \
	if [ ! -f "$$stamp" ] || [ "$$(cat "$$stamp")" != "$$want" ]; then \
		echo "Front-end dependencies are missing or stale; running npm ci..."; \
		(cd $(FRONTEND) && npm ci) && echo "$$want" > "$$stamp"; \
	fi

# `make ask`, `make api`, `make eval-retrieval` and `make dev` build the index first when it
# is missing.
$(INDEX):
	@$(MAKE) --no-print-directory index

# The EDA reads the cached company-facts; fetch them only when the cache is missing.
$(SEC_FACTS_INDEX):
	@$(MAKE) --no-print-directory sec-facts
