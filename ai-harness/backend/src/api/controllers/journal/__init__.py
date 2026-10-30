"""Контроллеры журнала: пакет по ресурсам (B2, расщепление journal.py).

Ресурсы: chronicle, psi, assistant, runs, streams, checklists, artifacts.
Контракт main.py сохранён: `from api.controllers import journal` → `journal.router`
с префиксом /api/v1 и тегом «journal» — пути URL не менялись.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.controllers.journal import (
    artifacts,
    assistant,
    checklists,
    chronicle,
    psi,
    runs,
    streams,
)

router = APIRouter(prefix="/api/v1", tags=["journal"])
router.include_router(chronicle.router)
router.include_router(psi.router)
router.include_router(assistant.router)
router.include_router(runs.router)
router.include_router(streams.router)
router.include_router(checklists.router)
router.include_router(artifacts.router)
