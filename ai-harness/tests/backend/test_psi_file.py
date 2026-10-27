"""Файл ПСИ: рендер и сохранение по psi_path истории (решение владельца 27.10.2026)."""

from __future__ import annotations

SECTIONS = [{"heading": "Г1. Проверки входа",
             "items": [{"action": "Открыть список черновиков",
                        "expected": "Список открывается, есть строка «Тестовое событие»"}]}]
PREAMBLE = ("**Назначение.** Проверка входа.\n\n"
            "## Словарик\n\n| Термин | Что это |\n|---|---|\n| Черновик | Запись до публикации |")


async def _mk_story(client, **kw):
    payload = {"projectId": "AH", "type": "story", "title": "ПСИ-тест истории",
               "priority": "high", "authorTag": "by_human"}
    payload.update(kw)
    r = await client.post("/api/v1/tasks", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["code"]


async def test_psi_file_to_explicit_path(client, tmp_path):
    target = tmp_path / "FNR" / "FNR_8" / "psi.md"
    code = await _mk_story(client, psiPath=str(target))
    r = await client.post(f"/api/v1/stories/{code}/psi",
                          json={"sections": SECTIONS, "preambleMd": PREAMBLE})
    assert r.status_code == 200, r.text
    assert target.exists(), "файл psi.md не записан по psi_path истории"
    text = target.read_text(encoding="utf-8")
    assert code in text and "Ожидаемый результат" in text and "Словарик" in text
    assert "П.1 " in text  # нумерация пунктов


async def test_psi_file_default_path_under_project(client, tmp_path):
    # собственный проект с путём во tmp — дефолтный путь считается от пути проекта
    r = await client.post("/api/v1/projects", json={
        "name": "ПСИ-проект", "mnemonic": "PSIF", "path": str(tmp_path / "proj"),
        "baseBranch": "main"})
    assert r.status_code == 200, r.text
    code = await _mk_story(client, projectId="PSIF")
    r2 = await client.post(f"/api/v1/stories/{code}/psi", json={"sections": SECTIONS})
    assert r2.status_code == 200, r2.text
    default_file = tmp_path / "proj" / ".harness" / "psi" / code / "psi.md"
    assert default_file.exists(), f"нет файла по умолчанию: {default_file}"
    assert "Ожидаемый результат" in default_file.read_text(encoding="utf-8")
