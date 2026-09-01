# Стратегия тестирования MSSQL-primary / Babelfish-shadow

## Цель

Тесты должны доказать три независимых свойства:

1. переписанный SQL не изменил ожидаемое поведение MSSQL;
2. Babelfish возвращает семантически эквивалентный результат на одинаковых данных;
3. shadow-контур не может повредить primary response при ошибке или деградации Babelfish.

Mock-only suite доказывает wiring, но не совместимость SQL. Для финального `COMPATIBLE` нужен integration test против реальных движков и точной версии Babelfish.

## Пирамида тестов

### 1. Unit: query selection и comparator

Покрой:

- выбор common SQL или пары `primary_sql/shadow_sql` по query ID;
- передачу одинаковых typed parameters;
- нормализацию колонок и значений;
- order-sensitive compare при `ORDER BY` и multiset compare без него;
- различие `NULL`, пустой строки и отсутствующего поля;
- Unicode без lossy conversion;
- decimal precision/scale;
- datetime precision/timezone;
- безопасную diff summary без credentials/PII.

### 2. Unit/component: failure isolation

Стабами соединений докажи:

- MSSQL success + Babelfish exception → вызывающий код получает исходный MSSQL result;
- MSSQL success + Babelfish timeout → тот же MSSQL result, timeout зарегистрирован;
- MSSQL failure → сохраняется исходная MSSQL error semantics; shadow не маскирует её;
- shadow flag off → Babelfish executor/connection не вызывается;
- shadow flag on + allowlist/sampling hit → вызываются и MSSQL, и Babelfish, а возвращается MSSQL result;
- shadow flag on никогда не превращается в target switch и не пропускает MSSQL;
- sampling miss/circuit open → primary выполняется штатно;
- side-effecting query → `DOCUMENT_ONLY: SIDE_EFFECTING`, без rewrite и вызова Babelfish.

Сравнивай не только `equals`, но и идентичность типа/DTO там, где это часть публичного контракта.

### 3. Integration: query parity на двух движках

Для каждого критичного query ID либо репрезентативной группы:

1. Подними или подключи тестовые MSSQL и Babelfish точной целевой версии.
2. Примени эквивалентную схему.
3. Загрузи один детерминированный fixture dataset в обе БД.
4. Проверь checksum/count ключевых fixture-таблиц до теста.
5. Выполни запрос с одинаковыми typed parameters.
6. Нормализуй только заранее разрешённые различия.
7. Сравни schema, row count и значения.
8. Выведи query ID, diff class и небольшой безопасный diff при падении.

Не используй два несинхронных production snapshot как строгий parity fixture. Такой тест измеряет одновременно SQL и data drift и не позволяет локализовать причину.

## Обязательные наборы данных

Добавь случаи, актуальные запросу:

- пустой результат;
- одна и несколько строк;
- `NULL` и пустые строки;
- кириллица/Unicode и длинные строки;
- граничные decimal/datetime значения;
- дубликаты;
- ветки фильтрации и join без соответствующей строки;
- одинаковые sort keys, если порядок важен;
- параметры с неявными преобразованиями типов.

Для найденного Compass `Review Semantics` создай отдельный targeted case, воспроизводящий именно спорную конструкцию.

## Endpoint/service parity

Если несколько SQL-запросов собираются в один DTO/HTTP response:

- вызови production service/endpoint через MSSQL primary;
- дождись или синхронно получи результат shadow-comparator в тестовом режиме;
- сравни публичную форму ответа и значимые значения;
- исключай только заведомо недетерминированные поля по явному списку причин;
- отдельно проверь, что реальный клиентский ответ взят из MSSQL.

Snapshot допустим как дополнение. Основные критичные поля и коллекции сравнивай структурно, чтобы изменение snapshot не скрыло регрессию.

## Тесты переписывания SQL

Для каждого `before → after`:

- сохрани query ID;
- добавь regression case на поведение, ради которого существовала исходная конструкция;
- выполни новый вариант на MSSQL и Babelfish;
- проверь не только строки, но типы колонок, precision/scale и ordering;
- повторно прогони Compass на SQL, извлечённом из фактического кода.

Если используются разные dialect variants, один параметризованный contract test обязан прогонять оба варианта и сравнивать результат.

Этот раздел применяется только к `READ_ONLY`. Для side-effecting SQL код и тесты не добавляются: в отчёте формируется только предлагаемый будущий test plan без выполнения на Babelfish.

## CI и локальный запуск

Предпочитай существующие testcontainers/docker-compose/CI services проекта. Не добавляй тяжёлую инфраструктуру, если проект уже имеет согласованный способ integration-тестов.

Разделяй suites маркерами проекта, например `unit`, `db-integration`, `babelfish-parity`. Если окружение недоступно, integration suite может быть явно skipped только с понятной причиной; skipped suite не позволяет выставить финальный `COMPATIBLE`.

Credentials бери из секретов CI или environment. Не сохраняй их в fixtures, test config и отчётах.

## Критерий готовности

Разработка завершена, когда:

- новый SQL проходит MSSQL regression;
- Compass для target version не содержит нерешённых блокеров;
- integration parity проходит на синхронных fixtures;
- failure-isolation и kill-switch тесты проходят;
- тесты запускаются одной задокументированной командой;
- непроверенные ветки и skipped tests перечислены в отчёте.
