import { CHANNEL_LABELS, formatDate, label, TYPE_LABELS } from "../tickets/format";
import type { SupportStats, SupportStatsResult } from "./types";

/**
 * Панель супервайзера (FR-7.1, #170). Сводные агрегаты приходят с бэкенда
 * (`getSupportStats`, #166), который считает их SQL-агрегатами по своей БД (ADR-0011).
 * Секции nullable; страница не падает на отсутствующих полях («—»). 403 → нейтральная
 * ветка «только супервайзеру» (фронт прав не вычисляет — гейт на бэкенде). ai_chat
 * `degraded=true` — kb-search не настроен/недоступен (см. #77), не ошибка.
 *
 * Примечание: секция «загрузка операторов» (по тексту issue) реализуется в #171
 * (`/reports`, отчёт `operators`) — её нет в контракте `SupportStats`.
 */
function num(n: number | null | undefined): string {
  return n == null ? "—" : String(n);
}

function pct(n: number | null | undefined): string {
  return n == null ? "—" : `${n.toFixed(1)}%`;
}

function minutes(n: number | null | undefined): string {
  return n == null ? "—" : `${n.toFixed(0)} мин`;
}

function rating(n: number | null | undefined): string {
  return n == null ? "—" : n.toFixed(2);
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded border border-gray-200 p-4">
      <h2 className="text-sm font-medium">{title}</h2>
      {children}
    </section>
  );
}

function Tile({ title, value }: { title: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-gray-500">{title}</dt>
      <dd className="text-xl font-semibold text-gray-900">{value}</dd>
    </div>
  );
}

function Breakdown({
  title,
  data,
  labels,
}: {
  title: string;
  data: Record<string, number> | undefined;
  labels: Record<string, string>;
}) {
  const entries = Object.entries(data ?? {});
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-xs text-gray-500">{title}</h3>
      {entries.length === 0 ? (
        <p className="text-sm text-gray-400">нет данных</p>
      ) : (
        <ul className="flex flex-col gap-0.5 text-sm text-gray-700">
          {entries.map(([key, count]) => (
            <li key={key} className="flex justify-between gap-4">
              <span>{label(labels, key)}</span>
              <span className="font-medium">{count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Stats({ stats }: { stats: SupportStats }) {
  const { period, tickets, sla, performance, quality, ai_chat } = stats;
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-gray-500">
        Период: {formatDate(period?.from)} — {formatDate(period?.to)}
      </p>

      <Section title="Заявки">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Tile title="Всего создано" value={num(tickets?.total)} />
          <Tile title="Открыто сейчас" value={num(tickets?.open)} />
          <Tile title="Решено" value={num(tickets?.resolved)} />
          <Tile title="Закрыто" value={num(tickets?.closed)} />
        </dl>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Breakdown title="По типу" data={tickets?.by_type} labels={TYPE_LABELS} />
          <Breakdown title="По каналу" data={tickets?.by_channel} labels={CHANNEL_LABELS} />
        </div>
      </Section>

      <Section title="SLA">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Tile title="Соблюдение первого ответа" value={pct(sla?.first_response_compliance_pct)} />
          <Tile title="Соблюдение решения" value={pct(sla?.resolution_compliance_pct)} />
          <Tile title="Нарушений" value={num(sla?.breaches)} />
        </dl>
      </Section>

      <Section title="Производительность">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Tile
            title="Средн. время первого ответа"
            value={minutes(performance?.avg_first_response_minutes)}
          />
          <Tile title="Средн. время решения" value={minutes(performance?.avg_resolution_minutes)} />
          <Tile title="Доля переоткрытий" value={pct(performance?.reopened_rate_pct)} />
        </dl>
      </Section>

      <Section title="Качество">
        <dl className="grid grid-cols-2 gap-4">
          <Tile title="Средняя оценка" value={rating(quality?.avg_rating)} />
          <Tile title="Оценок получено" value={num(quality?.ratings_count)} />
        </dl>
      </Section>

      <Section title="Первая линия (AI-чат)">
        {ai_chat?.degraded ? (
          <p className="text-sm text-gray-500">
            Метрики первой линии недоступны (интеграция kb-search не настроена).
          </p>
        ) : (
          <dl className="grid grid-cols-2 gap-4">
            <Tile title="Containment (без эскалации)" value={pct(ai_chat?.containment_rate_pct)} />
            <Tile title="Эскалировано" value={num(ai_chat?.escalated_count)} />
          </dl>
        )}
      </Section>
    </div>
  );
}

export function StatsSections({ result }: { result: SupportStatsResult }) {
  // 403 — нейтральная ветка (фронт прав не вычисляет, гейт на бэкенде).
  if ("forbidden" in result) {
    return (
      <p className="text-sm text-gray-500">
        Панель супервайзера доступна только пользователям с правом просмотра аналитики.
      </p>
    );
  }
  // Ошибка — фиксированная строка (detail/problem из ApiError наружу не выводим, ФЗ-152).
  if ("error" in result) {
    return (
      <p role="alert" className="text-sm text-red-600">
        {result.error}
      </p>
    );
  }
  return <Stats stats={result.stats} />;
}
