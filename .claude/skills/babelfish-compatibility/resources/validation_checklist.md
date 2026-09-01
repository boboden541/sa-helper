# Чек-лист проверки Babelfish compatibility

## Hard Gates

- [ ] Прочитаны применимые `AGENTS.md` и миграционный контекст проекта.
- [ ] Область проверки и полный call path названы явно.
- [ ] Зафиксирована точная целевая версия Babelfish; `latest` не используется как неявное допущение.
- [ ] Все SQL batches имеют `query_id` и источник `файл:строка` или DB-объект.
- [ ] Каждый batch до любых правок классифицирован как `READ_ONLY` или `SIDE_EFFECTING`; смешанные/неясные batches считаются `SIDE_EFFECTING`.
- [ ] Учтены динамический SQL, процедуры/functions/views, транзакции и session settings.
- [ ] Официальный Compass реально запущен либо результат помечен `INCONCLUSIVE`; статический вердикт не придуман.
- [ ] Все `Not Supported`, `Review Semantics` и `Review Performance` разобраны по query ID.
- [ ] Только несовместимый `READ_ONLY` SQL минимально переписан либо оставлен с доказанным блокером; business semantics не изменена молча.
- [ ] После переписывания SQL повторно извлечён из фактического кода и проверен Compass.
- [ ] Compass-проверка не выдана за runtime parity.
- [ ] В режиме DEVELOPMENT MSSQL остаётся единственным источником клиентского результата.
- [ ] Shadow-флаг не переключает target: при включённом shadow тест подтверждает оба вызова, MSSQL и Babelfish.
- [ ] В режиме DEVELOPMENT Babelfish error/timeout/mismatch не меняет primary outcome.
- [ ] В режиме DEVELOPMENT shadow по умолчанию ограничен доказуемо read-only запросами.
- [ ] Side-effecting SQL не переписан и не выполнен на Babelfish; все детали зафиксированы в отчёте со статусом `DOCUMENT_ONLY: SIDE_EFFECTING`.
- [ ] В режиме DEVELOPMENT у shadow отдельны timeout, pool/concurrency limit, sampling и kill switch.
- [ ] В оба контура передаются одинаковые typed parameters; варианты SQL сопоставлены явно.
- [ ] Результаты проверены на колонки/типы, NULL, Unicode, числа, даты, строки и порядок.
- [ ] Различаются SQL incompatibility и data drift.
- [ ] Логи не содержат credentials и необработанные чувствительные параметры.
- [ ] Вердикт соответствует фактическим доказательствам и содержит границы проверки.

## Runtime и rollback

- [ ] Babelfish schema/data для scope существуют или это явно отмечено как блокер.
- [ ] Выполнен хотя бы один репрезентативный MSSQL/Babelfish smoke case.
- [ ] Проверены error behavior и timeout Babelfish.
- [ ] Проверено отключение shadow-флага: поведение совпадает с исходным MSSQL-only путём.
- [ ] Для DEVELOPMENT перечислены изменённые файлы и причина каждого изменения.
- [ ] Есть MSSQL regression test и реальный MSSQL/Babelfish integration parity test либо итог `INCONCLUSIVE`.
- [ ] Проверены Babelfish exception/timeout, kill switch и отсутствие влияния на MSSQL result.
- [ ] Для каждого `Review Semantics` есть targeted test case.
- [ ] Запущены доступные lint/tests/smoke checks.

## Отчёт

- [ ] Указаны версия Compass, целевая версия Babelfish и артефакты запуска.
- [ ] Есть таблица query inventory и findings.
- [ ] Есть таблица runtime parity.
- [ ] Есть описание shadow architecture и защит.
- [ ] Есть таблица SQL rewrites и матрица автоматических тестов.
- [ ] Есть остаточные риски, rollback и следующий безопасный шаг.
