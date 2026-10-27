"""Реестр инструментов (вариант 4): скан, живой синк, чтение. Файлы только читаются."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from repository.models import AppSetting

KEY = "agents.tools_dir"


async def _set_dir(session, path) -> None:
    row = (await session.execute(sa.select(AppSetting).where(AppSetting.key == KEY))).scalar_one_or_none()
    if row:
        row.value = str(path)
    else:
        session.add(AppSetting(key=KEY, value=str(path)))
    await session.commit()


def _mk_tools(tmp_path):
    root = tmp_path / "tools"
    (root / "commands").mkdir(parents=True)
    (root / "skills" / "demo").mkdir(parents=True)
    (root / "commands" / "hello.md").write_text(
        '---\ndescription: "Сказать привет"\n---\n# hello\nТело команды', encoding="utf-8")
    (root / "skills" / "demo" / "SKILL.md").write_text("# Демо-навык\nДелает демо", encoding="utf-8")
    return root


async def test_tools_scan_list_read(client, session, tmp_path):
    from usecase.settings import tools as tools_uc

    saved = (await session.execute(sa.select(AppSetting.value).where(AppSetting.key == KEY))).scalar_one_or_none()
    root = _mk_tools(tmp_path)
    await _set_dir(session, root)
    try:
        s1 = await tools_uc.scan(session)
        assert s1["added"] == 2 and s1["commands"] == 1 and s1["skills"] == 1

        listing = await tools_uc.list_artifacts(session)
        assert listing["drift"] == 0 and listing["counts"]["commands"] == 1

        (root / "commands" / "hello.md").write_text("# hello v2", encoding="utf-8")
        st = {i["name"]: i["status"] for i in
              (await tools_uc.list_artifacts(session))["items"]}
        assert st["hello"] == "changed"

        (root / "commands" / "extra.md").write_text("# extra", encoding="utf-8")
        listing3 = await tools_uc.list_artifacts(session)
        assert any(n["name"] == "extra" for n in listing3["newOnDisk"])

        s2 = await tools_uc.scan(session)
        assert s2["updated"] == 1 and s2["added"] == 1

        art = await tools_uc.read_artifact(session, "command", "hello")
        assert art["content"].startswith("# hello v2") and art["changed"] is False

        (root / "skills" / "demo" / "SKILL.md").unlink()
        st4 = {i["name"]: i["status"] for i in
               (await tools_uc.list_artifacts(session))["items"]}
        assert st4["demo"] == "missing"
        s3 = await tools_uc.scan(session)
        assert s3["removed"] == 1
    finally:
        await _set_dir(session, saved or "")


async def test_tools_api(client, session, tmp_path):
    saved = (await session.execute(sa.select(AppSetting.value).where(AppSetting.key == KEY))).scalar_one_or_none()
    root = _mk_tools(tmp_path)
    from repository.models import ToolArtifact

    await session.execute(sa.delete(ToolArtifact))  # реестр предыдущего теста не должен переживать
    await session.commit()
    await _set_dir(session, root)
    try:
        r = await client.post("/api/v1/tools/scan")
        assert r.status_code == 200 and r.json()["added"] == 2

        r2 = await client.get("/api/v1/tools")
        assert r2.status_code == 200 and r2.json()["counts"]["commands"] == 1
        assert r2.json()["items"][0]["description"] == "Сказать привет"

        r3 = await client.get("/api/v1/tools/skill/demo")
        assert r3.status_code == 200 and "Демо-навык" in r3.json()["content"]

        r4 = await client.get("/api/v1/tools/skill/нет-такого")
        assert r4.status_code == 400
    finally:
        await _set_dir(session, saved or "")


# ---------- обратная запись (два входа: файл и веб) ----------

async def test_tools_write_roundtrip(client, session, tmp_path):
    from domain.model.validators import DomainError

    from usecase.settings import tools as tools_uc

    saved = (await session.execute(sa.select(AppSetting.value).where(AppSetting.key == KEY))).scalar_one_or_none()
    root = _mk_tools(tmp_path)
    from repository.models import ToolArtifact

    await session.execute(sa.delete(ToolArtifact))
    await session.commit()
    await _set_dir(session, root)
    try:
        await tools_uc.scan(session)
        who = (await session.execute(sa.text('SELECT id FROM "user" WHERE user_type = :t'),
                                     {"t": "human"})).scalar_one()
        res = await tools_uc.write_artifact(session, who, "command", "hello", "# hello v3\nОбновлено")
        assert res["ok"] is True
        assert (root / "commands" / "hello.md").read_text(encoding="utf-8").startswith("# hello v3")

        art = await tools_uc.read_artifact(session, "command", "hello")
        assert art["content"].startswith("# hello v3") and art["changed"] is False

        # конфликт: файл изменился на диске после скана — запись отклоняется
        (root / "commands" / "hello.md").write_text("# правка с диска", encoding="utf-8")
        with pytest.raises(DomainError, match="изменился на диске"):
            await tools_uc.write_artifact(session, who, "command", "hello", "# затрём?")

        # пустая правка отклоняется
        with pytest.raises(DomainError, match="Пустая"):
            await tools_uc.write_artifact(session, who, "command", "hello", "  \n")
    finally:
        await _set_dir(session, saved or "")


# ---------- назначение скиллов агентам ----------

async def test_agent_skills_assign(client, session, tmp_path):
    from repository.models import AgentProfile, ToolArtifact

    from usecase.settings.agents import create_agent, update_agent

    saved = (await session.execute(sa.select(AppSetting.value).where(AppSetting.key == KEY))).scalar_one_or_none()
    root = _mk_tools(tmp_path)
    await session.execute(sa.delete(ToolArtifact))
    await session.commit()
    await _set_dir(session, root)
    try:
        from usecase.settings import tools as tools_uc

        await tools_uc.scan(session)
        user = await create_agent(session, {"name": "Скилловый", "role": "тест",
                                            "skills": ["demo"]})
        p = (await session.execute(sa.select(AgentProfile)
             .where(AgentProfile.user_id == user.id))).scalar_one()
        assert p.skills == ["demo"]

        with pytest.raises(Exception, match="нет в реестре"):
            await update_agent(session, user.id, {"skills": ["нет-такого"]})

        await update_agent(session, user.id, {"skills": []})
        p2 = (await session.execute(sa.select(AgentProfile)
              .where(AgentProfile.user_id == user.id))).scalar_one()
        assert p2.skills is None
    finally:
        await _set_dir(session, saved or "")
