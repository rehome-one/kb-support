import Link from "next/link";
import { notFound } from "next/navigation";

import { OperatorHeader } from "@/app/components/OperatorHeader";
import {
  ApiError,
  getRequesterContext,
  getSuggestedArticles,
  getTicket,
  getTicketHistory,
  listCannedResponses,
  listMessages,
} from "@/lib/api/client";

import {
  assignAction,
  closeAction,
  createMessageAction,
  escalateAction,
  patchTicketAction,
  renderCannedAction,
  reopenAction,
  resolveAction,
} from "./actions";
import { HistoryTimeline } from "./HistoryTimeline";
import { MessageComposer } from "./MessageComposer";
import { MessageThread } from "./MessageThread";
import { RequesterContext } from "./RequesterContext";
import { SuggestedArticles } from "./SuggestedArticles";
import { TicketActions } from "./TicketActions";
import { TicketDetail } from "./TicketDetail";
import type {
  CannedSummary,
  RequesterContextResult,
  SuggestedArticlesResult,
  TicketHistoryEntry,
  TicketMessage,
} from "./types";

type MessagesResult = { items: TicketMessage[] } | { error: string };
type HistoryResult = { items: TicketHistoryEntry[] } | { forbidden: true } | { error: string };

// Переписку и историю грузим с graceful degradation: ошибка одной секции не
// роняет страницу. Токен остаётся на сервере (вызовы server-only клиента).
async function loadMessages(id: string): Promise<MessagesResult> {
  try {
    const res = await listMessages(id);
    return { items: res.data ?? [] };
  } catch {
    return { error: "Не удалось загрузить переписку" };
  }
}

async function loadHistory(id: string): Promise<HistoryResult> {
  try {
    const res = await getTicketHistory(id);
    return { items: res.data ?? [] };
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      return { forbidden: true };
    }
    return { error: "Не удалось загрузить историю" };
  }
}

async function loadRequesterContext(id: string): Promise<RequesterContextResult> {
  try {
    const res = await getRequesterContext(id);
    // 200 контракта всегда несёт data; на всякий случай — деградируем мягко.
    return res.data ? { context: res.data } : { error: "Контекст заявителя недоступен" };
  } catch (error) {
    // 403 (контекст — только операторам, #81) — отдельная нейтральная ветка, как история.
    if (error instanceof ApiError && error.status === 403) {
      return { forbidden: true };
    }
    return { error: "Не удалось загрузить контекст заявителя" };
  }
}

// Шаблоны ответов для панели композера (#131). Ошибка не критична — панель просто
// не показывается (пустой список). Токен остаётся на сервере (server-only клиент).
async function loadTemplates(): Promise<CannedSummary[]> {
  try {
    const res = await listCannedResponses();
    return res.data ?? [];
  } catch {
    return [];
  }
}

// Предложенные статьи БЗ (#131, FR-5.4). 200 несёт degraded-флаг; сбой → мягкая ошибка.
async function loadSuggestedArticles(id: string): Promise<SuggestedArticlesResult> {
  try {
    const res = await getSuggestedArticles(id);
    return res.data
      ? { articles: res.data.articles, degraded: res.data.degraded }
      : { error: "Похожие статьи недоступны" };
  } catch {
    return { error: "Не удалось загрузить похожие статьи" };
  }
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export default async function TicketCardPage({ params }: { params: { id: string } }) {
  const { id } = params;

  let ticket;
  let loadFailed = false;
  try {
    const res = await getTicket(id);
    ticket = res.data;
  } catch (error) {
    // 404 (в т.ч. anti-enumeration для чужой заявки) — стандартная not-found.
    if (error instanceof ApiError && error.status === 404) notFound();
    // Иная ошибка (5xx/сеть/недокументированная) — не «не найдено», а сбой загрузки.
    loadFailed = true;
  }

  if (loadFailed) {
    return (
      <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-6 p-8">
        <OperatorHeader />
        <Link href="/tickets" className="w-fit text-sm text-gray-600 underline hover:text-gray-900">
          ← К списку заявок
        </Link>
        <p role="alert" className="text-sm text-red-600">
          Не удалось загрузить заявку. Попробуйте позже.
        </p>
      </main>
    );
  }
  if (!ticket) notFound();

  const [messages, history, requesterContext, templates, suggestedArticles] = await Promise.all([
    loadMessages(id),
    loadHistory(id),
    loadRequesterContext(id),
    loadTemplates(),
    loadSuggestedArticles(id),
  ]);

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-6 p-8">
      <OperatorHeader />
      <Link href="/tickets" className="w-fit text-sm text-gray-600 underline hover:text-gray-900">
        ← К списку заявок
      </Link>

      <TicketDetail ticket={ticket} />
      <TicketActions
        ticket={ticket}
        patchAction={patchTicketAction}
        assignAction={assignAction}
        escalateAction={escalateAction}
        resolveAction={resolveAction}
        closeAction={closeAction}
        reopenAction={reopenAction}
      />
      <RequesterContext ticket={ticket} result={requesterContext} />

      <Section title="Переписка">
        {"error" in messages ? (
          <p role="alert" className="text-sm text-red-600">
            {messages.error}
          </p>
        ) : (
          <MessageThread messages={messages.items} />
        )}
        <MessageComposer
          ticketId={ticket.id}
          createMessageAction={createMessageAction}
          templates={templates}
          renderTemplateAction={renderCannedAction}
        />
      </Section>

      <Section title="Похожие статьи">
        <SuggestedArticles result={suggestedArticles} />
      </Section>

      <Section title="История">
        {"forbidden" in history ? (
          <p className="text-sm text-gray-500">История доступна только операторам.</p>
        ) : "error" in history ? (
          <p role="alert" className="text-sm text-red-600">
            {history.error}
          </p>
        ) : (
          <HistoryTimeline entries={history.items} />
        )}
      </Section>
    </main>
  );
}
