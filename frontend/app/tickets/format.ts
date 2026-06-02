// Карты лейблов доменных enum (RU). Ключи покрывают все значения контракта —
// добавление значения в контракт требует добавления лейбла (защита от пропусков).

export const STATUS_LABELS: Record<string, string> = {
  NEW: "Новая",
  OPEN: "В работе",
  PENDING: "Ждёт заявителя",
  WAITING: "Ждёт 3-ю сторону",
  ESCALATED: "Эскалирована",
  RESOLVED: "Решена",
  CLOSED: "Закрыта",
  REOPENED: "Переоткрыта",
};

export const PRIORITY_LABELS: Record<string, string> = {
  low: "Низкий",
  normal: "Обычный",
  high: "Высокий",
  critical: "Критический",
};

export const TYPE_LABELS: Record<string, string> = {
  PAYMENT: "Оплата",
  CONTRACT: "Договор",
  MOVE_IN: "Заселение",
  MOVE_OUT: "Выселение",
  MAINTENANCE: "Обслуживание",
  UTILITIES: "Коммуналка",
  ACCOUNT: "Аккаунт",
  LISTING: "Объявление",
  COLLABORATOR: "Коллаборант",
  COMPLAINT: "Жалоба",
  FRAUD: "Мошенничество",
  COMPENSATION: "Компенсация",
  GUARANTEE: "Гарантия",
  INSURANCE: "Страхование",
  ACCEPTANCE_ACT: "Акт приёма",
  OTHER: "Прочее",
};

export const CHANNEL_LABELS: Record<string, string> = {
  AI_CHAT: "AI-чат",
  EMAIL: "Email",
  WEB_FORM: "Веб-форма",
  PHONE: "Телефон",
  INTERNAL: "Внутренний",
  LK_CLAIM: "ЛК — претензия",
  INSURER_WEBHOOK: "Вебхук страховщика",
  SYSTEM: "Система",
};

export const TEAM_LABELS: Record<string, string> = {
  support: "Поддержка",
  legal: "Юристы",
  finance: "Финансы",
};

export const SORT_LABELS: Record<string, string> = {
  "-created_at": "Сначала новые",
  created_at: "Сначала старые",
  "-priority": "Приоритет ↓",
  priority: "Приоритет ↑",
  "-resolution_due_at": "Дедлайн решения ↓",
  resolution_due_at: "Дедлайн решения ↑",
};

/** Лейбл значения enum; «—» для пустого, само значение — если лейбл не найден. */
export function label(map: Record<string, string>, value: string | null | undefined): string {
  if (!value) return "—";
  return map[value] ?? value;
}

// Фиксированный TZ (РФ, см. NFR «все серверы в РФ») — детерминированный вывод в тестах.
const DATE_FORMAT = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Moscow",
});

/** Форматирует ISO-дату в `дд.мм.гггг, чч:мм` (МСК). Невалидную — возвращает как есть. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return DATE_FORMAT.format(date);
}

/** Короткий вид uuid для колонок (полного справочника имён пока нет — см. #45). */
export function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 8 ? id.slice(0, 8) : id;
}

// Дата без времени (период брони — date, не datetime).
const DATE_ONLY_FORMAT = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "Europe/Moscow",
});

/** Форматирует ISO-дату в `дд.мм.гггг` (МСК). Невалидную/пустую — «—»/как есть. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return DATE_ONLY_FORMAT.format(date);
}

/** Сумма в рублях (RU-разделители). `null/undefined` → «—». */
export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${new Intl.NumberFormat("ru-RU").format(value)} ₽`;
}

// --- Лейблы полей контекста заявителя (platform, #81/#73). В отличие от карт выше,
// домен задаётся rehome.one platform (провизорный контракт ADR-0006), а не нашим
// OpenAPI — значения не фиксированы, поэтому `label()` корректно фолбэчит на сырую
// строку при промахе (не теряем данные оператору).
export const USER_ROLE_LABELS: Record<string, string> = {
  tenant: "Наниматель",
  landlord: "Наймодатель",
  operator: "Оператор",
  admin: "Администратор",
};

export const PREMISES_KIND_LABELS: Record<string, string> = {
  apartment: "Квартира",
  room: "Комната",
  house: "Дом",
  studio: "Студия",
};

export const BOOKING_STATUS_LABELS: Record<string, string> = {
  draft: "Черновик",
  pending: "Ожидает",
  active: "Активна",
  completed: "Завершена",
  cancelled: "Отменена",
};

export const COLLABORATOR_CATEGORY_LABELS: Record<string, string> = {
  cleaning: "Клининг",
  insurance: "Страхование",
  bank: "Банк",
  repair: "Ремонт",
  legal: "Юр. услуги",
};

export const AUTHOR_TYPE_LABELS: Record<string, string> = {
  requester: "Заявитель",
  operator: "Оператор",
  system: "Система",
  ai: "AI-ассистент",
};

export const HISTORY_ACTION_LABELS: Record<string, string> = {
  created: "Создана",
  status_changed: "Смена статуса",
  reassigned: "Переназначение",
  priority_changed: "Смена приоритета",
  type_changed: "Смена типа",
  team_changed: "Смена команды",
  tags_updated: "Обновление меток",
  message_added: "Добавлено сообщение",
  rated: "Оценка",
};

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return "∅";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function describeValues(value: Record<string, unknown> | null | undefined): string {
  if (!value) return "";
  return Object.entries(value)
    .map(([key, val]) => `${key}: ${formatScalar(val)}`)
    .join(", ");
}

/**
 * Человекочитаемый diff строки журнала. Обрабатывает `created` (from=null → «→ …»),
 * произвольные ключи `{"<поле>": <значение>}` и служебные объекты (`message_added`).
 */
export function formatHistoryDiff(
  from: Record<string, unknown> | null | undefined,
  to: Record<string, unknown> | null | undefined,
): string {
  const before = describeValues(from);
  const after = describeValues(to);
  if (!before && !after) return "";
  if (!before) return `→ ${after}`;
  if (!after) return `${before} →`;
  return `${before} → ${after}`;
}
