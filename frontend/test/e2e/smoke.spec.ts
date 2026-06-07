/**
 * E2-8 (#49): сквозной smoke рабочего места оператора.
 * Сценарий: (вход мокнут storageState) → список заявок → открыть карточку →
 * отправить ответ → ответ виден в переписке.
 *
 * Доказывает интеграцию UI ↔ типизированный клиент ↔ HTTP-граница против
 * детерминированного мок-бэкенда. Реальный SSO/бэкенд — вне scope (#52).
 */

import { expect, test } from "@playwright/test";

import { TICKET_NUMBER, TICKET_SUBJECT } from "./fixtures.data.mjs";

test("оператор: список → карточка → ответ", async ({ page }) => {
  // 1. Список заявок: маршрут защищён middleware, проходим благодаря storageState.
  await page.goto("/support/tickets");
  await expect(page.getByRole("heading", { name: "Заявки" })).toBeVisible();

  const ticketLink = page.getByRole("link", { name: TICKET_NUMBER });
  await expect(ticketLink).toBeVisible();

  // 2. Открыть карточку.
  await ticketLink.click();
  await expect(page).toHaveURL(/\/support\/tickets\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: TICKET_SUBJECT })).toBeVisible();

  // Исходная переписка заявителя видна.
  await expect(page.getByText("Когда починят лифт?")).toBeVisible();

  // 3. Отправить ответ оператора.
  const reply = `E2E-ответ оператора ${Date.now()}`;
  await page.getByRole("textbox", { name: "Текст сообщения" }).fill(reply);
  await page.getByRole("button", { name: "Отправить ответ" }).click();

  // 4. Ответ персистнут фикстурой и подтянут после revalidatePath — виден в треде.
  await expect(page.getByText(reply)).toBeVisible();
});
