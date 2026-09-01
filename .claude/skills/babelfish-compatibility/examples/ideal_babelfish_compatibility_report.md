# Babelfish compatibility report: <scope>

> **Вердикт:** COMPATIBLE | COMPATIBLE WITH CHANGES | INCOMPATIBLE | INCONCLUSIVE  
> **Дата / commit:** <UTC date> / <sha>  
> **MSSQL:** <version, database>  
> **Babelfish target:** <version> / PostgreSQL <version>  
> **Режим:** development | review  
> **Граница проверки:** <что вошло и что не вошло>

## 1. Резюме

<Что проверено, какие блокеры или ограничения найдены, можно ли включать shadow для заявленного scope.>

## 2. Контекст и call path

```text
<entry point>
└─ <service>
   ├─ <repository / DAO>
   └─ <query executor>
```

Не-DB зависимости: <cache/search/HTTP/queue или «нет»>.

## 3. SQL inventory

| Query ID | Источник | Операция | DB-объекты | Класс исполнения | Ветки/динамика |
|---|---|---|---|---|---|
| Q-001 | `src/Repo.php:42` | SELECT | `dbo.item_view` | READ_ONLY | `<условие>` |
| Q-002 | `src/Repo.php:78` | UPDATE | `dbo.item` | SIDE_EFFECTING | `<условие>` |

**Покрытие:** <N>/<N> найденных batches.  
**Непроверенные ветки:** <список или «нет»>.

## 4. Babelfish Compass

| Поле | Значение |
|---|---|
| Compass version | `<version>` |
| Target Babelfish | `<version>` |
| Input SQL | `<path/hash>` |
| Report | `<path>` |
| Supported | `<N>` |
| Not Supported | `<N>` |
| Review Semantics | `<N>` |
| Review Performance | `<N>` |
| Ignored / Manual review | `<N>` |

### Findings

| ID | Query ID | Classification | Feature | SQL до | SQL после / решение | Статус |
|---|---|---|---|---|---|---|
| BF-001 | Q-001 | Review Semantics | `<feature>` | `<fragment>` | `<rewrite + paired test>` | Open/Resolved |

### Side-effecting SQL — document only

| Query ID | Операция и объекты | Compass findings | Транзакционные/семантические риски | Предлагаемая будущая доработка | Почему не запускался |
|---|---|---|---|---|---|
| Q-002 | `UPDATE dbo.item` | `<...>` | `<locks/triggers/IDs/...>` | `<proposal, код не изменён>` | `DOCUMENT_ONLY: SIDE_EFFECTING` |

## 5. Runtime parity

| Case | Query ID | Параметры (без секретов) | MSSQL | Babelfish shadow | Comparison | Latency MSSQL/BF |
|---|---|---|---|---|---|---|
| RT-001 | Q-001 | `<safe summary>` | OK, N rows | OK, N rows | MATCH | `<ms>/<ms>` |

Проверено отдельно:

- NULL / empty values: <результат>;
- Unicode: <результат>;
- decimal precision/scale: <результат>;
- dates/timezone: <результат>;
- ordering: <результат>;
- error behavior: <результат>;
- data snapshot/replication lag: <результат>.

## 6. Shadow architecture

```text
<request>
├─ MSSQL primary ──> client result
└─ Babelfish shadow ──> comparator ──> telemetry
```

| Защита | Реализация / значение |
|---|---|
| Scope / allowlist | `<...>` |
| Sampling | `<...>` |
| Shadow timeout | `<...>` |
| Pool / concurrency limit | `<...>` |
| Circuit breaker | `<...>` |
| Kill switch | `<...>` |
| Sensitive-data policy | `<...>` |
| Write policy | `DOCUMENT_ONLY: SIDE_EFFECTING` |

MSSQL result остаётся неизменным: <доказательство тестом>.

## 7. Расхождения и классификация

| Diff ID | Query ID | Класс | Наблюдение | Причина | Влияние | Действие |
|---|---|---|---|---|---|---|
| D-001 | Q-001 | DATA_DRIFT | `<...>` | `<...>` | `<...>` | `<...>` |

## 8. Изменения и автоматические тесты

| Файл | Изменение | Причина |
|---|---|---|
| `<path>` | `<...>` | `<...>` |

Выполнено:

- `<lint/test/smoke command>` — <result>;
- Compass rerun — <result>;
- shadow-off rollback test — <result>.

| Test | Уровень | Query IDs | Что доказывает | Результат |
|---|---|---|---|---|
| `<test name>` | unit/integration/endpoint | Q-001 | MSSQL regression / parity / isolation | PASS/FAIL/SKIP |

Команда полного прогона:

```text
<command>
```

## 9. Риски, rollback и следующий шаг

Остаточные риски:

- <risk>.

Rollback / kill switch:

```text
<точное безопасное действие без credentials>
```

Следующий безопасный шаг: <одно конкретное действие>.
