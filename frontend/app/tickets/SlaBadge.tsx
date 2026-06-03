import { SLA_STATE_LABELS, slaStateClass } from "./format";

/**
 * Бейдж состояния SLA (#92, FR-4.3). Состояние вычисляет бэкенд (#89) — фронт только
 * отображает. `none`/отсутствует → нейтральный «—» (индикатор не показываем).
 */
export function SlaBadge({ state }: { state?: string | null }) {
  if (!state || state === "none") {
    return (
      <span className="text-gray-300" aria-hidden="true">
        —
      </span>
    );
  }
  const text = SLA_STATE_LABELS[state] ?? state;
  return (
    <span
      role="status"
      aria-label={`SLA: ${text}`}
      className={`font-medium ${slaStateClass(state)}`}
    >
      ● {text}
    </span>
  );
}
