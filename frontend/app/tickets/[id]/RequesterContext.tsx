import { shortId } from "../format";
import type { Ticket } from "./types";

/**
 * Заглушка контекста заявителя/объекта. Полные данные User/Premises (имя, адрес,
 * договор) подтянутся по API в E3 (#16); пока показываем только идентификаторы.
 */
export function RequesterContext({ ticket }: { ticket: Ticket }) {
  const rows: { title: string; id: string | null | undefined }[] = [
    { title: "Заявитель", id: ticket.requester_id },
    { title: "Объект", id: ticket.premises_id },
    { title: "Договор/бронь", id: ticket.booking_id },
  ];

  return (
    <section className="flex flex-col gap-2 rounded border border-dashed border-gray-300 p-4">
      <h2 className="text-sm font-medium">Контекст</h2>
      <dl className="grid grid-cols-3 gap-3">
        {rows.map(({ title, id }) => (
          <div key={title} className="flex flex-col gap-0.5">
            <dt className="text-xs text-gray-500">{title}</dt>
            <dd className="font-mono text-sm text-gray-600" title={id ?? undefined}>
              {shortId(id)}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-gray-400">
        Полные данные заявителя и объекта появятся в E3 (#16).
      </p>
    </section>
  );
}
