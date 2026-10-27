"""«Мост»: опции раннера агента — совместимость версий SDK и подключение папки инструментов (27.10.2026)."""

from __future__ import annotations

from pathlib import Path

from daemon.runner.agent_runner import RunRequest, _link_agent_dir, _options_kwargs


def _req(**kw) -> RunRequest:
    return RunRequest(task_code="AH-1", skill_md="s", context_md="c", **kw)


def test_options_new_sdk_keeps_all():
    fields = {"cwd", "allowed_tools", "permission_mode", "max_turns",
              "model", "mcp_servers", "setting_sources"}
    kw = _options_kwargs(_req(model="m1", mcp_servers={"g": {"url": "http://x"}},
                              agent_dir="/tmp/agents"), fields)
    assert kw["model"] == "m1"
    assert kw["mcp_servers"] == {"g": {"url": "http://x"}}
    assert kw["setting_sources"] == ["project"]
    assert kw["permission_mode"] == "acceptEdits"


def test_options_old_sdk_drops_unknown():
    """Старый SDK без model/setting_sources — новые опции тихо отбрасываются, прогон не падает."""
    kw = _options_kwargs(_req(model="m1", agent_dir="/tmp/agents"),
                         {"cwd", "allowed_tools", "permission_mode", "max_turns"})
    assert set(kw) == {"cwd", "allowed_tools", "permission_mode", "max_turns"}


def test_link_agent_dir(tmp_path: Path):
    src = tmp_path / "claude"
    (src / "skills").mkdir(parents=True)
    (src / "skills" / "SKILL.md").write_text("# навык", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    mode = _link_agent_dir(str(src), wt)
    link = wt / ".claude"
    assert link.is_symlink()
    assert (link / "skills" / "SKILL.md").read_text(encoding="utf-8") == "# навык"
    assert mode == "симлинк"
    # живое отслеживание: правка источника видна агенту без пересоздания
    (src / "skills" / "SKILL.md").write_text("# навык v2", encoding="utf-8")
    assert (link / "skills" / "SKILL.md").read_text(encoding="utf-8") == "# навык v2"


def test_link_replaces_old_copy(tmp_path: Path):
    src = tmp_path / "claude"
    src.mkdir()
    (src / "a.md").write_text("x", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".claude").mkdir()
    (wt / ".claude" / "old.md").write_text("копия от прежней версии", encoding="utf-8")
    _link_agent_dir(str(src), wt)
    assert (wt / ".claude").is_symlink()
    assert not (wt / ".claude" / "old.md").exists()


def test_exclude_written_for_worktree(tmp_path: Path):
    """В linked worktree .git — файл «gitdir: …»; исключение пишется в gitdir/info/exclude."""
    src = tmp_path / "claude"
    src.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    gitdir = tmp_path / "main" / ".git" / "worktrees" / "wt1"
    gitdir.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    _link_agent_dir(str(src), wt)
    assert ".claude/" in (gitdir / "info" / "exclude").read_text(encoding="utf-8")
