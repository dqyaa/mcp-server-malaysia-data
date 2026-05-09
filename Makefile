# Convenience targets for development.
# Run `make help` to list them.

.PHONY: help install install-dev install-all test test-unit test-property test-integration \
        test-contract lint format typecheck cov run-mcp run-rest run-quickstart docker docker-up \
        docker-down clean

PYTHON ?= python
PIP ?= pip

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---- Install ----
install:  ## Install the package with runtime deps only.
	$(PIP) install -e .

install-dev:  ## Install with dev tools (test, lint, typecheck).
	$(PIP) install -e ".[dev,redis]"

install-all:  ## Install everything including agent extras.
	$(PIP) install -e ".[dev,redis,sentry,agent]"

# ---- Tests ----
test:  ## Run unit + property tests (fast, default).
	pytest tests/unit tests/property

test-unit:  ## Unit tests only.
	pytest tests/unit -v

test-property:  ## Property-based tests only.
	pytest tests/property -v

test-integration:  ## Hit live BNM and data.gov.my APIs.
	pytest tests/integration -m integration -v

test-contract:  ## Validate upstream API shapes haven't drifted.
	pytest tests/contract -m contract -v

cov:  ## Run tests with coverage report.
	pytest tests/unit tests/property --cov --cov-report=term --cov-report=html
	@echo "HTML coverage at htmlcov/index.html"

# ---- Quality ----
lint:  ## Ruff lint.
	ruff check src tests

format:  ## Ruff format.
	ruff format src tests

typecheck:  ## Mypy strict.
	mypy src/

# ---- Run ----
run-mcp:  ## Start the MCP server (stdio mode).
	$(PYTHON) -m malaysia_data_mcp.presentation.mcp_server

run-rest:  ## Start the REST/HTTP server on :8000.
	$(PYTHON) -m malaysia_data_mcp.presentation.http_server

run-quickstart:  ## Smoke-test all 15 tools against live APIs.
	$(PYTHON) quickstart.py

# ---- Docker ----
docker:  ## Build the Docker image.
	docker build -f deploy/Dockerfile -t malaysia-data-mcp:latest .

docker-up:  ## Bring up the full stack (server + Redis + Prometheus + Grafana).
	docker compose -f deploy/docker-compose.yml up

docker-down:  ## Tear down the stack.
	docker compose -f deploy/docker-compose.yml down

# ---- Clean ----
clean:  ## Remove caches and build artifacts.
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache .hypothesis htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
