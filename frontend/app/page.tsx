import { Brand } from "@/app/components/Brand";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 p-8">
      <header className="flex items-center justify-between border-b pb-4">
        <Brand />
        <span className="text-sm text-gray-500">E2 — скелет</span>
      </header>
      <section className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Рабочее место оператора</h1>
        <p className="text-gray-600">
          Скелет фронтенда kb-support. Экраны (список заявок, карточка, переписка, действия)
          подключаются в последующих задачах E2 (#43–#49).
        </p>
      </section>
    </main>
  );
}
