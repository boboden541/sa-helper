"""ПСИ: документ с версиями, прогоны со снапшотом пунктов, баги (СТ §4.5.2).

Каждая версия документа автоматически сохраняется файлом по пути истории
(task.psi_path, «Путь сохранения ПСИ» — например …/FNR/FNR_8/psi.md);
путь не задан — стандартный <путь проекта>/.harness/psi/<код истории>/psi.md
(решение владельца 27.10.2026)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from domain.model.validators import DomainError
from repository.models import (
    Checklist,
    ChecklistItem,
    Chronicle,
    Project,
    PsiDocument,
    PsiRun,
    PsiRunItem,
    Task,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession

from usecase.story.reference import psi_plan_ref_version


async def _story(session: AsyncSession, code: str) -> Task:
    story = (
        await session.execute(sa.select(Task).where(Task.code == code.upper()))
    ).scalar_one_or_none()
    if story is None:
        raise DomainError(f"История {code} не найдена")
    return story


def render_psi_md(
    story: Task, version: int, sections: list[dict], preamble_md: str | None = None
) -> str:
    """Рендер документа в канон идеального ПСИ (пример — FNR_8/psi.md)."""
    today = datetime.now(timezone.utc).date().isoformat()
    lines = [
        f"# Процедура приёмо-сдаточных испытаний (ПСИ): {story.title} ({story.code})",
        "",
        "**Назначение.** Этот документ — пошаговый сценарий проверки реализованного "
        "функционала. Каждый пункт — пара «Действие → Ожидаемый результат»: выполняете "
        "действие, сверяете факт с ожиданием, ставите вердикт ✓/✗.",
        f"**Дата документа:** {today}. **Версия документа:** v{version}.",
        "",
    ]
    if preamble_md and preamble_md.strip():
        lines += [preamble_md.strip(), ""]
    position = 0
    for section in sections:
        lines += [f"## {section.get('heading', 'Раздел')}", ""]
        for item in section.get("items", []):
            position += 1
            lines += [
                f"### П.{position} {item.get('action', '')}",
                "",
                f"**Ожидаемый результат:** {item.get('expected', '')}",
                "",
            ]
    return "\n".join(lines)


async def save_psi_file(session: AsyncSession, story: Task, md: str) -> str:
    """Пишет psi.md по пути истории (или в стандартное место); возвращает путь как на компьютере."""
    import os

    from infrastructure.paths import host_to_container

    user_path = (story.psi_path or "").strip() if story.psi_path else ""
    if not user_path:
        project = await session.get(Project, story.project_id)
        base = (project.path if project else "").rstrip("/")
        user_path = f"{base}/.harness/psi/{story.code}/psi.md" if base else ""
    if not user_path:
        raise DomainError("Путь сохранения ПСИ не задан и путь проекта неизвестен")
    target = Path(host_to_container(user_path))
    os.makedirs(target.parent, exist_ok=True)
    target.write_text(md, encoding="utf-8")
    return user_path


async def create_version(
    session: AsyncSession,
    story_code: str,
    author: User,
    sections: list[dict],
    preamble_md: str | None = None,
) -> int:
    """sections: [{"heading": str, "items": [{"action": str, "expected": str,
    "taskCode": str?}]}]. Пункт ПСИ — строка чеклиста kind='psi' (ФТ-ah-39).
    Версия сохраняется файлом по пути истории (psi_path).

    ФНР-15: если у payload-пунктов есть taskCode, совпадающий с linked_task_id
    действующих пунктов, регистрация работает в РЕЖИМЕ ДЕЛЬТЫ — пункты, чьи задачи
    не затронуты payload'ом, механически переносятся из прошлой версии
    (carry_forward, carried_from_version), и файл рендерится из полного документа
    (перенесённые секции + дельта). Иначе — полный документ (прежний контракт)."""
    story = await _story(session, story_code)
    version = (
        await session.execute(
            sa.select(sa.func.coalesce(sa.func.max(PsiDocument.version), 0)).where(
                PsiDocument.story_id == story.id
            )
        )
    ).scalar_one() + 1
    doc = PsiDocument(story_id=story.id, version=version, author_id=author.id)
    session.add(doc)
    await session.flush()

    # psi-чеклист у истории ОДИН (uq_checklist_task_kind): новая версия
    # переиспользует его с заменой пунктов. Было: новый Checklist каждый раз —
    # второй вызов падал UniqueViolation, «ПСИ v2» через API не создавался
    # вообще (найдено тестом УИТ 03.11.2026).
    chk = (
        await session.execute(
            sa.select(Checklist).where(Checklist.task_id == story.id, Checklist.kind == "psi")
        )
    ).scalar_one_or_none()
    if chk is None:
        chk = Checklist(task_id=story.id, kind="psi")
        session.add(chk)
        await session.flush()

    # ФНР-15: валидация taskCode — задача должна быть ребёнком/багом ЭТОЙ истории
    payload_task_ids: dict[str, uuid.UUID] = {}
    for section in sections:
        for item in section.get("items", []):
            code = (item.get("taskCode") or "").strip()
            if not code:
                continue
            if code.upper() in payload_task_ids:
                continue
            linked = (
                await session.execute(
                    sa.select(Task).where(sa.func.upper(Task.code) == code.upper())
                )
            ).scalar_one_or_none()
            if linked is None or linked.story_id != story.id:
                raise DomainError(
                    f"taskCode «{code}» не является задачей/багом истории {story.code}"
                )
            payload_task_ids[code.upper()] = linked.id

    # --- режим регистрации: полный документ или дельта с carry-forward ---
    old_rows = (
        (
            await session.execute(
                sa.select(ChecklistItem)
                .where(ChecklistItem.checklist_id == chk.id)
                .order_by(ChecklistItem.position)
            )
        )
        .scalars()
        .all()
        if chk.id is not None
        else []
    )
    linked_old_ids = {
        old.linked_task_id for old in old_rows if old.kind == "item" and old.linked_task_id
    }
    delta_mode = bool(linked_old_ids & set(payload_task_ids.values()))

    carried_from = version - 1
    if delta_mode:
        # переносятся все строки, КРОМЕ пунктов, чьи задачи затронуты payload'ом
        carried_rows = [
            old
            for old in old_rows
            if not (old.kind == "item" and old.linked_task_id in payload_task_ids.values())
        ]
        # полный документ = перенесённые секции (в прежнем порядке) + дельта-секции
        full_sections: list[dict] = []
        current: dict | None = None
        for old in carried_rows:
            if old.kind == "heading":
                current = {"heading": old.text, "items": []}
                full_sections.append(current)
            else:
                if current is None:
                    current = {"heading": "Без секции", "items": []}
                    full_sections.append(current)
                current["items"].append(
                    {
                        "action": old.text,
                        "expected": old.psi_expected or "",
                    }
                )
        full_sections.extend(sections)
        render_sections = full_sections
        carried_count = sum(1 for old in carried_rows if old.kind == "item")
    else:
        carried_rows = []
        render_sections = sections
        carried_count = 0

    await session.execute(sa.delete(ChecklistItem).where(ChecklistItem.checklist_id == chk.id))
    position = 0
    items_count = 0
    # перенос: прежний текст/ожидание/связи, вердикт сброшен под новый прогон
    for old in carried_rows:
        session.add(
            ChecklistItem(
                checklist_id=chk.id,
                position=position,
                kind=old.kind,
                level=old.level,
                text=old.text,
                status="todo",
                psi_expected=old.psi_expected,
                psi_actual=None,
                linked_task_id=old.linked_task_id,
                bug_task_id=old.bug_task_id,
                carried_from_version=carried_from if old.kind == "item" else None,
            )
        )
        position += 1
        if old.kind == "item":
            items_count += 1
    for section in sections:
        session.add(
            ChecklistItem(
                checklist_id=chk.id,
                position=position,
                kind="heading",
                level=1,
                text=section.get("heading", "Раздел"),
            )
        )
        position += 1
        for item in section.get("items", []):
            code = (item.get("taskCode") or "").strip().upper()
            session.add(
                ChecklistItem(
                    checklist_id=chk.id,
                    position=position,
                    kind="item",
                    text=item.get("action", ""),
                    status="todo",
                    psi_expected=item.get("expected", ""),
                    linked_task_id=payload_task_ids.get(code),
                )
            )
            position += 1
            items_count += 1

    # повторная регистрация = новая ревизия «ПСИ-редактора» (ФТ-FNR15-08)
    chk.manager_review_version = None
    chk.manager_review_state = None

    carry_note = f", перенесено {carried_count}" if delta_mode else ""
    session.add(
        Chronicle(
            task_id=story.id,
            event_type="psi",
            author_id=author.id,
            author_kind="agent" if author.user_type == "agent" else "human",
            message=f"Составлен ПСИ v{version} ({items_count} пунктов{carry_note})",
        )
    )

    # файл psi.md — в папку назначения (например, sa_documentation/FNR/FNR_<N>/psi.md).
    # Одна транзакция на версию (было 3 коммита: данные, файл-ок, файл-фейл —
    # отказ между ними оставлял БД и файл в разных фазах; анализ 03.11.2026).
    # Риск-окно неустранимо: файл вне БД — при сбое коммита файл остаётся
    # сиротой (документ в БД не зафиксирован); осознанный компромисс.
    try:
        md = render_psi_md(story, version, render_sections, preamble_md)
        saved_to = await save_psi_file(session, story, md)
        session.add(
            Chronicle(
                task_id=story.id,
                event_type="psi",
                author_id=author.id,
                author_kind="auto",
                rule_code="PSI_FILE",
                message=f"Файл ПСИ v{version} сохранён: {saved_to}",
            )
        )
    except (OSError, DomainError) as err:
        session.add(
            Chronicle(
                task_id=story.id,
                event_type="psi",
                author_id=author.id,
                author_kind="auto",
                rule_code="PSI_FILE",
                message=f"Файл ПСИ v{version} НЕ сохранён: {err}",
            )
        )
    # регистрация версии документа = заверка psi-плана текущей версией эталона
    chk.source_ref_version = story.ref_version
    await session.commit()
    return version


async def link_task(
    session: AsyncSession, story_code: str, actor: User, position: int, task_code: str
) -> dict:
    """ФТ-FNR15-01: карта покрытия «пункт ПСИ ↔ задача» (аналог link_bug).
    Идемпотентен: повторная связь той же задачи — без изменения."""
    story = await _story(session, story_code)
    _, items = await _current_doc_and_items(session, story.id)
    item = next((i for i in items if i.kind == "item" and i.position == position), None)
    if item is None:
        raise DomainError(f"Пункт П.{position} не найден в текущем документе ПСИ")
    linked = (
        await session.execute(sa.select(Task).where(sa.func.upper(Task.code) == task_code.upper()))
    ).scalar_one_or_none()
    if linked is None or linked.story_id != story.id:
        raise DomainError(f"«{task_code}» не является задачей/багом истории {story.code}")
    item.linked_task_id = linked.id
    session.add(
        Chronicle(
            task_id=story.id,
            event_type="psi",
            author_id=actor.id,
            author_kind="agent" if actor.user_type == "agent" else "human",
            message=f"Пункт П.{position} связан с {linked.code} (карта покрытия)",
        )
    )
    await session.commit()
    return {"position": position, "linkedTaskCode": linked.code}


async def set_manager_review(
    session: AsyncSession, story_code: str, reviewer: User, verdict: bool, note: str | None
) -> dict:
    """ФТ-FNR15-08: вердикт «ПСИ-редактора» о документе. approved → ребро M3b
    (psi_review → in_testing); rejected → ребро M3c (возврат на qa_ready с
    адресной причиной в контексте составителя)."""
    story = await _story(session, story_code)
    chk = (
        await session.execute(
            sa.select(Checklist).where(Checklist.task_id == story.id, Checklist.kind == "psi")
        )
    ).scalar_one_or_none()
    if chk is None:
        raise DomainError("У истории нет плана ПСИ — ревизовать нечего")
    latest = (
        await session.execute(
            sa.select(sa.func.max(PsiDocument.version)).where(PsiDocument.story_id == story.id)
        )
    ).scalar_one()
    chk.manager_review_version = latest
    chk.manager_review_state = "approved" if verdict else "rejected"
    session.add(
        Chronicle(
            task_id=story.id,
            event_type="psi",
            author_id=reviewer.id,
            author_kind="agent" if reviewer.user_type == "agent" else "human",
            message=(
                f"ПСИ v{latest}: редактор {'одобрил' if verdict else 'ОТКЛОНИЛ'}"
                + (f": {(note or '')[:300]}" if note and not verdict else "")
            ),
        )
    )
    await session.commit()
    return {"version": latest, "state": chk.manager_review_state}


async def _current_doc_and_items(session: AsyncSession, story_id):
    doc = (
        await session.execute(
            sa.select(PsiDocument)
            .where(PsiDocument.story_id == story_id)
            .order_by(PsiDocument.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if doc is None:
        raise DomainError("У истории нет документа ПСИ")
    chk = (
        await session.execute(
            sa.select(Checklist).where(Checklist.task_id == story_id, Checklist.kind == "psi")
        )
    ).scalar_one_or_none()
    items = (
        (
            await session.execute(
                sa.select(ChecklistItem)
                .where(ChecklistItem.checklist_id == chk.id)
                .order_by(ChecklistItem.position)
            )
        )
        .scalars()
        .all()
        if chk
        else []
    )
    return doc, items


async def run_psi(
    session: AsyncSession, story_code: str, runner: User, results: list[dict]
) -> dict:
    """Прогон: [{position, passed: bool, actual}] → протокол со снапшотом пунктов (ФТ-ah-41).
    Непройденный пункт предлагает баг с предзаполнением (возвращает без создания)."""
    story = await _story(session, story_code)
    doc, items = await _current_doc_and_items(session, story.id)
    item_rows = [i for i in items if i.kind == "item"]

    passed = failed = 0
    run = PsiRun(psi_doc_id=doc.id, run_by=runner.id, passed=0, failed=0)
    session.add(run)
    await session.flush()

    bug_proposals = []
    for r in results:
        position = r["position"]
        item = next((i for i in item_rows if i.position == position), None)
        if item is None:
            continue
        status = "done" if r.get("passed") else "failed"
        item.status = status
        item.psi_actual = r.get("actual", "")
        session.add(
            PsiRunItem(
                psi_run_id=run.id,
                item_id=item.id,
                position=position,
                item_text=item.text,
                expected=item.psi_expected,
                status=status,
                actual=r.get("actual", ""),
            )
        )
        if r.get("passed"):
            passed += 1
        else:
            failed += 1
            # дубль бага не создаётся: незакрытый баг пункта уже есть → предложение нет
            if item.bug_task_id is None:
                bug_proposals.append(
                    {
                        "position": position,
                        "action": item.text,
                        "expected": item.psi_expected or "",
                        "actual": r.get("actual", ""),
                    }
                )

    run.passed = passed
    run.failed = failed
    session.add(
        Chronicle(
            task_id=story.id,
            event_type="psi",
            author_id=runner.id,
            author_kind="agent" if runner.user_type == "agent" else "human",
            message=f"Прогон ПСИ v{doc.version}: {passed} пройдено, {failed} не пройдено",
        )
    )
    await session.commit()
    return {
        "version": doc.version,
        "passed": passed,
        "failed": failed,
        "bugProposals": bug_proposals,
        "runId": str(run.id),
    }


async def link_bug(session: AsyncSession, story_code: str, position: int, bug_code: str) -> None:
    """Связывает пункт ПСИ с заведённым багом (идемпотентность цикла, ФТ-ah-42)."""
    story = await _story(session, story_code)
    _, items = await _current_doc_and_items(session, story.id)
    item = next((i for i in items if i.kind == "item" and i.position == position), None)
    if item is None:
        raise DomainError(f"Пункт {position} не найден")
    bug = (
        await session.execute(sa.select(Task).where(Task.code == bug_code.upper()))
    ).scalar_one_or_none()
    if bug is None:
        raise DomainError(f"Баг {bug_code} не найден")
    item.bug_task_id = bug.id
    session.add(
        Chronicle(
            task_id=story.id,
            event_type="bug",
            author_kind="human",
            message=f"Пункт {position} ПСИ связан с багом {bug.code}",
        )
    )
    await session.commit()
    # M4 (ФТ-ah-36): «все баги заведены с привязкой к истории» → blocked (из in testing)
    _, items_now = await _current_doc_and_items(session, story.id)
    failed_items = [i for i in items_now if i.kind == "item" and i.status == "failed"]
    if (
        failed_items
        and all(i.bug_task_id for i in failed_items)
        and story.status_key == "in_testing"
    ):
        from usecase.story.mirror import apply_m4

        await apply_m4(session, story)


async def mark_item(
    session: AsyncSession,
    story_code: str,
    actor: User,
    position: int,
    passed: bool,
    actual: str,
) -> dict:
    """Поэтапная отметка пункта ПСИ по ходу прогона (решение владельца 04.11.2026).

    Вердикт фиксируется сразу — переживает обрыв сессии, гейт M6 и карточка
    видят живую картину прогона. Пройденный пункт — без события (шум не плодим),
    непройденный — событие в хроники: владелец видит провал немедленно."""
    story = await _story(session, story_code)
    _, items = await _current_doc_and_items(session, story.id)
    # П.N — документная нумерация: сквозной счётчик ТОЛЬКО по пунктам (kind=
    # "item"), заголовки секций занимают position в чеклисте, но в документе
    # не нумеруются. Раньше сверяли чеклист-позицию с документным номером —
    # после первой секции промах: П.3 = position 4 → молча чужой пункт
    item_rows = sorted((i for i in items if i.kind == "item"), key=lambda i: i.position)
    item = item_rows[position - 1] if 0 < position <= len(item_rows) else None
    if item is None:
        raise DomainError(f"Пункт П.{position} не найден в текущем документе ПСИ")
    item.status = "done" if passed else "failed"
    item.psi_actual = (actual or "").strip() or None
    if not passed:
        session.add(
            Chronicle(
                task_id=story.id,
                event_type="psi",
                author_id=actor.id,
                author_kind="agent" if actor.user_type == "agent" else "human",
                message=f"Пункт П.{position} ПСИ НЕ ПРОЙДЕН"
                + (f": {(actual or '')[:200]}" if actual else ""),
            )
        )
    await session.commit()
    return {"position": position, "status": item.status, "passed": passed}


async def mark_rework(session: AsyncSession, story_code: str, actor: User) -> dict:
    """ФТ-FNR14-06: рычаг «переработать ПСИ». Версионирование (ref_version/
    ref_hash) отслеживает дрейф ЭТАЛОНА, но не качество плана — система не имела
    состояния «план формально заверен, но требует переработки» (разбор
    VITRINA-1 06.11: M3 мгновенно уводил историю с qa_ready, составитель не
    получал окна). Сброс заверенности гасит psi_ready — M3 ждёт новой версии."""
    story = await _story(session, story_code)
    chk = (
        await session.execute(
            sa.select(Checklist).where(Checklist.task_id == story.id, Checklist.kind == "psi")
        )
    ).scalar_one_or_none()
    if chk is None:
        raise DomainError("У истории нет плана ПСИ — перерабатывать нечего")
    chk.source_ref_version = None
    _, items = await _current_doc_and_items(session, story.id)
    count = 0
    for item in items:
        if item.kind == "item":
            item.status = "todo"
            item.psi_actual = None
            count += 1
    session.add(
        Chronicle(
            task_id=story.id,
            event_type="psi",
            author_id=actor.id,
            author_kind="human" if actor.user_type == "human" else "agent",
            message=(
                f"План ПСИ отправлен на переработку: заверенность снята, "
                f"{count} пунктов сброшены — M3 ждёт регистрации новой версии"
            ),
        )
    )
    await session.commit()
    return {"resetItems": count}


async def new_cycle(session: AsyncSession, story_code: str) -> int:
    """Идемпотентность: статусы пунктов сбрасываются в «не прогонялся»,
    протоколы (со снапшотами) не затираются (ФТ-ah-42)."""
    story = await _story(session, story_code)
    _, items = await _current_doc_and_items(session, story.id)
    count = 0
    for item in items:
        if item.kind == "item":
            item.status = "todo"
            item.psi_actual = None
            count += 1
    session.add(
        Chronicle(
            task_id=story.id,
            event_type="psi",
            author_kind="human",
            message=f"Новый цикл прогона: {count} пунктов сброшены",
        )
    )
    await session.commit()
    return count


async def get_document(session: AsyncSession, story_code: str) -> dict:
    story = await _story(session, story_code)
    docs = (
        (
            await session.execute(
                sa.select(PsiDocument)
                .where(PsiDocument.story_id == story.id)
                .order_by(PsiDocument.version)
            )
        )
        .scalars()
        .all()
    )
    _, items = await _current_doc_and_items(session, story.id)
    runs = (
        await session.execute(
            sa.select(PsiRun, PsiDocument.version)
            .join(PsiDocument, PsiDocument.id == PsiRun.psi_doc_id)
            .where(PsiDocument.story_id == story.id)
            .order_by(PsiRun.ran_at)
        )
    ).all()
    plan_ref = await psi_plan_ref_version(session, story.id)
    return {
        "stale": plan_ref is not None and plan_ref < story.ref_version,
        "refVersion": story.ref_version,
        "planRefVersion": plan_ref,
        "versions": [
            {"version": d.version, "authorId": str(d.author_id), "at": d.created_at.isoformat()}
            for d in docs
        ],
        "items": [
            {
                "position": i.position,
                "kind": i.kind,
                "text": i.text,
                "expected": i.psi_expected,
                "actual": i.psi_actual,
                "status": i.status,
                "bugTaskId": str(i.bug_task_id or ""),
            }
            for i in items
        ],
        "runs": [
            {
                "id": str(r.id),
                "version": d,
                "passed": r.passed,
                "failed": r.failed,
                "at": r.ran_at.isoformat(),
            }
            for r, d in runs
        ],
    }
