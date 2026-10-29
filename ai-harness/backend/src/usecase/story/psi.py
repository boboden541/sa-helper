"""ПСИ: документ с версиями, прогоны со снапшотом пунктов, баги (СТ §4.5.2).

Каждая версия документа автоматически сохраняется файлом по пути истории
(task.psi_path, «Путь сохранения ПСИ» — например …/FNR/FNR_8/psi.md);
путь не задан — стандартный <путь проекта>/.harness/psi/<код истории>/psi.md
(решение владельца 27.10.2026)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.validators import DomainError
from repository.models import (
    Checklist, ChecklistItem, Chronicle, PsiDocument, PsiRun, PsiRunItem, Project, Task, User,
)


async def _story(session: AsyncSession, code: str) -> Task:
    story = (await session.execute(
        sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if story is None:
        raise DomainError(f"История {code} не найдена")
    return story


def render_psi_md(story: Task, version: int, sections: list[dict],
                  preamble_md: str | None = None) -> str:
    """Рендер документа в канон идеального ПСИ (пример — FNR_8/psi.md)."""
    today = datetime.now(timezone.utc).date().isoformat()
    lines = [f"# Процедура приёмо-сдаточных испытаний (ПСИ): {story.title} ({story.code})",
             "",
             "**Назначение.** Этот документ — пошаговый сценарий проверки реализованного "
             "функционала. Каждый пункт — пара «Действие → Ожидаемый результат»: выполняете "
             "действие, сверяете факт с ожиданием, ставите вердикт ✓/✗.",
             f"**Дата документа:** {today}. **Версия документа:** v{version}.", ""]
    if preamble_md and preamble_md.strip():
        lines += [preamble_md.strip(), ""]
    position = 0
    for section in sections:
        lines += [f"## {section.get('heading', 'Раздел')}", ""]
        for item in section.get("items", []):
            position += 1
            lines += [f"### П.{position} {item.get('action', '')}", "",
                      f"**Ожидаемый результат:** {item.get('expected', '')}", ""]
    return "\n".join(lines)


async def save_psi_file(session: AsyncSession, story: Task, md: str) -> str:
    """Пишет psi.md по пути истории (или в стандартное место); возвращает путь как на компьютере."""
    import os

    from infrastructure.paths import host_to_container

    user_path = (story.psi_path or "") .strip() if story.psi_path else ""
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


async def create_version(session: AsyncSession, story_code: str, author: User,
                         sections: list[dict], preamble_md: str | None = None) -> int:
    """sections: [{"heading": str, "items": [{"action": str, "expected": str}]}].
    Пункт ПСИ — строка чеклиста особого типа kind='psi' (ФТ-ah-39).
    Версия сохраняется файлом по пути истории (psi_path)."""
    story = await _story(session, story_code)
    version = (await session.execute(
        sa.select(sa.func.coalesce(sa.func.max(PsiDocument.version), 0))
        .where(PsiDocument.story_id == story.id))).scalar_one() + 1
    doc = PsiDocument(story_id=story.id, version=version, author_id=author.id)
    session.add(doc)
    await session.flush()

    chk = Checklist(task_id=story.id, kind="psi")
    session.add(chk)
    await session.flush()
    position = 0
    items_count = 0
    for section in sections:
        session.add(ChecklistItem(checklist_id=chk.id, position=position, kind="heading",
                                  level=1, text=section.get("heading", "Раздел")))
        position += 1
        for item in section.get("items", []):
            session.add(ChecklistItem(
                checklist_id=chk.id, position=position, kind="item",
                text=item.get("action", ""), status="todo",
                psi_expected=item.get("expected", "")))
            position += 1
            items_count += 1
    session.add(Chronicle(task_id=story.id, event_type="psi",
                          author_id=author.id, author_kind="agent" if author.user_type == "agent" else "human",
                          message=f"Составлен ПСИ v{version} ({items_count} пунктов)"))
    await session.commit()

    # файл psi.md — в папку назначения (например, sa_documentation/FNR/FNR_<N>/psi.md)
    try:
        md = render_psi_md(story, version, sections, preamble_md)
        saved_to = await save_psi_file(session, story, md)
        session.add(Chronicle(task_id=story.id, event_type="psi", author_id=author.id,
                              author_kind="auto", rule_code="PSI_FILE",
                              message=f"Файл ПСИ v{version} сохранён: {saved_to}"))
        await session.commit()
    except (OSError, DomainError) as err:
        session.add(Chronicle(task_id=story.id, event_type="psi", author_id=author.id,
                              author_kind="auto", rule_code="PSI_FILE",
                              message=f"Файл ПСИ v{version} НЕ сохранён: {err}"))
        await session.commit()
    return version


async def _current_doc_and_items(session: AsyncSession, story_id):
    doc = (await session.execute(
        sa.select(PsiDocument).where(PsiDocument.story_id == story_id)
        .order_by(PsiDocument.version.desc()).limit(1))).scalar_one_or_none()
    if doc is None:
        raise DomainError("У истории нет документа ПСИ")
    chk = (await session.execute(
        sa.select(Checklist).where(Checklist.task_id == story_id, Checklist.kind == "psi")
    )).scalar_one_or_none()
    items = (await session.execute(
        sa.select(ChecklistItem).where(ChecklistItem.checklist_id == chk.id)
        .order_by(ChecklistItem.position))).scalars().all() if chk else []
    return doc, items


async def run_psi(session: AsyncSession, story_code: str, runner: User,
                  results: list[dict]) -> dict:
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
        session.add(PsiRunItem(
            psi_run_id=run.id, item_id=item.id, position=position,
            item_text=item.text, expected=item.psi_expected,
            status=status, actual=r.get("actual", "")))
        if r.get("passed"):
            passed += 1
        else:
            failed += 1
            # дубль бага не создаётся: незакрытый баг пункта уже есть → предложение нет
            if item.bug_task_id is None:
                bug_proposals.append({
                    "position": position, "action": item.text,
                    "expected": item.psi_expected or "", "actual": r.get("actual", "")})

    run.passed = passed
    run.failed = failed
    session.add(Chronicle(
        task_id=story.id, event_type="psi", author_id=runner.id,
        author_kind="agent" if runner.user_type == "agent" else "human",
        message=f"Прогон ПСИ v{doc.version}: {passed} пройдено, {failed} не пройдено"))
    await session.commit()
    return {"version": doc.version, "passed": passed, "failed": failed,
            "bugProposals": bug_proposals, "runId": str(run.id)}


async def link_bug(session: AsyncSession, story_code: str, position: int,
                   bug_code: str) -> None:
    """Связывает пункт ПСИ с заведённым багом (идемпотентность цикла, ФТ-ah-42)."""
    story = await _story(session, story_code)
    _, items = await _current_doc_and_items(session, story.id)
    item = next((i for i in items if i.kind == "item" and i.position == position), None)
    if item is None:
        raise DomainError(f"Пункт {position} не найден")
    bug = (await session.execute(
        sa.select(Task).where(Task.code == bug_code.upper()))).scalar_one_or_none()
    if bug is None:
        raise DomainError(f"Баг {bug_code} не найден")
    item.bug_task_id = bug.id
    session.add(Chronicle(task_id=story.id, event_type="bug", author_kind="human",
                          message=f"Пункт {position} ПСИ связан с багом {bug.code}"))
    await session.commit()
    # M4 (ФТ-ah-36): «все баги заведены с привязкой к истории» → blocked (из in testing)
    _, items_now = await _current_doc_and_items(session, story.id)
    failed_items = [i for i in items_now if i.kind == "item" and i.status == "failed"]
    if (failed_items and all(i.bug_task_id for i in failed_items)
            and story.status_key == "in_testing"):
        from usecase.story.mirror import apply_m4

        await apply_m4(session, story)


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
    session.add(Chronicle(task_id=story.id, event_type="psi", author_kind="human",
                          message=f"Новый цикл прогона: {count} пунктов сброшены"))
    await session.commit()
    return count


async def get_document(session: AsyncSession, story_code: str) -> dict:
    story = await _story(session, story_code)
    docs = (await session.execute(
        sa.select(PsiDocument).where(PsiDocument.story_id == story.id)
        .order_by(PsiDocument.version))).scalars().all()
    _, items = await _current_doc_and_items(session, story.id)
    runs = (await session.execute(
        sa.select(PsiRun, PsiDocument.version)
        .join(PsiDocument, PsiDocument.id == PsiRun.psi_doc_id)
        .where(PsiDocument.story_id == story.id)
        .order_by(PsiRun.ran_at))).all()
    return {
        "versions": [{"version": d.version, "authorId": str(d.author_id),
                      "at": d.created_at.isoformat()} for d in docs],
        "items": [{"position": i.position, "kind": i.kind, "text": i.text,
                   "expected": i.psi_expected, "actual": i.psi_actual,
                   "status": i.status, "bugTaskId": str(i.bug_task_id or "")}
                  for i in items],
        "runs": [{"id": str(r.id), "version": d, "passed": r.passed,
                  "failed": r.failed, "at": r.ran_at.isoformat()} for r, d in runs]
    }
