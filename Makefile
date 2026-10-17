# Single entry point for the project. Run `make help` for the targets.

# `dev` uses bash builtins (wait -n, trap).
SHELL := /bin/bash

BACKEND := backend
FRONTEND := frontend
UV := cd $(BACKEND) && uv run
NPM := cd $(FRONTEND) && npm run --silent

SEC_FACTS_INDEX := data/derived/sec_companyfacts/index.json
INDEX := data/derived/edgar_rag.sqlite
EMBEDDINGS := data/derived/embeddings/text-embedding-3-small.npy
API_PORT ?= 8000
WEB_PORT ?= 3000

# Local settings for the backend (copy backend/.env.example). Optional; the variables
# it defines are exported to the recipes. Make syntax, so values are unquoted.
ENV_FILE := $(BACKEND)/.env
-include $(ENV_FILE)
export $(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' $(ENV_FILE) 2>/dev/null)

# The API key variables a generator's provider needs, read from the table of compared
# generators (edgar_eval.generators.GENERATORS): `$(GENERATOR_KEYS) MODEL` for one model
# (none for the default generator), `$(GENERATOR_KEYS) --all` for every one.
GENERATOR_KEYS = $(UV) python -m edgar_eval.generators keys

# Stops a recipe unless every variable named in $(1), a shell word list, is set.
define require_keys
for key in $(1); do \
		if [ -z "$${!key}" ]; then \
			echo "error: $$key must be set. Copy backend/.env.example to backend/.env" >&2; \
			echo 'and fill it in.' >&2; \
			exit 1; \
		fi; \
	done
endef

.PHONY: help install test lint format eda sec-facts index embeddings ask api eval-retrieval eval-generation eval-rescore eval-arms eval-generators eval-export deck dev frontend-deps

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

embeddings: $(INDEX) ## Embed every chunk for the dense and hybrid Arms (evaluation only; needs OPENAI_API_KEY; costs about 35 cents and takes about 25 minutes)
	@if [ -z "$$OPENAI_API_KEY" ]; then \
		echo 'error: OPENAI_API_KEY is not set. Copy backend/.env.example to backend/.env' >&2; \
		echo 'and fill it in.' >&2; \
		exit 1; \
	fi
	$(UV) python -m edgar_eval.embeddings

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

eval-retrieval: $(INDEX) $(if $(filter dense hybrid,$(or $(ARMS),dense)),$(EMBEDDINGS)) ## Score retrieval Arms on the Golden Set: make eval-retrieval [SPLIT=dev|holdout|all] [ARMS="fts5 ..."]
	$(UV) python -m edgar_eval.retrieval --split $(SPLIT) $(foreach arm,$(ARMS),--arm $(arm)) \
		--json ../data/derived/eval/retrieval-$(SPLIT).json

eval-generation: $(INDEX) $(if $(filter dense hybrid,$(ARM)),$(EMBEDDINGS)) ## Score answers on the Golden Set: make eval-generation [SPLIT=...] [MODEL=...] [ARM=...] (costs money)
	@keys=$$($(GENERATOR_KEYS) $(MODEL)) || exit 1; \
	$(call require_keys,$$keys JEV_API_KEY)
	$(UV) python -m edgar_eval.generation --split $(SPLIT) $(if $(MODEL),--model $(MODEL)) \
		$(if $(ARM),--arm $(ARM)) \
		--json ../data/derived/eval/generation-$(if $(ARM),arms-$(SPLIT)-$(ARM),$(SPLIT)$(if $(MODEL),-$(MODEL))).json

# Every saved generation report, the prompt iterations' included.
GENERATION_REPORTS = $(wildcard data/derived/eval/generation-*.json data/derived/eval/prompt-iterations/generation-*.json)

eval-rescore: $(INDEX) ## Redo the figure check of every saved generation report from its stored answers, in place (no Answer Call, no Jev call)
	@if [ -z "$(GENERATION_REPORTS)" ]; then echo 'No saved generation reports in data/derived/eval/.'; exit 0; fi
	$(UV) python -m edgar_eval.generation --rescore $(addprefix ../,$(GENERATION_REPORTS))

eval-arms: $(INDEX) $(EMBEDDINGS) ## Answer the split through every Arm and choose one by the selection rule (costs money)
	@keys=$$($(GENERATOR_KEYS)) || exit 1; \
	$(call require_keys,$$keys JEV_API_KEY)
	$(UV) python -m edgar_eval.selection arms --split $(SPLIT)

eval-generators: $(INDEX) ## Answer the split with each of the four generators and choose one by the selection rule (costs money)
	@keys=$$($(GENERATOR_KEYS) --all) || exit 1; \
	$(call require_keys,$$keys JEV_API_KEY)
	$(UV) python -m edgar_eval.selection generators --split $(SPLIT)

SPLIT ?= dev
RETRIEVAL_REPORT = data/derived/eval/retrieval-$(SPLIT).json

eval-export: $(RETRIEVAL_REPORT) ## Export the latest eval results and Corpus coverage for the "How it works" page [SPLIT=...]
	$(UV) python -m edgar_eval.export --split $(SPLIT)

# The slide deck is Markdown for Marp (docs/deck.md); npx fetches the pinned Marp CLI.
MARP := npx --yes @marp-team/marp-cli@4.5.1

deck: ## Render the slide deck (docs/deck.md) to data/derived/deck/deck.html with Marp
	$(MARP) docs/deck.md --output data/derived/deck/deck.html

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

# `make ask`, `make api`, the `eval-` targets and `make dev` build the index first when it
# is missing.
$(INDEX):
	@$(MAKE) --no-print-directory index

# The dense and hybrid Arms read the chunk embeddings; build them only when missing. A
# rebuilt index with different chunks makes them refuse to load: run `make embeddings`.
$(EMBEDDINGS):
	@$(MAKE) --no-print-directory embeddings

# `make eval-export` runs the retrieval harness first when its report is missing, on the
# Shipped Arm only (it makes no LLM call and needs no embeddings). The generation harness
# costs money, so it only ever runs when asked for.
$(RETRIEVAL_REPORT):
	@$(MAKE) --no-print-directory eval-retrieval SPLIT=$(SPLIT) ARMS=fts5

# The EDA reads the cached company-facts; fetch them only when the cache is missing.
$(SEC_FACTS_INDEX):
	@$(MAKE) --no-print-directory sec-facts
