/**
 * Публичная поверхность API-клиента kb-support. Экраны (#45–#49) импортируют
 * только отсюда — низкоуровневый транспорт (`transport.ts`) наружу не торчит.
 */

export {
  ApiError,
  request,
  listTickets,
  getTicket,
  updateTicket,
  listMessages,
  createMessage,
  assignTicket,
  escalateTicket,
  resolveTicket,
  closeTicket,
  reopenTicket,
  rateTicket,
} from "@/lib/api/client";

export type {
  Problem,
  RequestOptions,
  TicketListResponse,
  TicketResponse,
  MessageListResponse,
  MessageResponse,
  ListTicketsQuery,
  ListMessagesQuery,
  TicketUpdateInput,
  MessageCreateInput,
  AssignInput,
  EscalateInput,
  ResolveInput,
  CloseInput,
  ReopenInput,
  RateInput,
} from "@/lib/api/client";

// Пробрасывается транспортом #43, когда серверная сессия без токена.
export { UnauthenticatedError } from "@/lib/api/transport";
