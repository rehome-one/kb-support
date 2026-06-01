// Route-level Suspense fallback на время серверной загрузки карточки.
export default function Loading() {
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-6 p-8">
      <div className="h-6 w-40 animate-pulse rounded bg-gray-200" />
      <div className="h-40 animate-pulse rounded border border-gray-200 bg-gray-50" />
      <div className="h-24 animate-pulse rounded border border-gray-200 bg-gray-50" />
      <div className="h-32 animate-pulse rounded border border-gray-200 bg-gray-50" />
    </main>
  );
}
