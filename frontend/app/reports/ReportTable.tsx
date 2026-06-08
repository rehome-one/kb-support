import { CHANNEL_LABELS, label, shortId, TYPE_LABELS } from "../tickets/format";
import type { Report } from "./types";

/**
 * Таблица отчёта (FR-7.2, #171). Колонки на каждый из 5 типов (контракт `getReport`,
 * #167). nullable → «—». ФЗ-152: `operator_id` усечён через `shortId`, сырых ПДн нет.
 */
function pct(n: number | null | undefined): string {
  return n == null ? "—" : `${n.toFixed(1)}%`;
}

function minutes(n: number | null | undefined): string {
  return n == null ? "—" : `${n.toFixed(0)} мин`;
}

function num(n: number | null | undefined): string {
  return n == null ? "—" : String(n);
}

const thClass = "px-3 py-2 text-left text-xs font-medium text-gray-500";
const tdClass = "px-3 py-2 text-sm text-gray-700";

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <table className="min-w-full divide-y divide-gray-200">
      <thead>
        <tr>
          {head.map((h) => (
            <th key={h} className={thClass} scope="col">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">{children}</tbody>
    </table>
  );
}

function Empty({ cols }: { cols: number }) {
  return (
    <tr>
      <td className={`${tdClass} text-gray-400`} colSpan={cols}>
        нет данных за период
      </td>
    </tr>
  );
}

export function ReportTable({ report }: { report: Report }) {
  switch (report.report) {
    case "volume": {
      const rows = report.rows ?? [];
      return (
        <Table head={["Измерение", "Значение", "Заявок"]}>
          {rows.length === 0 ? (
            <Empty cols={3} />
          ) : (
            rows.map((r, i) => {
              const labels = r.dimension === "channel" ? CHANNEL_LABELS : TYPE_LABELS;
              return (
                <tr key={i}>
                  <td className={tdClass}>{r.dimension === "channel" ? "Канал" : "Тип"}</td>
                  <td className={tdClass}>{label(labels, r.key)}</td>
                  <td className={tdClass}>{num(r.count)}</td>
                </tr>
              );
            })
          )}
        </Table>
      );
    }
    case "sla": {
      const rows = report.rows ?? [];
      return (
        <Table head={["Соблюдение первого ответа", "Соблюдение решения", "Нарушений"]}>
          {rows.length === 0 ? (
            <Empty cols={3} />
          ) : (
            rows.map((r, i) => (
              <tr key={i}>
                <td className={tdClass}>{pct(r.first_response_compliance_pct)}</td>
                <td className={tdClass}>{pct(r.resolution_compliance_pct)}</td>
                <td className={tdClass}>{num(r.breaches)}</td>
              </tr>
            ))
          )}
        </Table>
      );
    }
    case "satisfaction": {
      const rows = report.rows ?? [];
      return (
        <Table head={["Оценка", "Количество"]}>
          {rows.length === 0 ? (
            <Empty cols={2} />
          ) : (
            rows.map((r, i) => (
              <tr key={i}>
                <td className={tdClass}>{num(r.rating)}</td>
                <td className={tdClass}>{num(r.count)}</td>
              </tr>
            ))
          )}
        </Table>
      );
    }
    case "reopens": {
      const rows = report.rows ?? [];
      return (
        <Table head={["Всего", "Переоткрыто", "Доля переоткрытий"]}>
          {rows.length === 0 ? (
            <Empty cols={3} />
          ) : (
            rows.map((r, i) => (
              <tr key={i}>
                <td className={tdClass}>{num(r.total)}</td>
                <td className={tdClass}>{num(r.reopened)}</td>
                <td className={tdClass}>{pct(r.reopened_rate_pct)}</td>
              </tr>
            ))
          )}
        </Table>
      );
    }
    case "operators": {
      const rows = report.rows ?? [];
      return (
        <Table head={["Оператор", "Решено", "Средн. время решения"]}>
          {rows.length === 0 ? (
            <Empty cols={3} />
          ) : (
            rows.map((r, i) => (
              <tr key={i}>
                <td className={`${tdClass} font-mono`} title={r.operator_id}>
                  {shortId(r.operator_id)}
                </td>
                <td className={tdClass}>{num(r.resolved_count)}</td>
                <td className={tdClass}>{minutes(r.avg_resolution_minutes)}</td>
              </tr>
            ))
          )}
        </Table>
      );
    }
    default:
      return null;
  }
}
