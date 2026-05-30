# Makefile для kb-support backend. Все цели запускаются из директории backend/.
.PHONY: help install lint format typecheck test test-cov dev docker-build clean

PYTHON ?= python3
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PYBIN  := $(VENV)/bin

help: ## Показать список доступных целей
	@awk 'BEGIN {FS = ":.*##"; printf "Доступные цели:\n"} /^[a-zA-Z_-]+:.*##/ {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: $(VENV)/bin/activate ## Установить зависимости (runtime + dev)
	$(PIP) install -e ".[dev]"

lint: ## ruff check + ruff format --check
	$(PYBIN)/ruff check src tests
	$(PYBIN)/ruff format --check src tests

format: ## ruff format (in-place)
	$(PYBIN)/ruff format src tests
	$(PYBIN)/ruff check --fix src tests

typecheck: ## mypy --strict
	$(PYBIN)/mypy src tests

test: ## pytest без coverage
	$(PYBIN)/pytest

test-cov: ## pytest + coverage (CI target)
	$(PYBIN)/pytest --cov=src/api --cov-report=term-missing --cov-report=xml --cov-fail-under=80

dev: ## uvicorn с auto-reload (localhost:8000)
	$(PYBIN)/uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

docker-build: ## Собрать Docker-образ
	docker build -t kb-support-backend:dev .

clean: ## Удалить кеши и venv
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
