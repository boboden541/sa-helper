// ESLint flat-config: разумный минимум — рекомендуемые правила TS/JS плюс
// базовые react-hooks (rules-of-hooks + exhaustive-deps), без стилистики.
// Компиляторные линты react-hooks v7 (set-state-in-effect / immutability /
// refs / purity) выключены сознательно: они воюют с легаси-паттернами
// приложения (hash-роутинг через window.location, рисование temp-ребра
// по ref в FlowTab с принудительным tick) — их правка меняет поведение.
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'test-results', 'playwright-report'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
)
