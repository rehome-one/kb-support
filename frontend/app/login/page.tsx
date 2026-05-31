import { signIn } from "@/auth";
import { Brand } from "@/app/components/Brand";

export default function LoginPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-6 p-8">
      <Brand />
      <h1 className="text-xl font-semibold">Вход в рабочее место</h1>
      <p className="text-center text-sm text-gray-600">
        Доступ к службе поддержки reHome — через единый вход (Keycloak).
      </p>
      <form
        action={async () => {
          "use server";
          await signIn("keycloak", { redirectTo: "/" });
        }}
      >
        <button
          type="submit"
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700"
        >
          Войти через Keycloak
        </button>
      </form>
    </main>
  );
}
