"""Реестр инструментов: глобальная папка (.claude SA-Helper) → карточки команд и скиллов.

Вариант 4 (решение владельца 27.10.2026): файлы ТОЛЬКО читаются и отслеживаются —
импорт ничего не перемещает и не изменяет (судьба прежних /impl-* решается отдельной
задачей владельца)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.validators import DomainError
from repository.models import AppSetting, ToolArtifact

TOOLS_KEY = "agents.tools_dir"


async def _global_dir(session: AsyncSession) -> tuple[str, Path]:
    """Возвращает (путь как на компьютере пользователя, путь в координатах контейнера)."""
    """Глобальная папка в координатах машины, где реально работает backend."""
    import os

    from infrastructure.paths import host_to_container

    root = (await session.execute(sa.select(AppSetting.value).where(AppSetting.key == TOOLS_KEY))
            ).scalar_one_or_none() or ""
    if not root.strip():
        raise DomainError("Глобальная папка инструментов не задана — укажите её во вкладке «Агенты и матрица»")
    p = Path(host_to_container(root))
    if not os.path.isdir(p):
        raise DomainError(f"Глобальная папка инструментов недоступна: {root}")
    return root, p


_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_DESC_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE)
_HEAD_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _parse(text: str) -> str:
    """Описание артефакта: frontmatter description, иначе первый заголовок «# …»."""
    fm = _FRONT_RE.match(text)
    if fm:
        m = _DESC_RE.search(fm.group(1))
        if m:
            return m.group(1).strip().strip('"')[:200]
    m = _HEAD_RE.search(text)
    return (m.group(1).strip() if m else "")[:200]


def _scan_dir(root: Path) -> list[dict]:
    """commands/*.md и skills/*/SKILL.md — только чтение, без изменения файлов."""
    out: list[dict] = []
    cmds = root / "commands"
    if cmds.is_dir():
        for f in sorted(cmds.glob("*.md")):
            data = f.read_bytes()
            out.append({"kind": "command", "name": f.stem,
                        "rel_path": f"commands/{f.name}",
                        "description": _parse(data.decode("utf-8", "replace")),
                        "content_hash": hashlib.sha256(data).hexdigest(),
                        "size_bytes": len(data)})
    skills = root / "skills"
    if skills.is_dir():
        for d in sorted(x for x in skills.iterdir() if x.is_dir()):
            sk = d / "SKILL.md"
            if sk.is_file():
                data = sk.read_bytes()
                out.append({"kind": "skill", "name": d.name,
                            "rel_path": f"skills/{d.name}/SKILL.md",
                            "description": _parse(data.decode("utf-8", "replace")),
                            "content_hash": hashlib.sha256(data).hexdigest(),
                            "size_bytes": len(data)})
    return out


async def scan(session: AsyncSession) -> dict:
    """Синхронизирует реестр с диском: добавить/обновить/удалить. Файлы не трогаются."""
    _user_root, root = await _global_dir(session)
    found = {(a["kind"], a["name"]): a for a in _scan_dir(root)}
    rows = (await session.execute(sa.select(ToolArtifact))).scalars().all()
    added = updated = removed = 0
    by_key = {(r.kind, r.name): r for r in rows}
    for key, art in found.items():
        row = by_key.get(key)
        if row is None:
            session.add(ToolArtifact(kind=art["kind"], name=art["name"],
                                     rel_path=art["rel_path"],
                                     description=art["description"],
                                     content_hash=art["content_hash"],
                                     size_bytes=art["size_bytes"]))
            added += 1
        elif row.content_hash != art["content_hash"]:
            row.content_hash = art["content_hash"]
            row.description = art["description"]
            row.size_bytes = art["size_bytes"]
            row.rel_path = art["rel_path"]
            updated += 1
    for key, row in by_key.items():
        if key not in found:
            await session.delete(row)
            removed += 1
    await session.commit()
    return {"added": added, "updated": updated, "removed": removed, "total": len(found),
            "commands": sum(1 for k in found if k[0] == "command"),
            "skills": sum(1 for k in found if k[0] == "skill")}


