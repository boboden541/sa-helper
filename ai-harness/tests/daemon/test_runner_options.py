"""«Мост»: опции раннера агента — совместимость версий SDK и материализация папки (27.10.2026)."""

from __future__ import annotations

from pathlib import Path

from daemon.runner.agent_runner import RunRequest, _materialize_agent_dir, _options_kwargs


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


def test_materialize_agent_dir(tmp_path: Path):
    src = tmp_path / "claude"
    (src / "skills" / "demo").mkdir(parents=True)
    (src / "skills" / "demo" / "SKILL.md").write_text("# навык", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    n = _materialize_agent_dir(str(src), wt)
    assert (wt / ".claude" / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8") == "# навык"
    assert n == 1
