"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  assignTicket,
  closeTicket,
  escalateTicket,
  reopenTicket,
  resolveTicket,
  updateTicket,
  type AssignInput,
  type EscalateInput,
  type ReopenInput,
  type ResolveInput,
  type TicketUpdateInput,
} from "@/lib/api/client";
import { UnauthenticatedError } from "@/lib/api/transport";

import type { ActionResult } from "./types";

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
