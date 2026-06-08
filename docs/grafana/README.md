# Grafana-дашборды kb-support

Декларативные JSON-дашборды Grafana для модуля службы поддержки (FR-7.3, эпик #21,
[ADR-0011](../adr/0011-analytics.md)). **В репозитории лежит только JSON-описание
дашборда** — сам провижининг в Grafana выполняет **ops** (ADR-0011: «Grafana — JSON-файлы
в репо, провижининг в Grafana — ops»). Прод-кода здесь нет.

## Дашборды

| Файл | Назначение |
|---|---|
| [`kb-support-overview.json`](./kb-support-overview.json) | Обзор поддержки: rate входящих заявок, нарушения SLA, время в очереди (TTFR) и до решения (TTR). |

## Источник данных

Все панели читают **Prometheus**, который скрейпит эндпоинт `/metrics` бэкенда kb-support
(`backend/src/api/observability/metrics.py`). Метрики регистрируются в дефолтном реестре
`prometheus_client` и экспонируются в формате Prometheus.

Дашборд **не привязан к конкретному источнику данных**: он использует входную переменную
`${DS_PROMETHEUS}` (тип `prometheus`). При импорте/провижининге Grafana подставит реальный
источник (см. ниже).

> **Заметка ops про `/metrics`:** эндпоинт `/metrics` отдаётся без аутентификации
> (observability-контур). Он должен быть доступен только Prometheus внутри инфраструктуры
> и **не выставляться публично** — закрыть на уровне сети / reverse-proxy / scrape-конфига.

## Карта «панель → метрика → источник»

Каждая панель ссылается **только** на метрики, реально экспортируемые бэкендом (сверено с кодом):

| Панель | Метрика | Тип | Лейблы | Источник (issue / файл) |
|---|---|---|---|---|
| Создано заявок (за период) / Rate входящих заявок — всего, по каналу, по типу | `tickets_created_total` | Counter | `type`, `channel` | #168 · `analytics/metrics.py` |
| Нарушений SLA (за период) / Нарушения SLA — по виду (`kind`) / по команде (`team`) | `sla_breaches_total` | Counter | `type`, `priority`, `team`, `kind` | #91 · `tickets/sla_metrics.py` |
| Время в очереди (TTFR) — p50/p90/p95 + stat p90 | `sla_time_to_first_response_seconds` | Histogram | `type`, `priority`, `team` | #91 · `tickets/sla_metrics.py` |
| Время до решения (TTR) — p50/p90/p95 + stat p90 | `sla_time_to_resolution_seconds` | Histogram | `type`, `priority`, `team` | #91 · `tickets/sla_metrics.py` |

Гистограммные квантили считаются по суффиксу `_bucket` с агрегацией по `le`
(`histogram_quantile(q, sum(rate(<metric>_bucket[$__rate_interval])) by (le))`). Окна rate —
через нативную переменную Grafana `$__rate_interval` (корректна при любом scrape-интервале).

### Почему нет панели «queue time» как отдельной метрики

Постановка FR-7.3 упоминает «время в очереди» (а тело issue #169 — `support_queue_time_seconds`).
Эта **отдельная метрика сознательно не вводилась** (см. #168 и docstring `analytics/metrics.py`):
«время в очереди» = интервал `created → first_responded` = это и есть
`sla_time_to_first_response_seconds` (TTFR, #91). Отдельная метрика была бы дублем того же
интервала на том же событии. Поэтому панели «Время в очереди» опираются на TTFR.

### Почему нет панели «containment»

Containment AI-чата (#21 / FR-7.3) **не является Prometheus-метрикой**: его отдаёт kb-search,
и доступен он только через `GET /support/stats` (config-gated seam #166) — знаменателя
(всего обращений в чат) в kb-support нет. Выносить его на Grafana из `/metrics` нельзя без
заглушки (что было бы костылём). Containment смотрите в **панели супервайзера** во фронтенде
оператора (`/dashboard`, #170), а не в Grafana.

## ФЗ-152 / ПДн

Все используемые метрики имеют лейблы **низкой кардинальности без ПДн**
(`type` / `channel` / `priority` / `team` / `kind`). На дашборде нет `ticket_id`,
`requester_id`, email, телефонов и прочих ПДн. **При расширении дашбордов не добавляйте
high-cardinality лейблы и любые идентификаторы пользователей** — это и риск ФЗ-152, и
деградация Prometheus.

## Провижининг (ops)

Provisioning-манифесты (ConfigMap / sidecar / Helm-values) **намеренно не хранятся в этом
репозитории** — это зона ops и зависит от конкретного деплоя Grafana (ADR-0011). Ниже —
how-to; выберите способ под вашу инсталляцию.

### Вариант A. File-based provisioning (рекомендуется для staging/prod)

1. Положите `kb-support-overview.json` в каталог дашбордов Grafana, например
   `/var/lib/grafana/dashboards/kb-support/`.
2. Добавьте provider в `/etc/grafana/provisioning/dashboards/kb-support.yaml`:

   ```yaml
   apiVersion: 1
   providers:
     - name: kb-support
       orgId: 1
       folder: kb-support
       type: file
       disableDeletion: false
       updateIntervalSeconds: 30
       allowUiUpdates: false
       options:
         path: /var/lib/grafana/dashboards/kb-support
         foldersFromFilesStructure: false
   ```

3. Убедитесь, что источник данных Prometheus сконфигурирован (provisioning datasources или
   вручную). При file-provisioning Grafana разрешает `${DS_PROMETHEUS}` в дашборде по
   единственному/дефолтному Prometheus-источнику; либо задайте конкретный datasource при
   подготовке файла.
4. Перезапустите / дождитесь reload Grafana — дашборд появится в папке `kb-support`.

### Вариант B. Ручной импорт (для локальной проверки)

1. Grafana → **Dashboards → New → Import**.
2. Загрузите `kb-support-overview.json`.
3. В диалоге выберите ваш Prometheus в поле **Prometheus** (`${DS_PROMETHEUS}`).
4. **Import**.

### Предпосылки

- Prometheus скрейпит `/metrics` kb-support (job настраивается на стороне ops).
- Метрики появляются только после реального трафика: счётчики (`tickets_created_total`,
  `sla_breaches_total`) и гистограммы (TTFR/TTR) инкрементируются на создании заявок,
  нарушениях SLA, первом ответе и решении. На пустой системе панели будут без данных — это
  ожидаемо.

## Совместимость

Дашборд использует стоковые типы панелей (`timeseries`, `stat`) и источник `prometheus` —
без сторонних плагинов. `schemaVersion: 39` (Grafana 10+). На более ранних версиях возможна
конвертация схемы при импорте.
