# kb-support backend

FastAPI-сервис модуля службы поддержки reHome.

## Quick start

```bash
# Зависимости (создаёт .venv в backend/, устанавливает runtime + dev)
make install

# Запустить dev-сервер (auto-reload, localhost:8000)
make dev

# Проверить /healthz
curl http://localhost:8000/healthz
# → {"status":"ok"}

# OpenAPI docs (FastAPI Swagger UI)
open http://localhost:8000/docs
```

## Команды разработки

| Цель | Что делает |
|---|---|
| `make install` | Создаёт `.venv/` и устанавливает runtime + dev зависимости |
| `make lint` | `ruff check` + `ruff format --check` |
| `make format` | `ruff format` (in-place) + `ruff check --fix` |
| `make typecheck` | `mypy --strict src tests` |
| `make test` | `pytest` без coverage |
| `make test-cov` | `pytest --cov` с порогом 80% (target для CI) |
| `make dev` | uvicorn с auto-reload |
| `make docker-build` | Сборка Docker-образа `kb-support-backend:dev` |
| `make clean` | Удаление кешей и venv |

## Структура

```
backend/
├── pyproject.toml     ← PEP 621 manifest + ruff/mypy/pytest/coverage конфиг
├── Dockerfile         ← multi-stage: base → builder → runtime (non-root)
├── Makefile
├── conftest.py        ← pytest fixtures (TestClient)
├── src/api/
│   ├── __init__.py
│   └── main.py        ← FastAPI app + /healthz
└── tests/
    └── unit/
        └── test_healthz.py
```

Структура расширится по мере landing'а E1 Issues (#2 — DB, #5-#10 — Ticket
доменная модель, и т.д.).

## Архитектурная константа

kb-support — **отдельный сервис**. Никаких импортов из rehome-kb-platform.
Доступ к User / Premises / Booking / Collaborator — только через HTTP-клиент
(появится в E3). См. `../CLAUDE.md` правило 7.

CI-проверка архитектурной константы (AT-001) активируется в #3.

## Связанные документы

- [../CLAUDE.md](../CLAUDE.md) — операционные правила Разработчика
- [../docs/handoff/01_postanovka/01_TZ_kb_support_v2.2.md](../docs/handoff/01_postanovka/01_TZ_kb_support_v2.2.md) — главное ТЗ
- [../docs/handoff/01_postanovka/04_openapi.yaml](../docs/handoff/01_postanovka/04_openapi.yaml) — контракт OpenAPI v1.1
