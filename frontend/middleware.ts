/**
 * Guard защищённых маршрутов. Неавторизованный запрос → редирект на страницу
 * входа (`pages.signIn`), далее на Keycloak. Использует edge-совместимый
 * `authConfig` (без провайдеров/секретов), решение принимает `authorized`.
 */

import NextAuth from "next-auth";

import { authConfig } from "@/auth.config";

const { auth } = NextAuth(authConfig);

export default auth;

export const config = {
  // Защищаем всё, кроме служебных путей Auth.js, страницы входа и статики.
  matcher: ["/((?!api/auth|login|_next/static|_next/image|favicon.ico).*)"],
};
