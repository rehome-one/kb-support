import { auth, signOut } from "@/auth";
import { Brand } from "@/app/components/Brand";

export default async function Home() {
  // Маршрут защищён middleware — сюда попадает только аутентифицированный оператор.
  const session = await auth();
  const operator = session?.user?.email ?? session?.user?.name ?? "оператор";

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 p-8">
      <header className="flex items-center justify-between border-b pb-4">
        <Brand />
        <div className="flex items-center gap-3 text-sm">
          <span className="text-gray-500">{operator}</span>
          <form
            action={async () => {
              "use server";
              await signOut({ redirectTo: "/login" });
            }}
          >
            <button type="submit" className="text-gray-600 underline hover:text-gray-900">
              Выйти
            </button>
          </form>
        </div>
      </header>
      <section className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Рабочее место оператора</h1>
        <p className="text-gray-600">
          Вход через Keycloak (SSO) подключён. Экраны (список заявок, карточка, переписка, действия)
          подключаются в последующих задачах E2 (#44–#49).
        </p>
      </section>
    </main>
  );
}
