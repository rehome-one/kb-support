import {
  HISTORY_ACTION_LABELS,
  formatDateTime,
  formatHistoryDiff,
  label,
  shortId,
} from "../format";
import type { TicketHistoryEntry } from "./types";

// История приходит в обратном хронологическом порядке (created_at DESC, новые сверху).
export function HistoryTimeline({ entries }: { entries: TicketHistoryEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-sm text-gray-500">История пуста.</p>;
  }

  return (
    <ol className="flex flex-col gap-2">
      {entries.map((entry) => {
        const diff = formatHistoryDiff(entry.from_value, entry.to_value);
        return (
          <li key={entry.id} className="flex flex-col gap-0.5 border-l-2 border-gray-200 pl-3">
            <div className="flex items-center justify-between gap-2 text-xs text-gray-500">
              <span className="font-medium text-gray-700">
                {label(HISTORY_ACTION_LABELS, entry.action)}
              </span>
              <time dateTime={entry.created_at}>{formatDateTime(entry.created_at)}</time>
            </div>
            <div className="text-xs text-gray-500">
              <span className="font-mono" title={entry.actor_id}>
                {shortId(entry.actor_id)}
              </span>
              {diff ? <span className="ml-2">{diff}</span> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
