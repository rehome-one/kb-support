import "@testing-library/jest-dom/vitest";

// Дефолтные env для тестов, читающих конфиг (readEnv). Не секреты — заглушки,
// только чтобы модули, читающие окружение, инициализировались в Vitest.
process.env.AUTH_SECRET ||= "test-auth-secret-not-for-prod";
process.env.AUTH_KEYCLOAK_ID ||= "kb-support-frontend";
process.env.AUTH_KEYCLOAK_SECRET ||= "test-client-secret";
process.env.AUTH_KEYCLOAK_ISSUER ||= "https://keycloak.local/realms/rehome";
// base = корень хоста (как .env.example и OpenAPI servers); префикс /api/v1 несут пути-хелперы.
process.env.KB_SUPPORT_API_BASE_URL ||= "https://kb-support.local";
