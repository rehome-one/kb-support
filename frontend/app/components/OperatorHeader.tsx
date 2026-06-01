import { auth, signOut } from "@/auth";

import { Brand } from "./Brand";

/**
 * Шапка рабочего места оператора: бренд, текущий оператор, выход. Серверный
 * компонент — берёт сессию из Auth.js; форма «Выйти» вызывает серверный signOut.
 */
export async function OperatorHeader() {
  const session = await auth();
  const operator = session?.user?.email ?? session?.user?.name ?? "оператор";

  return (
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
  );
}
