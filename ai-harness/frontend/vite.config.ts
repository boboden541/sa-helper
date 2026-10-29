import { defineConfig } from 'vite'

// штамп сборки: видно в подсказке логотипа — защита от устаревшего контейнера
import { execSync } from 'node:child_process'

// штамп сборки: реальный хэш HEAD (захардкоженный хэш устаревал)
let APP_BUILD = 'dev'
try {
  APP_BUILD = execSync('git rev-parse --short HEAD').toString().trim()
} catch { /* вне git — dev */ }
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  define: { __APP_BUILD__: JSON.stringify(APP_BUILD) },
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:8000' },
  },
  preview: {
    port: 4173,
    proxy: { '/api': 'http://localhost:8000' },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
})
