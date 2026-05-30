# kb-support backend

FastAPI-сервис модуля службы поддержки reHome.

## Quick start

```bash
# Зависимости (создаёт .venv в backend/, устанавливает runtime + dev)
make install

# Поднять Postgres (docker compose)
make db-up

# Применить миграции
make migrate

# Запустить dev-сервер (auto-reload, localhost:8000)
make dev

# Проверить /healthz
curl http://localhost:8000/healthz
# → {"status":"ok"}

# OpenAPI docs (FastAPI Swagger UI)
open http://localhost:8000/docs
```

## Конфигурация (env vars)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `KBS_DATABASE_URL` | `postgresql+asyncpg://kbsupport:devpass@localhost:5432/kbsupport` | Async DSN PostgreSQL (asyncpg driver) |
| `KBS_DATABASE_POOL_SIZE` | `10` | Размер connection pool'а |
| `KBS_DATABASE_POOL_MAX_OVERFLOW` | `20` | Сверх pool_size, временные коннекты |
| `KBS_DATABASE_ECHO` | `false` | SQLAlchemy echo (debug) |

Для local dev переменные подтягиваются из `.env` в `backend/`. В production —
из env / Kubernetes secrets / etc.

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
| `make db-up` / `db-down` / `db-logs` | docker compose: Postgres lifecycle |
| `make migrate` / `migrate-down` | `alembic upgrade head` / `downgrade -1` |
| `make revision m="<message>"` | Создать новую миграцию (autogenerate) |
| `make arch-check` | AT-001 — проверка архитектурной константы (см. правило 7 CLAUDE.md) |

## Контрактные тесты (AT-002)

`tests/contract/` проверяют, что реализация не дрейфует от контракта
`docs/openapi.yaml` (production-spec, см. #11). Реальные ответы приложения
валидируются против схем ответов операций (`jsonschema`; OpenAPI 3.1 = JSON
Schema 2020-12). Если изменить схему ответа в коде без обновления yaml — тест падает.

```bash
# Требуют Postgres (как остальные integration-тесты):
POSTGRES_AVAILABLE=1 KBS_DATABASE_URL=postgresql+asyncpg://... \
  pytest tests/contract/ -v

# Дополнительно — Prism mock из той же спеки (opt-in, тянет prism через npx):
RUN_PRISM_CONTRACT=1 POSTGRES_AVAILABLE=1 KBS_DATABASE_URL=... \
  pytest tests/contract/ -v
```

В CI контрактные тесты гоняются в job «Backend (Python)» (шаг «Contract tests
(AT-002)»); Prism-тест там скипается (env не выставлен), jsonschema drift-детектор
работает на сервисном Postgres.

## Структура

```
backend/
├── pyproject.toml         ← PEP 621 manifest + ruff/mypy/pytest/coverage конфиг
├── Dockerfile             ← multi-stage: base → builder → runtime (non-root)
├── Makefile
├── docker-compose.yml     ← Postgres 16 для local dev
├── alembic.ini            ← Alembic config
├── alembic/
│   ├── env.py             ← async-aware migrations env
│   ├── script.py.mako     ← template новой миграции
│   └── versions/          ← миграции (`YYYYMMDD_HHMMSS_<slug>.py`)
├── conftest.py            ← pytest fixtures (TestClient + DB session)
├── src/api/
│   ├── __init__.py
│   ├── main.py            ← FastAPI app + /healthz
│   ├── config.py          ← pydantic-settings (env KBS_*)
│   └── db/
│       ├── __init__.py    ← engine, session_factory, get_session()
│       └── base.py        ← DeclarativeBase
└── tests/
    └── unit/
        ├── test_healthz.py
        └── test_db_smoke.py
```

Структура расширится по мере landing'а E1 Issues (#2 — DB, #5-#10 — Ticket
доменная модель, и т.д.).

## Архитектурная константа

kb-support — **отдельный сервис**. Никаких импортов из rehome-kb-platform.
Доступ к User / Premises / Booking / Collaborator — только через HTTP-клиент
(появится в E3). См. `../CLAUDE.md` правило 7.

**AT-001 — CI-проверка архитектурной константы активна** (PR #3, 2026-05-30).
Локально: `make arch-check`. Скрипт: `../scripts/check-arch-constraint.sh`.

## Связанные документы

- [../CLAUDE.md](../CLAUDE.md) — операционные правила Разработчика
- [../docs/handoff/01_postanovka/01_TZ_kb_support_v2.2.md](../docs/handoff/01_postanovka/01_TZ_kb_support_v2.2.md) — главное ТЗ
- [../docs/handoff/01_postanovka/04_openapi.yaml](../docs/handoff/01_postanovka/04_openapi.yaml) — контракт OpenAPI v1.1
