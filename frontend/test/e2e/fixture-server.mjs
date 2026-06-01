/**
 * Детерминированный мок-бэкенд kb-support для E2E-smoke (#49).
 *
 * Зачем свой http-сервер, а не Prism: в `docs/openapi.yaml` всего несколько
 * `example`, dynamic-mock выдаёт случайные данные и навигация «открыть заявку X»
 * флакает. Здесь — фиксированные id и формы из контракта, плюс in-memory
 * персистенция отправленных сообщений (ассерт идёт после revalidatePath →
 * повторного GET, поэтому одного эха мало). Это тестовый артефакт фронта, не код
 * чужого сервиса: общение строго по HTTP (арх-константа не нарушается).
 *
 * Чистый Node ESM без зависимостей — запускается `node`'ом напрямую как
 * webServer в playwright.config (Playwright не транспилирует команды).
 */

import { createServer } from "node:http";

import {
  HISTORY,
  INITIAL_MESSAGES,
  OPERATOR_ID,
  TICKET,
  TICKET_ID,
  TICKET_SUMMARY,
} from "./fixtures.data.mjs";

const PORT = Number(process.env.PORT ?? 3101);
const BASE = "/api/v1/support/tickets";

// In-memory переписка — копия, чтобы повторный прогон стартовал с чистого листа.
const messages = INITIAL_MESSAGES.map((m) => ({ ...m }));
let messageSeq = 0;

const json = (res, status, payload) => {
  const data = JSON.stringify(payload);
  res.writeHead(status, {
    "Content-Type": status >= 400 ? "application/problem+json" : "application/json",
  });
  res.end(data);
};

const envelope = (data, extra = {}) => ({
  data,
  request_id: "e2e-00000000-0000-4000-8000-000000000000",
  ...extra,
});

const problem = (res, status, title) =>
  json(res, status, {
    type: `https://api.rehome.one/errors/${status}`,
    title,
    status,
  });

const readBody = (req) =>
  new Promise((resolve) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        resolve({});
      }
    });
  });

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://localhost:${PORT}`);
  const path = url.pathname;
  const method = req.method ?? "GET";

  // Health-пинг — Playwright webServer ждёт ответа на корне.
  if (path === "/" && method === "GET") {
    return json(res, 200, { status: "ok" });
  }

  // GET /tickets — список (одна страница, без курсора).
  if (path === BASE && method === "GET") {
    return json(
      res,
      200,
      envelope([TICKET_SUMMARY], { pagination: { next_cursor: null, has_more: false } }),
    );
  }

  const ticketPath = `${BASE}/${TICKET_ID}`;

  // GET /tickets/{id}
  if (path === ticketPath && method === "GET") {
    return json(res, 200, envelope(TICKET));
  }

  // GET /tickets/{id}/messages — текущая переписка (хронологически).
  if (path === `${ticketPath}/messages` && method === "GET") {
    return json(res, 200, envelope(messages));
  }

  // POST /tickets/{id}/messages — добавить ответ оператора и персистить.
  if (path === `${ticketPath}/messages` && method === "POST") {
    const body = await readBody(req);
    messageSeq += 1;
    const created = {
      id: `cccccccc-cccc-4ccc-8ccc-${String(messageSeq).padStart(12, "0")}`,
      ticket_id: TICKET_ID,
      author_id: OPERATOR_ID,
      author_type: "operator",
      body: String(body.body ?? ""),
      is_internal: Boolean(body.is_internal),
      created_at: "2026-06-01T10:00:00Z",
    };
    messages.push(created);
    return json(res, 201, envelope(created));
  }

  // GET /tickets/{id}/history — журнал (без пагинации).
  if (path === `${ticketPath}/history` && method === "GET") {
    return json(res, 200, envelope(HISTORY));
  }

  return problem(res, 404, "Not found");
});

server.listen(PORT, () => {
  // eslint-disable-next-line no-console -- единственный канал готовности для webServer
  console.log(`[e2e-fixture] listening on http://localhost:${PORT}`);
});
