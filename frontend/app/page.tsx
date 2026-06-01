import Link from "next/link";

import { OperatorHeader } from "@/app/components/OperatorHeader";

export default function Home() {
  // Маршрут защищён middleware — сюда попадает только аутентифицированный оператор.
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 p-8">
      <OperatorHeader />
      <section className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold">Рабочее место оператора</h1>
        <p className="text-gray-600">Вход через Keycloak (SSO) подключён.</p>
        <Link
          href="/tickets"
          className="w-fit rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700"
        >
          Перейти к заявкам
        </Link>
      </section>
    </main>
  );
}
