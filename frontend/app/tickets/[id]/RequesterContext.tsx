import {
  BOOKING_STATUS_LABELS,
  COLLABORATOR_CATEGORY_LABELS,
  formatDate,
  formatMoney,
  label,
  PREMISES_KIND_LABELS,
  shortId,
  USER_ROLE_LABELS,
} from "../format";
import type { RequesterContextResult, Ticket } from "./types";

/**
 * Контекст заявителя на карточке оператора (FR-2.2, #73). Данные приходят с бэкенда
 * (`getRequesterContext`, #81), который ходит в rehome.one platform. Секции независимы
 * и nullable; страница не падает при недоступности (graceful degradation, как переписка/
 * история в #46). `degraded=true` — интеграция platform не настроена (см. #77), не ошибка.
 */
function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-gray-500">{title}</dt>
      <dd className="text-sm text-gray-700">{children}</dd>
    </div>
  );
}

function IdFallback({ title, id }: { title: string; id: string | null | undefined }) {
  return (
    <Field title={title}>
      <span className="font-mono text-gray-600" title={id ?? undefined}>
        {shortId(id)}
      </span>
    </Field>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded border border-gray-200 p-4">
      <h2 className="text-sm font-medium">Контекст заявителя</h2>
      {children}
    </section>
  );
}

export function RequesterContext({
  ticket,
  result,
}: {
  ticket: Ticket;
  result: RequesterContextResult;
}) {
  // 403 — отдельная нейтральная ветка (как история в #46), не «ошибка загрузки».
  if ("forbidden" in result) {
    return (
      <Frame>
        <p className="text-sm text-gray-500">Контекст заявителя доступен только операторам.</p>
      </Frame>
    );
  }
  // Ошибка — фиксированная строка (detail/problem из ApiError наружу не выводим, ФЗ-152).
  if ("error" in result) {
    return (
      <Frame>
        <p role="alert" className="text-sm text-red-600">
          {result.error}
        </p>
      </Frame>
    );
  }

  const { user, premises, booking, collaborator, degraded } = result.context;

  return (
    <Frame>
      {degraded && (
        <p className="text-sm text-gray-500">
          Контекст из платформы недоступен (интеграция не настроена). Показаны идентификаторы.
        </p>
      )}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        {user ? (
          <>
            <Field title="Заявитель">{user.display_name}</Field>
            <Field title="Роль">{label(USER_ROLE_LABELS, user.role)}</Field>
            <Field title="Email">{user.email ?? "—"}</Field>
            <Field title="Телефон">{user.phone ?? "—"}</Field>
          </>
        ) : (
          <IdFallback title="Заявитель" id={ticket.requester_id} />
        )}

        {premises ? (
          <>
            <Field title="Объект">{premises.address}</Field>
            <Field title="Тип объекта">{label(PREMISES_KIND_LABELS, premises.kind)}</Field>
            {premises.rooms != null && <Field title="Комнат">{premises.rooms}</Field>}
            {premises.area_m2 != null && <Field title="Площадь">{premises.area_m2} м²</Field>}
          </>
        ) : (
          ticket.premises_id && <IdFallback title="Объект" id={ticket.premises_id} />
        )}

        {booking ? (
          <>
            <Field title="Договор/бронь">{label(BOOKING_STATUS_LABELS, booking.status)}</Field>
            <Field title="Период">
              {formatDate(booking.period_start)} —{" "}
              {booking.period_end ? formatDate(booking.period_end) : "бессрочно"}
            </Field>
            {booking.monthly_rent != null && (
              <Field title="Аренда/мес">{formatMoney(booking.monthly_rent)}</Field>
            )}
          </>
        ) : (
          ticket.booking_id && <IdFallback title="Договор/бронь" id={ticket.booking_id} />
        )}

        {collaborator && (
          <>
            <Field title="Коллаборант">{collaborator.name}</Field>
            <Field title="Категория">
              {label(COLLABORATOR_CATEGORY_LABELS, collaborator.category)}
            </Field>
            {collaborator.contact?.email && (
              <Field title="Email коллаборанта">{collaborator.contact.email}</Field>
            )}
            {collaborator.contact?.phone && (
              <Field title="Телефон коллаборанта">{collaborator.contact.phone}</Field>
            )}
          </>
        )}
      </dl>
    </Frame>
  );
}
