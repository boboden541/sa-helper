# Контракт теневого выполнения MSSQL + Babelfish

## Цель

Shadow-контур проверяет Babelfish на реальном SQL и параметрах, пока MSSQL остаётся единственным источником бизнес-результата.

```text
                         +--> MSSQL primary --> return to caller
application query layer -|
                         `--> Babelfish shadow --> compare/telemetry only
```

Это dual execution для чтения, а не переключение target и не dual write. Не реализуй feature flag вида `target=mssql|babelfish`: MSSQL вызывается всегда, а флаг только разрешает или запрещает дополнительный Babelfish shadow.

## Где внедрять

Предпочтительный порядок точек внедрения:

1. общий parameterized query executor;
2. connection provider / DAO boundary;
3. repository decorator;
4. узкий service-level wrapper для временного POC.

Выбирай самую узкую централизованную точку, которая покрывает весь заявленный SQL-набор и не захватывает посторонний трафик. Не используй глобальный mutable target, особенно в long-lived workers и параллельных запросах.

## Контракт исполнения

Логическая операция должна иметь:

```text
query_id
primary_sql
shadow_sql (по умолчанию совпадает с primary_sql)
typed_parameters
comparison_policy
shadow_policy
correlation_id
```

Порядок:

1. Проверь kill switch, allowlist query IDs и sampling.
2. Выполни MSSQL primary по существующему production-пути.
3. Независимо выполни Babelfish shadow, если запрос read-only и попал в выборку.
4. Перехвати любую shadow-ошибку на границе инфраструктуры.
5. Нормализуй и сравни результаты.
6. Верни вызывающему коду исходный MSSQL result без подмены.

При включённом shadow и попадании в allowlist/sampling тест должен доказать два вызова — MSSQL и Babelfish — в рамках одной логической операции. Запрещён сценарий, где включение shadow-флага перестаёт вызывать MSSQL.

Параллельный запуск допустим, если драйверы, connection pools и request lifecycle это безопасно поддерживают. Последовательный запуск также является shadow dual execution, но его latency нужно измерять. Асинхронный запуск должен гарантировать доставку и иметь ограниченный срок хранения параметров; fire-and-forget, который процесс может потерять, нельзя выдавать за полную проверку.

## Изоляция отказов

Обязательные механизмы:

- отдельный Babelfish connection pool;
- меньший shadow timeout, чем общий request timeout;
- ограничение concurrency/queue depth;
- sampling от 0 до 100%;
- allowlist endpoint/repository/query ID;
- feature flag и мгновенный kill switch;
- circuit breaker при серии ошибок;
- отсутствие retry storm: небольшой фиксированный предел повторов или ноль;
- shadow-исключения никогда не пробрасываются в primary call path.

Если runtime не позволяет завершить shadow до окончания запроса, используй очередь/worker или post-response hook с гарантированным lifecycle. Не удерживай пользовательский ответ бесконечно ради Babelfish.

## Безопасность SQL

### Read-only

Разрешены параметризованные `SELECT` и вызовы, для которых доказано отсутствие side effects. Учитывай, что процедура с именем `get*` всё равно может писать.

Классифицируй как `READ_ONLY` только когда одновременно выполнено всё:

- top-level операция — `SELECT`;
- нет `SELECT INTO`, DML, DDL и изменения session/server state;
- все вызываемые procedures/functions и dynamic SQL прослежены и доказуемо не пишут;
- batch не создаёт и не изменяет временные/постоянные объекты;
- нет внешних side effects.

Если хотя бы один пункт не доказан, используй `SIDE_EFFECTING` и document-only маршрут.

### Side-effecting SQL: только документирование

`INSERT`, `UPDATE`, `DELETE`, `MERGE`, DDL, процедуры с записью, sequence/identity и внешние side effects не переписываются и не исполняются на Babelfish этим навыком. Смешанный batch целиком считается side-effecting. Транзакция с `ROLLBACK` не превращает его в разрешённый shadow: sequence/identity, внешние вызовы, autonomous behavior и блокировки могут иметь эффект вне ожидаемого rollback.

Зафиксируй в compatibility report:

- query ID, полный источник и call path;
- операция и затронутые таблицы/процедуры;
- Compass classification и точные findings;
- транзакции, locks, triggers, generated IDs и внешние эффекты;
- почему runtime shadow не запускался;
- рекомендуемый rewrite/архитектурный вариант как предложение, но не изменение кода;
- отдельный план тестирования, синхронизации и rollback для будущей задачи.

Статус: `DOCUMENT_ONLY: SIDE_EFFECTING`. Даже явная просьба запустить такой shadow выходит за контракт навыка и требует отдельной задачи с отдельными правилами.

## Сравнение результатов

Сначала отдели четыре класса расхождений:

1. `EXECUTION_ERROR` — запрос не выполнился в Babelfish.
2. `SCHEMA_MISMATCH` — колонки, типы, precision/scale или nullability отличаются.
3. `VALUE_MISMATCH` — форма совпала, значения отличаются.
4. `DATA_DRIFT` — различие объясняется разными снимками/лагом репликации, а не SQL-семантикой.
5. `PERFORMANCE_REGRESSION` — результат совпал, но latency/plan выходит за порог.

Нормализация должна быть явной, а не скрывать ошибки. Допустимые правила задаются на query ID:

- порядок строк игнорируется только без `ORDER BY`;
- decimal сравнивается с сохранением заявленных precision/scale;
- datetime приводится к согласованному timezone/precision;
- Unicode сравнивается как Unicode, `?` не считается эквивалентом;
- `NULL`, пустая строка и отсутствующее поле не эквивалентны без доменного правила;
- большие результаты можно сравнивать по детерминированному hash + выборке, фиксируя ограничение метода.

## Телеметрия

Минимальная запись события:

```text
timestamp
query_id / query_fingerprint
correlation_id
primary_status, primary_duration_ms, primary_row_count
shadow_status, shadow_duration_ms, shadow_row_count
comparison_status
diff_summary
target_babelfish_version
```

Параметры редактируй или хешируй по data classification. SQL fingerprint предпочтительнее полного SQL в production-логах.

Метрики:

- shadow attempted/skipped/succeeded/failed;
- parity match/mismatch/data-drift;
- timeout/circuit-open;
- latency p50/p95/p99 и overhead primary request;
- backlog/queue depth для async режима.

## Критерии готовности к расширению

Расширяй allowlist только когда для текущего scope:

- Compass findings разобраны;
- runtime error rate и mismatch rate находятся в согласованных пределах;
- data drift измерим;
- shadow не ухудшает primary SLO;
- kill switch проверен;
- секреты и чувствительные данные не попадают в логи.