async def list_artifacts(session: AsyncSession) -> dict:
    """Реестр + живой статус синка: сверка хешей с диском без записи в БД."""
    user_root, root = await _global_dir(session)
    found = {(a["kind"], a["name"]): a for a in _scan_dir(root)}
    rows = (await session.execute(
        sa.select(ToolArtifact).order_by(ToolArtifact.kind, ToolArtifact.name))).scalars().all()
    items: list[dict] = []
    drift = 0
    seen: set[tuple[str, str]] = set()
    for r in rows:
        key = (r.kind, r.name)
        seen.add(key)
        art = found.get(key)
        status = "ok" if art and art["content_hash"] == r.content_hash else (
            "changed" if art else "missing")
        if status != "ok":
            drift += 1
        items.append({"kind": r.kind, "name": r.name, "description": r.description,
                      "hash": r.content_hash[:7], "status": status,
                      "sizeBytes": r.size_bytes, "relPath": r.rel_path})
    new_on_disk = [a for k, a in found.items() if k not in seen]
    drift += len(new_on_disk)
    return {"toolsDir": user_root, "drift": drift,
            "counts": {"commands": sum(1 for i in items if i["kind"] == "command"),
                       "skills": sum(1 for i in items if i["kind"] == "skill")},
            "items": items,
            "newOnDisk": [{"kind": a["kind"], "name": a["name"]} for a in new_on_disk]}


async def read_artifact(session: AsyncSession, kind: str, name: str) -> dict:
    """Содержимое файла артефакта + флаг «изменился на диске после скана»."""
    _user_root, root = await _global_dir(session)
    row = (await session.execute(sa.select(ToolArtifact).where(
        ToolArtifact.kind == kind, ToolArtifact.name == name))).scalar_one_or_none()
    if row is None:
        raise DomainError("Артефакт не найден в реестре — просканируйте папку")
    path = root / row.rel_path
    if not path.is_file():
        raise DomainError(f"Файл исчез с диска: {row.rel_path}")
    data = path.read_bytes()
    return {"kind": kind, "name": name, "relPath": row.rel_path,
            "description": row.description, "content": data.decode("utf-8", "replace"),
            "changed": hashlib.sha256(data).hexdigest() != row.content_hash}


async def write_artifact(session: AsyncSession, who_id, kind: str, name: str, content: str) -> dict:
    """Обратная запись (вариант 4: два входа — файл и веб): правка карточки из UI пишет файл.

    Оптимистическая блокировка: если файл изменился на диске после последнего скана —
    отказ, чтобы не затереть чужие правки. Пустая правка отклоняется."""
    if not content.strip():
        raise DomainError("Пустая правка отклонена", field="content")
    _user_root, root = await _global_dir(session)
    row = (await session.execute(sa.select(ToolArtifact).where(
        ToolArtifact.kind == kind, ToolArtifact.name == name))).scalar_one_or_none()
    if row is None:
        raise DomainError("Артефакт не найден в реестре — просканируйте папку")
    path = root / row.rel_path
    if not path.is_file():
        raise DomainError(f"Файл исчез с диска: {row.rel_path}")
    current = hashlib.sha256(path.read_bytes()).hexdigest()
    if current != row.content_hash:
        raise DomainError(f"Файл изменился на диске после последнего скана ({row.rel_path}) — "
                          "просканируйте реестр, откройте карточку заново; правка не записана, "
                          "чтобы не затереть чужие изменения")
    data = content.encode("utf-8")
    path.write_bytes(data)
    row.content_hash = hashlib.sha256(data).hexdigest()
    row.size_bytes = len(data)
    row.description = _parse(content)
    from usecase.journal.settings_journal import record_and_commit

    await record_and_commit(session, who_id, "tools",
                            f"Правка файла инструментария: {row.rel_path}",
                            [{"field": row.rel_path, "old": current[:7], "new": row.content_hash[:7]}])
    return {"ok": True, "hash": row.content_hash[:7]}
