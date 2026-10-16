# Single entry point for the project. Run `make help` for the targets.

BACKEND := backend
UV := cd $(BACKEND) && uv run

SEC_FACTS_INDEX := data/derived/sec_companyfacts/index.json
INDEX := data/derived/edgar_rag.sqlite
API_PORT ?= 8000

# Local settings for the backend (copy backend/.env.example). Optional; the variables
# it defines are exported to the recipes. Make syntax, so values are unquoted.
ENV_FILE := $(BACKEND)/.env
-include $(ENV_FILE)
export $(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' $(ENV_FILE) 2>/dev/null)

.PHONY: help install test lint format eda sec-facts index ask api

help: ## List targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install: ## Install the backend environment (uv)
	cd $(BACKEND) && uv sync

test: ## Run the backend test suite
	$(UV) pytest

lint: ## Lint and check formatting of the backend
	$(UV) ruff check .
	$(UV) ruff format --check .

format: ## Auto-fix lint issues and format the backend
	$(UV) ruff check --fix .
	$(UV) ruff format .

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

# `make ask` and `make api` build the index first when it is missing.
$(INDEX):
	@$(MAKE) --no-print-directory index

# The EDA reads the cached company-facts; fetch them only when the cache is missing.
$(SEC_FACTS_INDEX):
	@$(MAKE) --no-print-directory sec-facts
