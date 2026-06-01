import { AUTHOR_TYPE_LABELS, formatDateTime, label } from "../format";
import type { TicketMessage } from "./types";

// Сообщения приходят с бэкенда в хронологическом порядке (created_at ASC).
// Внутренние заметки (is_internal) бэкенд отдаёт только оператору (NFR-1.3);
// здесь они визуально отделяются, чтобы их не спутали с ответом заявителю.
export function MessageThread({ messages }: { messages: TicketMessage[] }) {
  if (messages.length === 0) {
    return <p className="text-sm text-gray-500">Сообщений пока нет.</p>;
  }

  return (
    <ol className="flex flex-col gap-3">
      {messages.map((message) => (
        <li
          key={message.id}
          data-internal={message.is_internal ? "true" : "false"}
          className={
            message.is_internal
              ? "rounded border border-amber-300 bg-amber-50 p-3"
              : "rounded border border-gray-200 p-3"
          }
        >
          <div className="flex items-center justify-between gap-2 text-xs text-gray-500">
            <span className="font-medium">{label(AUTHOR_TYPE_LABELS, message.author_type)}</span>
            <div className="flex items-center gap-2">
              {message.is_internal ? (
                <span className="rounded bg-amber-200 px-1.5 py-0.5 font-medium text-amber-900">
                  Внутренняя заметка
                </span>
              ) : null}
              <time dateTime={message.created_at}>{formatDateTime(message.created_at)}</time>
            </div>
          </div>
          <p className="mt-1 whitespace-pre-wrap text-sm">{message.body}</p>
        </li>
      ))}
    </ol>
  );
}
