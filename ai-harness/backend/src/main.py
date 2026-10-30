"""Точка входа backend'а: FastAPI-приложение (uvicorn main:app)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.errors import ApiError, api_error_handler, domain_error_handler
from domain.model.validators import DomainError
from database import dispose_engine, get_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database import get_engine

    get_engine()  # инициализация по конфигу
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="AI-Harness", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(DomainError, domain_error_handler)
    from api.controllers import auth, journal, settings, tasks, transitions

    @app.get("/api/v1/healthz", include_in_schema=False)
    async def healthz():
        # без обращения к БД: живость процесса для docker healthcheck
        return {"status": "ok"}

    app.include_router(tasks.router)
    app.include_router(transitions.router)
    app.include_router(auth.router)
    app.include_router(settings.router)
    app.include_router(journal.router)
    return app


app = create_app()
