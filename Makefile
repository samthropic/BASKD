# Convenience targets. Every target is a thin wrapper around a `uv` command that is
# documented in README.md, so Windows users (or anyone without `make`) can run those directly.

.DEFAULT_GOAL := help
.PHONY: help install run run-memory test test-integration cov lint fmt typecheck check demo clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Create the virtualenv and install exactly the locked dependencies
	uv sync --locked

run: ## Run the API with settings from .env / environment (reloads on code changes)
	uv run uvicorn baskd.app:create_app --factory --reload --port 8000

run-memory: ## Run the API against the in-memory fake provider (no credentials needed)
	BASKD_PROVIDER=memory uv run uvicorn baskd.app:create_app --factory --reload --port 8000

test: ## Run the fast test suite (integration tests auto-skip without credentials)
	uv run pytest

test-integration: ## Run only the tests that hit the real provider (needs .env / credentials)
	uv run pytest -m integration -ra

cov: ## Run tests with a coverage report
	uv run pytest --cov --cov-report=term-missing

lint: ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-format and auto-fix lint findings
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Static type check
	uv run mypy

check: lint typecheck test ## Everything CI runs

demo: ## Exercise the create -> get -> list -> update -> delete workflow against a running server
	uv run python scripts/demo.py

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
