import type { SuggestedArticlesResult } from "./types";

// Презентационный (server-совместимый) блок предложенных статей БЗ (#131, FR-5.4).
// degraded/ошибка/пусто — нейтральные сообщения; статьи — ссылки (url из kb-wiki).
export function SuggestedArticles({ result }: { result: SuggestedArticlesResult }) {
  if ("error" in result) {
    return <p className="text-sm text-gray-500">{result.error}</p>;
  }
  if (result.degraded) {
    return <p className="text-sm text-gray-500">Похожие статьи сейчас недоступны.</p>;
  }
  if (result.articles.length === 0) {
    return <p className="text-sm text-gray-500">Похожих статей не найдено.</p>;
  }
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {result.articles.map((article) => (
        <li key={article.slug}>
          {article.url ? (
            <a
              href={article.url}
              target="_blank"
              rel="noreferrer"
              className="text-blue-700 underline hover:text-blue-900"
            >
              {article.title}
            </a>
          ) : (
            <span>{article.title}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
