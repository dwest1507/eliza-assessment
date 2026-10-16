# Single entry point for the project. Run `make help` for the targets.

BACKEND := backend
UV := cd $(BACKEND) && uv run

SEC_FACTS_INDEX := data/derived/sec_companyfacts/index.json

.PHONY: help install test lint format eda sec-facts

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

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
		echo 'User-Agent naming you and a contact email. Set it for the command, e.g.' >&2; \
		echo '  SEC_USER_AGENT="Your Name you@example.com" make sec-facts' >&2; \
		exit 1; \
	fi
	$(UV) python -m edgar_rag.sec_reference

# The EDA reads the cached company-facts; fetch them only when the cache is missing.
$(SEC_FACTS_INDEX):
	@$(MAKE) --no-print-directory sec-facts
