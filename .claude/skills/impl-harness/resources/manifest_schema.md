# Ресурс: канонический schema manifest.json

Единственный источник правды агента и UI (v2 §10). Файл: `FNR_N/harness/manifest.json`.
Запись **атомарная** (tmp + переименование), **один writer** — агент. Проверка после каждой
записи: `python3 harness/manifest_check.py --file <manifest>`.

## Верхний уровень

| Поле | Тип | Канон |
|---|---|---|
| `fnr_id` | str | `FNR_<N>` |
| `source_document` | str | имя файла СТ (например `system_requirements.md`) |
| `epic_branch` | str | `harness/FNR-<N>-<slug>` (slug — kebab-case) |
| `workspace` | str | путь корня воркспейса |
| `status` | enum | `PLANNED` → `AWAITING_APPROVAL` → `APPROVED` → `IN_PROGRESS` → `COMPLETED`; `ABORTED` |
| `created_at` / `updated_at` | ISO 8601 | UTC |
| `active_task_id` | str \| null | id задачи в работе |
| `circuit_breaker` | obj | `{"max_iterations_per_task": 4}` |
| `systems` | array | `{name, path, stack, preset?, data_only?, bootstrap}`; bootstrap: `ready|ready_with_notes|ready_data_only|stop` |
| `tasks` | array | см. ниже |

## Задача

| Поле | Канон |
|---|---|
| `id` | `T<номер>` |
| `fr_ids` | `["FR-<номер задачи>"]` — трассируемость к СТ |
| `title` | человекочитаемое название |
| `description` | 1–2 предложения сути задачи для витрины (карточка — полный контракт) |
| `system` | имя из `systems` |
| `phase` | `regular` \| `contract` \| `producer` \| `consumer` \| `characterization` |
| `branch` | `harness/FNR-<N>-<slug>-t<k>` |
| `worktree` | `.worktrees/FNR-<N>-t<k>` (заполняется при старте задачи) |
| `status` | `PLANNED` → `APPROVED` → `TDD_RED` → `TDD_GREEN` → `GATES` → `AGENT_REVIEW` → `DONE`; терминальные `ESCALATED_BLOCKED`, `ABORTED`; пауза — флаг `.flags/PAUSE`, не статус |
| `depends_on` | id задач; контрактная задача T1 — от неё зависят producers/consumers |
| `acceptance_criteria` | `[{id, desc, status, test}]`; `id` = `AC-<номер задачи>.<k>`; status: `PENDING`→`PASSED`/`FAILED`; `test` — имя теста, когда критерий покрыт |
| `gates` | `{build, test, lint, coverage, review}`: `pending|passed|failed|skipped` (`coverage`/`lint` — `skipped`, если инструмента нет) |
| `iteration_count` | счётчик TDD-итераций (circuit breaker при > 4) |
| `review_verdict` | `APPROVED` \| `CHANGES_REQUESTED` \| `BLOCKED` \| null |

## Правила

1. Имя теста критерия: `test_ac_<номер_с_подчёркиваниями>_<k>_<действие>` (пресет стека уточняет стиль).
2. `data_only: true` системы — задачи с `gates.build/test = "skipped"`.
3. Меняешь манифест — обнови `updated_at` и прогони `manifest_check.py`.
4. UI ничего не пишет в манифест; управление — только `.flags/` и `comments/`.
5. **Комментарии к задаче** — `harness/comments/T<k>.md` (append-only markdown):
   `- [YYYY-MM-DD HH:MM | author] текст`, author ∈ `agent|human|reviewer`. Агент оставляет
   комментарий на ключевых событиях: старт задачи, RED-гейт, каждая эскалация, завершение,
   вердикт ревью. Человек — из UI (кнопка отправки) или редактированием файла. Комментарии
   НЕ дублируют карточку — это живой журнал задачи.
