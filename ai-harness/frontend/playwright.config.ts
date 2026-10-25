import { defineConfig } from '@playwright/test'

// По умолчанию — DOCKER-стек :8088 (то, что открывает владелец).
// Для отладки на preview: PLAYWRIGHT_BASE_URL=http://localhost:4173 USE_PREVIEW=1 npx playwright test
const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:8088'
export default defineConfig({
  testDir: 'e2e',
  timeout: 30000,
  use: { baseURL: BASE },
  webServer: process.env.USE_PREVIEW
    ? { command: 'npm run preview', port: 4173, reuseExistingServer: true, timeout: 30000 }
    : undefined,
})
