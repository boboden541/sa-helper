"""Контроллеры настроек: пакет по ресурсам (B1, расщепление settings.py).

Ресурсы: flow, connections, agents, tools, projects, pipeline.
Контракт main.py сохранён: `from api.controllers import settings` → `settings.router`
с префиксом /api/v1 и тегом «settings» — пути URL не менялись.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.controllers.settings import agents, connections, flow, pipeline, projects, tools

router = APIRouter(prefix="/api/v1", tags=["settings"])
router.include_router(flow.router)
router.include_router(connections.router)
router.include_router(agents.router)
router.include_router(tools.router)
router.include_router(projects.router)
router.include_router(pipeline.router)
