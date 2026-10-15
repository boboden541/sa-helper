---
description: AI Harness — автономное исполнение задачи плана в git worktree (TDD-цикл с RED-гейтом и circuit breaker)
---

## Использование

```
/impl-run <путь к каталогу harness> [T<k>]
```

**Параметры:**

- `<путь к каталогу harness>` — например, `sa_documentation/FNR/FNR_1/harness`.
- `[T<k>]` — id задачи из `manifest.json`; если не указан — берётся первая готовая по DAG (`depends_on` закрыты, статус `PLANNED`/`APPROVED`).

## Примеры

```
/impl-run sa_documentation/FNR/FNR_1/harness T2
```

```
/impl-run sa_documentation/FNR/FNR_1/harness
```

## Важно

**Приоритет:** СТРОГОЕ соблюдение TDD-цикла и circuit breaker (v2 §7, `resources/gates_checklist.md`):
тесты прежде кода, RED обязателен, максимум 4 итераций исправлений, правки только в worktree
и только в ветке `harness/*`. Основное рабочее дерево и main/develop не трогаются.

**Ожидаемый результат:** задача доведена до `GATES`→`AGENT_REVIEW` (код + тесты + коммит
`[FNR-<N>/T<k>]` + обновлённый `manifest.json` + логи) либо `ESCALATED_BLOCKED` с отчётом.

**Универсальность:** команды гейтов — из `workspaces.yaml`; роль и правила —
`.claude/skills/impl-harness/SKILL.md`; карточка задачи — единственный рабочий контракт.
`python3` (Windows Git Bash: `python`).

---

## Инструкция для LLM

Ты — исполнитель задачи контура. Работаешь строго по карточке `tasks/T<k>.md` и досье;
СТ открываешь только чтобы сверить точность пересказа.

### Графовый контекст (complement-модель)

Если MCP `sa-helper-graph` доступен — `graph_call_chain`/`graph_impact` для impact-лестницы
(шаг 5). Недоступен — ripgrep по импортам/вызовам. Не заходить в `.worktrees/` при поисках.

### Этап 0: Предусловия

1. `manifest.json`: статус плана `APPROVED`/`IN_PROGRESS` **и** файл `.flags/APPROVE_PLAN`
   существует. Нет → STOP: «план не утверждён».
2. Флаг `.flags/PAUSE` существует → STOP: «контур на паузе».
3. Задача по параметру или первая готовая по DAG. Не готова (deps не `DONE`) → перечисли, что
   мешает, STOP. Карточка — прочитай целиком.
4. Система задачи: `gates.build/test` ≠ `skipped`? Для `data_only`-системы TDD сводится к DDL-задаче
   (тесты = проверка скриптов ревью; смотри карточку).
5. Если работа в системе уже идёт (`active_task_id` ≠ null и ≠ эта задача) → STOP.

### Этап 1: Изоляция

1. В репозитории системы: `git worktree add .worktrees/FNR-<N>-t<k> -b harness/FNR-<N>-<slug>-t<k>`
   (если ветка/worktree уже есть от прошлой попытки — продолжи в нём).
2. Скрой артефакты: `.worktrees/` в `.git/info/exclude` (если ещё нет).
3. Включи enforcement, скоупинг по worktree (иначе конфиг протечёт в общие настройки репо и
   заденет основное дерево!):
   ```bash
   git config extensions.worktreeConfig true
   git config --worktree core.hooksPath <абсолютный путь к harness/hooks воркспейса>
   ```
   Каталога `harness/hooks` нет → скопируй из установки sa-helper (универсальные скрипты
   pre-commit/pre-push) в корень воркспейса один раз.
4. Все дальнейшие команды — из каталога worktree.

### Этап 2: TDD RED

1. По карточке напиши тесты acceptance-критериев: **имена** `test_ac_<номер>_<k>_<действие>`
   (стиль — пресет стека). Тесты не должны требовать кода, которого ещё нет, — только публичного
   контракта из карточки/досье.
2. Запусти гейт test (`runner.py --mode test`, команда из `workspaces.yaml`, `--log` в
   `<harness>/logs/T<k>_red.log`). RED-гейт: **новые тесты обязаны упасть**. Прошли на пустом
   коде → тесты фиктивны: перепиши (п. «RED-гейт» в `resources/gates_checklist.md`).
3. Зафиксируй в manifest: задача `status: "TDD_RED"`.

### Этап 3: TDD GREEN (circuit breaker = 4)

1. Минимальная реализация ровно под падающие тесты (пресет стека, Golden Reference из досье).
2. Прогони гейт test. Падает → исправь и повтори. `iteration_count` +1 за каждый цикл
   «исправил → прогнал».
3. **Перед каждой итерацией** проверь `.flags/PAUSE`: появился — остановись, манифест в текущем
   состоянии, отчёт человеку (снять паузу → продолжить этой же командой).
4. `iteration_count > 4` → **эскалация**: статус `ESCALATED_BLOCKED`, отчёт
   `logs/T<k>_failure_report.md` (что делал, что падает, гипотезы, что нужно человеку), STOP.
5. Тесты зелёные → статус `TDD_GREEN`; для каждого AC запиши в manifest `test` = имя теста,
   `status: "PASSED"`.

### Этап 4: Гейты качества

1. `lint_cmd` из реестра (есть) → `runner.py --mode lint`; нет — `gates.lint = "skipped"`.
2. **Impact-лестница** (`resources/gates_checklist.md`): импортёры изменённых файлов → прогон
   их тестов (суженный скоуп) → при чистом прогоне `gates.test = "passed"`.
3. Coverage: инструмент есть в репо (pytest-cov/jacoco) → дельта по изменённым файлам ≥ 80%
   (v2 §17 п. 1: нет инструмента — `gates.coverage = "skipped"`, не блокирует).
4. Все гейты зелёные/skipped → `status: "GATES"`.

### Этап 5: Коммит и завершение

1. Коммит в ветке задачи: `[FNR-<N>/T<k>] <type>: <кратко>` (type: feat/test/docs/chore).
2. Манифест атомарно: `status: "AGENT_REVIEW"`, `active_task_id: null`, логи перечислены.
3. Worktree оставить до ревью (`/impl-review` смотрит дифф; удалит `/impl-review` при APPROVED
   или человек при доработке). Основное дерево системы не тронуто — проверь `git status` там.
4. Если после тебя есть готовые задачи по DAG — предложи продолжить этой же командой.

Завершение: выведи резюме (AC → тесты, гейты, итерации, коммит) и литеральную подсказку:
«Задача T<k> готова к ревью. Следующий шаг: /impl-review <путь к harness> T<k>».
При эскалации — путь к failure_report и формулировку проблемы для человека.
