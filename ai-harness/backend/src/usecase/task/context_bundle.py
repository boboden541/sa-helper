"""Контекстный бандл агента: постановка + чеклисты + отчёты этапов + комментарии +
связи + хвост хроник (СТ §4.3.1; чеклист — источник истины о прогрессе, 02.11.2026).
"""

from __future__ import annotations

import sqlalchemy as sa
from repository.models import (
    Checklist,
    ChecklistItem,
    Chronicle,
    Project,
    PsiDocument,
    Tag,
    Task,
    TaskArtifact,
    TaskComment,
    TaskRelation,
    TaskTag,
    TaskType,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession

_OPEN = ("done", "closed")


def _squeeze(text: str, limit: int = 4000) -> str:
    """Длинный артефакт → начало + конец (вердикты обычно в конце отчёта)."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head, tail = text[:1200], text[-(limit - 1200) :]
    return f"{head}\n…[сокращено]…\n{tail}"


async def build_context_md(session: AsyncSession, task: Task) -> str:
    # ФТ-FNR15-08.3: изоляция контекста «ПСИ-редактора» — на psi_review агент видит
    # ТОЛЬКО документ и адреса/учётки стенда. Никаких исходников, Story Delta,
    # чеклистов и хроник: ревизия «глазами менеджера» падает, если у неё есть
    # возможность «додумать» по коду.
    if task.status_key == "psi_review":
        return await _psi_review_bundle(session, task)

    type_key = (
        await session.execute(sa.select(TaskType.key).where(TaskType.id == task.task_type_id))
    ).scalar_one()
    tags = (
        (
            await session.execute(
                sa.select(Tag.label)
                .join(TaskTag, TaskTag.tag_id == Tag.id)
                .where(TaskTag.task_id == task.id)
            )
        )
        .scalars()
        .all()
    )

    parts = [
        f"Задача {task.code} [{type_key}] — {task.title}",
        f"Статус: {task.status_key}; приоритет: {task.priority}; теги: {', '.join(tags)}",
        *(
            [f"Репозиторий доработки: {task.repo_path} (worktree и ветка task/<код> — в нём)"]
            if task.repo_path
            else []
        ),
        f"\n## Постановка\n{_squeeze(task.description_md or '(описание пусто)', 60000)}",
    ]

    # здоровье psi-плана: сравнение версий эталона и заверки плана —
    # вычисляемый факт, агент обязан увидеть дрейф (решение владельца 03.11.2026)
    if type_key == "story":
        from usecase.story.reference import psi_plan_ref_version

        plan_ref = await psi_plan_ref_version(session, task.id)
        if plan_ref is None:
            parts.append(
                "\n⚠ PSI-ПЛАНА НЕТ: документ ПСИ не зарегистрирован. "
                "Составь документ и зарегистрируй версию "
                "(POST /stories/{код}/psi через host.docker.internal:8000) — "
                "чеклист psi станет планом прогона. Методология psi-methodology."
            )
        elif plan_ref < task.ref_version:
            parts.append(
                f"\n⚠ ПЛАН ПСИ УСТАРЕЛ: эталон постановки v{task.ref_version}, "
                f"план заверен v{plan_ref}. Сначала пересмотри план под текущий "
                "эталон (сверь с psi.md, дополни/убери пункты) и зарегистрируй "
                "новую версию документа — потом прогон. "
                "Методология psi-methodology: «Полный прогон обязателен»."
            )
        else:
            parts.append(
                f"\nПлан ПСИ актуален: эталон v{task.ref_version}, план заверен v{plan_ref}."
            )

        # ФТ-FNR15-02: дельта-брифинг — какие пункты плана затронуты с момента
        # последней регистрации версии документа. База = created_at последнего
        # psi_document; затронуты дети с updated_at позже базы (или без базы — все).
        if task.status_key == "qa_ready":
            last_doc = (
                await session.execute(
                    sa.select(PsiDocument.version, PsiDocument.created_at)
                    .where(PsiDocument.story_id == task.id)
                    .order_by(PsiDocument.version.desc())
                    .limit(1)
                )
            ).first()
            base_v = last_doc[0] if last_doc else None
            base_dt = last_doc[1] if last_doc else None

            ch_q = sa.select(Task.id, Task.code, Task.title, Task.status_key).where(
                Task.story_id == task.id
            )
            if base_dt is not None:
                ch_q = ch_q.where(Task.updated_at > base_dt)
            affected = (await session.execute(ch_q.order_by(Task.code))).all()

            if affected:
                linked = (
                    await session.execute(
                        sa.select(ChecklistItem.linked_task_id, ChecklistItem.position)
                        .join(Checklist, Checklist.id == ChecklistItem.checklist_id)
                        .where(
                            Checklist.task_id == task.id,
                            Checklist.kind == "psi",
                            ChecklistItem.kind == "item",
                            ChecklistItem.linked_task_id.isnot(None),
                        )
                    )
                ).all()
                cover: dict = {}
                for lid, pos in linked:
                    cover.setdefault(lid, []).append(f"П.{pos}")
                base_label = f"v{base_v}" if base_v else "документа нет"
                lines = [
                    f"\n## Дельта ПСИ (база: {base_label}) — пункты на переработку:",
                    "Переработай/создай ТОЛЬКО эти пункты (с taskCode) — остальные"
                    " переносятся системой (carry-forward). Методология psi-methodology.",
                ]
                for tid, tcode, ttitle, tstatus in affected:
                    pts = cover.get(tid)
                    if pts:
                        lines.append(
                            f"- {tcode} «{ttitle}» [{tstatus}] — "
                            f"затронуты пункты {', '.join(pts)} — ПЕРЕРАБОТАТЬ"
                        )
                    else:
                        lines.append(
                            f"- {tcode} «{ttitle}» [{tstatus}] — "
                            "НЕ покрыт ни одним пунктом — СОЗДАТЬ пункт"
                        )
                parts.append("\n".join(lines))

        # Срез изменений истории (Story Delta, ФТ-FNR14-03): дочерние задачи и баги
        from repository.models import TaskBranch

        children_q = (
            sa.select(
                Task.id,
                Task.code,
                Task.title,
                Task.status_key,
                TaskType.key.label("type_key"),
                TaskBranch.branch_name,
                TaskBranch.head_commit,
                TaskBranch.diff_stats,
            )
            .join(TaskType, TaskType.id == Task.task_type_id)
            .outerjoin(TaskBranch, TaskBranch.task_id == Task.id)
            .where(Task.story_id == task.id)
            .order_by(Task.code)
        )
        children_res = (await session.execute(children_q)).all()
        if children_res:
            delta_lines = [
                f"\n## Срез изменений истории (Story Delta) — дочерних задач: {len(children_res)}"
            ]
            # последние dev-отчёты всех детей одним запросом (было N+1: отдельный
            # SELECT на каждого ребёнка при каждом построении контекста)
            child_ids = [r[0] for r in children_res]
            last_reports: dict = {}
            reps = (
                await session.execute(
                    sa.select(TaskArtifact.task_id, TaskArtifact.version, TaskArtifact.body_md)
                    .where(
                        TaskArtifact.task_id.in_(child_ids),
                        TaskArtifact.kind == "dev_report",
                    )
                    .order_by(TaskArtifact.version)
                )
            ).all()
            for rid, _ver, body in reps:
                last_reports[rid] = body
            for cid, ccode, ctitle, cstatus, ctype, cbranch, chead, cdiff in children_res:
                dev_rep = last_reports.get(cid)
                summary_short = ""
                if dev_rep:
                    summary_short = dev_rep.strip().split("\n\n")[0][:300]
                diff_txt = ""
                if isinstance(cdiff, dict) and cdiff.get("stat"):
                    stat_lines = cdiff["stat"].strip().split("\n")
                    diff_txt = f"\n  - Дифф: {', '.join(line.strip() for line in stat_lines[:4])}"

                delta_lines.append(
                    f"- **[{ctype}] {ccode} «{ctitle}»** — статус: {cstatus}"
                    + (f"; коммит: `{chead[:8]}` (ветка `{cbranch}`)" if chead else "")
                    + diff_txt
                    + (f"\n  - Резюме разработчика: {summary_short}" if summary_short else "")
                )
            parts.append("\n".join(delta_lines))

    # Инфраструктура тестового стенда (ФТ-FNR14-01)
    project = await session.get(Project, task.project_id)
    if project and project.path:
        import json
        from pathlib import Path

        from infrastructure.paths import host_to_container, task_repo_root

        root_path = Path(host_to_container(task_repo_root(project.path, task.repo_path)))
        stand_file = root_path / ".harness" / "stand.json"
        if stand_file.exists():
            try:
                stand_data = json.loads(stand_file.read_text(encoding="utf-8"))
                services = stand_data.get("services", {})
                auth = stand_data.get("auth", {})
                bootstrap = stand_data.get("bootstrap", {})

                stand_lines = ["\n## Параметры тестового стенда (.harness/stand.json)"]
                for s_name, s_info in services.items():
                    port = s_info.get("host_port")
                    url = s_info.get("base_url") or s_info.get("dsn") or f":{port}"
                    stype = s_info.get("type", "service")
                    stand_lines.append(f"- **{s_name}** [{stype}]: `{url}` (порт {port})")
                    try:
                        port_num = int(port)
                    except (TypeError, ValueError):
                        continue  # нечисловой порт не проверяем
                    if not 21000 <= port_num <= 29999:
                        stand_lines.append(
                            f"  - ⚠️ ПОРТ ВНЕ ПОЛИТИКИ 21000–29999: {port} — конфликт с "
                            "харнесом (:8000/:8088/:5433) или чужие порты контура; "
                            "перенесите сервис (методологии, глобальные docker-правила)."
                        )
                    if port_num in (8000, 8088, 5433):
                        stand_lines.append(
                            "  - ⚠️ ЗАПРЕЩЁННЫЙ ПОРТ: конфликт с харнесом "
                            "(:8000/:8088/:5433) — перенесите сервис."
                        )

                users = auth.get("test_users", [])
                if users:
                    stand_lines.append("### Тестовые пользователи")
                    for u in users[:3]:
                        stand_lines.append(
                            f"- {u.get('role', 'user')}: `{u.get('email')}` / `{u.get('password')}`"
                        )

                if bootstrap.get("healthcheck_cmd"):
                    stand_lines.append(f"- **Healthcheck:** `{bootstrap.get('healthcheck_cmd')}`")

                parts.append("\n".join(stand_lines))
            except Exception as err:  # noqa: BLE001 — невалидный манифест не роняет контекст
                # молчаливый пропуск дефектен (анализ 06.11): агент не узнавал,
                # что манифест нечитаем. Показываем отказ прямо в блоке
                parts.append(
                    f"\n## Параметры тестового стенда — МАНИФЕСТ НЕЧИТАЕМ: {str(err)[:200]}. "
                    "Проверь .harness/stand.json (валидный JSON?) и сообщи человеку."
                )

    # Чеклисты — ИСТОЧНИК ИСТИНЫ о прогрессе: открытые пункты = точка продолжения
    checks = (
        await session.execute(
            sa.select(
                Checklist.kind, ChecklistItem.position, ChecklistItem.text, ChecklistItem.status
            )
            .join(ChecklistItem, ChecklistItem.checklist_id == Checklist.id)
            .where(Checklist.task_id == task.id)
            .order_by(Checklist.kind, ChecklistItem.position)
        )
    ).all()
    if checks:
        by_kind: dict[str, list] = {}
        for kind, position, text, status in checks:
            by_kind.setdefault(kind, []).append((position, text, status))
        blocks = []
        for kind, items in by_kind.items():
            open_items = [(p, t, s) for p, t, s in items if s not in _OPEN]
            closed = [str(p) for p, t, s in items if s in _OPEN]
            lines = [f"### Чеклист {kind} — закрыто {len(items) - len(open_items)}/{len(items)}"]
            lines += [f"- ☐ №{p} {t} [{s}]" for p, t, s in open_items]
            if kind == "psi" and type_key == "story":
                lines.append(
                    "- Отмечай каждый пункт СРАЗУ после проверки: POST /stories/{код}/psi/items "
                    '{"position": N, "passed": true/false, "actual": "факт"} '
                    "через host.docker.internal:8000 — отметка переживает обрыв сессии"
                )
            if closed:
                lines.append(f"- ✓ закрыты: №{', №'.join(closed)}")
            blocks.append("\n".join(lines))
        parts.append(
            "\n## Чеклисты — источник истины: открытые пункты = с чего продолжить\n"
            + "\n".join(blocks)
        )

    # Отчёты этапов: последние версии — итоги прошлых прогонов (вердикты, найденное)
    last_v = (
        sa.select(TaskArtifact.kind, sa.func.max(TaskArtifact.version).label("v"))
        .where(TaskArtifact.task_id == task.id)
        .group_by(TaskArtifact.kind)
        .subquery()
    )
    arts = (
        await session.execute(
            sa.select(TaskArtifact.kind, TaskArtifact.version, TaskArtifact.body_md)
            .join(
                last_v, (TaskArtifact.kind == last_v.c.kind) & (TaskArtifact.version == last_v.c.v)
            )
            .order_by(TaskArtifact.kind)
        )
    ).all()
    if arts:
        blocks = [
            f"### Отчёт {kind} (v{version})\n{_squeeze(body)}" for kind, version, body in arts
        ]
        parts.append(
            "\n## Отчёты этапов (итоги прошлых прогонов — не повторяй подтверждённое)\n"
            + "\n\n".join(blocks)
        )

    # Комментарии: последние 8 — прямой канал человека и прошлых агентов
    comments = (
        await session.execute(
            sa.select(TaskComment.body, User.name, User.user_type)
            .join(User, User.id == TaskComment.author_id)
            .where(TaskComment.task_id == task.id)
            .order_by(TaskComment.created_at.desc())
            .limit(8)
        )
    ).all()
    if comments:
        lines = [
            f"- «{body[:2000]}» — {name} ({'человек' if ut == 'human' else 'агент'})"
            for body, name, ut in reversed(comments)
        ]
        parts.append(
            "\n## Комментарии (последние; человеческие — приоритетны)\n" + "\n".join(lines)
        )

    relations = (
        await session.execute(
            sa.select(TaskRelation.kind, Task.code, Task.title)
            .join(Task, Task.id == TaskRelation.to_task)
            .where(TaskRelation.from_task == task.id)
        )
    ).all()
    if relations:
        lines = [f"- {kind} {code} «{title}»" for kind, code, title in relations]
        parts.append("\n## Связи\n" + "\n".join(lines))

    # индекс задач проекта: коды соседей для declarations связей (relations_updates)
    siblings = await session.execute(
        sa.select(Task.code, Task.title, Task.status_key)
        .join(Project, Project.id == Task.project_id)
        .where(
            Task.project_id == task.project_id,
            Task.status_key.notin_(("done", "canceled")),
            Task.id != task.id,
        )
        .order_by(Task.code)
        .limit(12)
    )
    if siblings:
        lines = [f"- {code} «{title}» — {status}" for code, title, status in siblings]
        parts.append(
            "\n## Задачи проекта (для связей: что сначала, что потом, кто кого блокирует)\n"
            + "\n".join(lines)
        )

    # Допустимые переходы из текущего статуса: агент предлагает только их,
    # не догадывается о ключах статусов (инцидент AH-130: агент выдумал
    # «testing» вместо qa_ready — движок честно отказал, попытка сгорела)
    from repository.flow_queries import current_flow_version_id
    from repository.models import FlowStatus, FlowTransition, FlowVersion

    # fv_id заранее: подзапрос в ON джойна путал SQLAlchemy разрешение FROM
    # (анализ 03.11.2026); двухшаговое получение id — детерминированный план
    fv_id = await current_flow_version_id(session, task.task_type_id)
    edges = (
        await session.execute(
            sa.select(
                FlowTransition.to_status,
                FlowTransition.runner,
                FlowTransition.display,
                FlowStatus.label,
            )
            .join(FlowVersion, FlowVersion.id == FlowTransition.flow_version_id)
            .join(
                FlowStatus,
                (FlowStatus.flow_version_id == FlowTransition.flow_version_id)
                & (FlowStatus.status_key == FlowTransition.to_status),
            )
            .where(FlowVersion.id == fv_id, FlowTransition.from_status == task.status_key)
        )
    ).all()
    if edges:
        lines = [
            f"- → {to} «{label}» — исполнитель: {runner}" + (f" ({display})" if display else "")
            for to, runner, display, label in edges
        ]
        parts.append(
            "\n## Куда можно предлагать переход (только эти ключи статусов)\n" + "\n".join(lines)
        )

    tail = (
        (
            await session.execute(
                sa.select(Chronicle.message)
                .where(Chronicle.task_id == task.id)
                .order_by(Chronicle.created_at.desc())
                .limit(12)
            )
        )
        .scalars()
        .all()
    )
    if tail:
        parts.append(
            "\n## Хроника (последние события)\n" + "\n".join(f"- {m}" for m in reversed(tail))
        )

    return "\n".join(parts)


async def _psi_review_bundle(session: AsyncSession, task: Task) -> str:
    """Минимальный контекст ревизора (ФТ-FNR15-08.3): документ ПСИ + параметры
    стенда. Терминал разрешён — шаги документа исполняются «как написано»."""
    import json
    from pathlib import Path

    from infrastructure.paths import host_to_container, task_repo_root
    from repository.models import Checklist, ChecklistItem

    rows = (
        await session.execute(
            sa.select(
                ChecklistItem.kind,
                ChecklistItem.position,
                ChecklistItem.text,
                ChecklistItem.psi_expected,
                ChecklistItem.psi_actual,
                ChecklistItem.status,
            )
            .join(Checklist, Checklist.id == ChecklistItem.checklist_id)
            .where(
                Checklist.task_id == task.id,
                Checklist.kind == "psi",
            )
            .order_by(ChecklistItem.position)
        )
    ).all()
    doc_lines: list[str] = []
    for kind, pos, text, expected, actual, _status in rows:
        if kind == "heading":
            doc_lines.append(f"\n## {text}")
        elif kind == "item":
            doc_lines.append(f"\n### П.{pos} {text}")
            doc_lines.append(f"Ожидаемый результат: {expected or '(не указано)'}")
            if actual:
                doc_lines.append(f"(прошлый факт: {actual[:200]})")

    parts = [
        "# Ревизия документа ПСИ (ФТ-FNR15-08)",
        "Ты — менеджер продукта БЕЗ инженерного бэкграунда. Твоя единственная задача —"
        " проверить, что документ ПСИ ниже ПОНЯТЕН и ВОСПРОИЗВОДИМ «как написано»:",
        "- исполняй шаги документа буквально, только то, что написано; ничего не додумывай;",
        "- НЕ читай исходный код проекта, историю задачи и прочие материалы — их у тебя нет;",
        "- если шаг нельзя выполнить (не сказано, где выполнять; нет пароля; команда"
        " ссылается на то, чего нет) — фиксируй «П.N: невоспроизводим — причина»;",
        "- в конце отправь вердикт: POST "
        f"host.docker.internal:8000/api/v1/stories/{task.code}/psi/review "
        'с телом {"verdict": true|false, "note": "адресные причины по пунктам"} '
        "(Content-Type: application/json; методология в скилле psi-editor).",
        "- бюджет: уложись в 60 минут; застрял — отправляй verdict=false с причинами.",
        "\n## Документ ПСИ",
        "\n".join(doc_lines) or "(документ пуст)",
    ]

    project = await session.get(Project, task.project_id)
    if project and project.path:
        stand_path = (
            Path(host_to_container(task_repo_root(project.path, task.repo_path)))
            / ".harness"
            / "stand.json"
        )
        if stand_path.exists():
            try:
                stand = json.loads(stand_path.read_text(encoding="utf-8"))
                parts.append(
                    "\n## Адреса и учётки стенда"
                    "\nИспользуй ТОЛЬКО их; порты/адреса из документа должны совпадать."
                )
                for name, info in stand.get("services", {}).items():
                    url = info.get("base_url") or info.get("dsn") or ""
                    parts.append(f"- {name}: `{url}`")
                for u in stand.get("auth", {}).get("test_users", [])[:5]:
                    parts.append(
                        f"- учётка {u.get('role', 'user')}: `{u.get('email')}` / "
                        f"`{u.get('password')}`"
                    )
            except Exception:  # noqa: BLE001
                parts.append("\n(stand.json нечитаем — продолжай по тексту документа)")
    return "\n\n".join(parts)
