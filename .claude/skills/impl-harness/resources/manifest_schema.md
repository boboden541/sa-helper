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
   `- [YYYY-MM-DD HH:MM | author] **Заголовок** — суть`, author ∈ `agent|human|reviewer|daemon`.
   Запись многострочная (тело — markdown до следующей записи; подпункты «·», не «-»).
   Комментарий — отчёт для человека, не видевшего сессию: что произошло, почему, что дальше.
   Канон качества и шаблоны событий — навык `.claude/skills/comment-writing/SKILL.md`.
   Агент пишет на ключевых событиях (старт, RED/GREEN, эскалация, завершение, вердикт),
   ревьюер — вердикт, человек — из UI, демон — переходы статусов.

## Поля конвейера v3 (опциональные; документ валиден и без них)

| Поле | Где | Канон |
|---|---|---|
| `auto_mode` | верхний уровень | булево, по умолчанию true: конвейер сам проходит стадии между шлюзами |
| `auto_review_strategy` | верхний уровень | `closure_first` (по умолчанию) \| `full_re_review` — стратегия ревью-петли |
| `created_by` | верхний уровень | `impl-plan` \| `impl-handoff` |
| `pipeline` | задача | `BACKLOG → READY → IMPLEMENTING → REVIEW → DONE → VERIFIED`; особые: `BLOCKED` (авто-retry), `NEEDS_HUMAN` (петля не сошлась), `ABORTED` — канон `harness/state_machine.py` |
| `blocked_from` | задача | статус для возврата после BLOCKED/NEEDS_HUMAN (`READY\|IMPLEMENTING\|REVIEW`) |
| `retries` / `review_iterations` | задача | счётчики демона и ревью-петли (int ≥ 0) |
| `paused` / `skip_review` | задача | булевы флаги задачи; пауза вступает на границе итерации |
| `session_id` | задача | последняя headless-сессия стадии (для `--resume` и чата) |
| `owner` | задача | `ai` \| `human` — кто исполнитель сейчас |
| `findings` | задача | `[{id, text, file?, resolution}]`; resolution: `open\|resolved\|still_blocking` — вход ревью-петли (closure_first) |

Владение полями: `pipeline`/`blocked_from`/`retries`/`review_iterations`/`session_id`/`owner`/`findings` —
пишет **демон**; `status`/`phase`/`iteration_count`/`acceptance_criteria[].status`/`gates` —
пишет **сессия исполнителя** (как в v2). Проверка согласованности — `manifest_check.py`
(принимает и v2-, и v3-документы).
