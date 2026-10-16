# Single entry point for the project. Run `make help` for the targets.

BACKEND := backend
UV := cd $(BACKEND) && uv run

.PHONY: help install test lint format eda

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

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

eda: ## Execute the EDA notebook from its script source and write the paired .ipynb
	$(UV) env JUPYTER_PREFER_ENV_PATH=1 jupytext --to ipynb --set-kernel python3 --execute notebooks/eda.py
