"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  assignTicket,
  closeTicket,
  createMessage,
  decideTicket,
  escalateTicket,
  renderCannedResponse,
  reopenTicket,
  resolveTicket,
  transitionCaseState,
  updateTicket,
  type AssignInput,
  type CaseStateTransitionInput,
  type DecisionInput,
  type EscalateInput,
  type MessageCreateInput,
  type ReopenInput,
  type ResolveInput,
  type TicketUpdateInput,
} from "@/lib/api/client";
import { UnauthenticatedError } from "@/lib/api/transport";

import type { ActionResult, RenderResult } from "./types";

// Общая обёртка: выполнить мутацию серверно (Bearer из сессии — токен не уходит в
// браузер), при успехе ревалидировать карточку, ошибку отдать как {status,title}.
async function run(id: string, op: () => Promise<unknown>): Promise<ActionResult> {
  try {
    await op();
    revalidatePath(`/tickets/${id}`);
    return { ok: true };
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return { ok: false, status: 401, title: "Сессия истекла — войдите снова" };
    }
    if (error instanceof ApiError) {
      return { ok: false, status: error.status, title: error.title };
    }
    return { ok: false, status: 0, title: "Не удалось выполнить действие" };
  }
}

export async function patchTicketAction(
  id: string,
  patch: TicketUpdateInput,
): Promise<ActionResult> {
  return run(id, () => updateTicket(id, patch));
}

export async function assignAction(id: string, input: AssignInput): Promise<ActionResult> {
  return run(id, () => assignTicket(id, input));
}

export async function escalateAction(id: string, input: EscalateInput): Promise<ActionResult> {
  return run(id, () => escalateTicket(id, input));
}

export async function resolveAction(id: string, input: ResolveInput): Promise<ActionResult> {
  return run(id, () => resolveTicket(id, input));
}

// close не принимает тело (контракт #60); reopen на бэкенде НЕ требует оператора —
// видимость кнопки на операторском экране не подменяет бэкенд-RBAC.
export async function closeAction(id: string): Promise<ActionResult> {
  return run(id, () => closeTicket(id));
}

export async function reopenAction(id: string, input: ReopenInput): Promise<ActionResult> {
  return run(id, () => reopenTicket(id, input));
}

// Добавление сообщения/внутренней заметки. is_internal=true бэкенд примет только от
// оператора (иначе 403, NFR-1.3) — фронт лишь передаёт флаг. Idempotency-Key — в хелпере.
export async function createMessageAction(
  id: string,
  input: MessageCreateInput,
): Promise<ActionResult> {
  return run(id, () => createMessage(id, input));
}

// Претензионные мутации (E10, #201). Бэкенд решает права (decision — legal/finance;
// case-state — оператор): видимость форм на фронте не подменяет RBAC. Любой статус
// ошибки (403/404/409/422) пересекает границу только как {status,title} (ФЗ-152).
export async function decideAction(id: string, input: DecisionInput): Promise<ActionResult> {
  return run(id, () => decideTicket(id, input));
}

export async function transitionCaseStateAction(
  id: string,
  input: CaseStateTransitionInput,
): Promise<ActionResult> {
  return run(id, () => transitionCaseState(id, input));
}

// Рендер шаблона для заявки (#131): подстановка переменных на сервере (ПДн — на сервере),
// результат (готовый текст + slug статьи) возвращается оператору для вставки в композер.
// Ошибка пересекает границу только как {status,title} (detail/problem остаётся на сервере).
export async function renderCannedAction(
  ticketId: string,
  cannedId: string,
): Promise<RenderResult> {
  try {
    const res = await renderCannedResponse(cannedId, { ticket_id: ticketId });
    const data = res.data;
    if (!data) {
      return { ok: false, status: 0, title: "Не удалось отрендерить шаблон" };
    }
    return {
      ok: true,
      body: data.rendered_body,
      linkedArticleSlug: data.linked_article_slug ?? null,
    };
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return { ok: false, status: 401, title: "Сессия истекла — войдите снова" };
    }
    if (error instanceof ApiError) {
      return { ok: false, status: error.status, title: error.title };
    }
    return { ok: false, status: 0, title: "Не удалось отрендерить шаблон" };
  }
}
