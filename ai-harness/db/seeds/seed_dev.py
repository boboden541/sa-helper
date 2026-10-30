"""Dev-наполнение БД: alias-колонки, пользователи, типы+flow, пресеты провайдеров, проект AH.

Идемпотентен: повторный запуск ничего не портит. Запуск: python -m db.seeds.seed_dev
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from database import dispose_engine, init_engine  # noqa: E402
from config import get_settings  # noqa: E402
from domain.model.validators import DomainError  # noqa: E402
from repository.models import AppSetting, Project, User  # noqa: Optional import below


async def _one(session, model, **filters):
    return (await session.execute(sa.select(model).filter_by(**filters))).scalar_one_or_none()


async def seed() -> None:
    from repository.models import Connection  # noqa: F401
    from db.seeds.flow_seed import ensure_alias_columns, seed_builtin_flows

    init_engine(get_settings().database_url)
    maker = None
    from database import get_sessionmaker

    maker = get_sessionmaker()
    async with maker() as session:
        # Alias-колонки и встроенные flow
        await ensure_alias_columns(session)
        await session.commit()

        system = await _one(session, User, name="system", is_service=True) or \
            (await session.execute(sa.insert(User).values(
                name="system", user_type="agent", is_service=True).returning(User))).scalar_one()
        await session.commit()

        await seed_builtin_flows(session, system)

        # Предустановленные агенты (ФТ-ah-62): при первом запуске система создаёт
        # базовый набор; скиллы — по постановке («Пользователи-агенты»)
        from argon2 import PasswordHasher  # noqa: F401
        from repository.models import AgentProfile

        PRESET_AGENTS = [
            ("Планировщик", "декомпозирует истории и задачи, готовит смарт-чеклист разработчика и контекст"),
            ("Разработчик", "ведёт TDD-разработку в ветке задачи task/<код>, ведёт чеклист, пишет отчёт"),
            ("Ревьюер-подготовщик", "готовит smart-чеклист ревьюера на статусе «Готово к ревью»"),
            ("Ревьюер", "составляет чеклист ревьюера, проверяет диф и отчёт, пишет отчёт о ревью"),
            ("Ревьюер-критик", "второе независимое ревью: строгость к краевым случаям и расхождениям"),
            ("Тестировщик-подготовщик", "готовит smart-чеклист тестирования на статусе «Готово к тестированию»"),
            ("Тестировщик", "составляет чеклист тестирования, проводит тестирование, пишет отчёт (для qa_task — в формате ПСИ)"),
            ("Аналитик", "собирает требования, проектирует концепты решения, пишет спецификацию"),
            ("ПСИ-составитель", "составляет документ ПСИ по истории: элементарное действие + ожидаемый результат"),
        ]
        # скилл на агента (решение владельца 29.10.2026 «под каждый статус — свой
        # скилл и свой пользователь»): подготовка ревью/тестирования вынесена в
        # отдельные скиллы и отдельных агентов
        # модели тяжёлых агентов (решение владельца 30.10.2026: оптимизация
        # расхода токенов — Разработчик/Ревьюер дают 87% входа конвейера;
        # пусто = дефолт SDK, что кратно дороже). Лёгкие подготовщики и ПСИ
        # остаются на дефолте.
        AGENT_MODELS = {
            "Разработчик": "claude-sonnet-5-5",
            "Ревьюер": "claude-sonnet-5-5",
        }
        AGENT_SKILLS = {
            "Планировщик": ["decomposer-methodology"],
            "Разработчик": ["developer-methodology"],
            "Ревьюер-подготовщик": ["review-preparation"],
            "Ревьюер": ["reviewer-methodology"],
            "Ревьюер-критик": ["reviewer-methodology"],
            "Тестировщик-подготовщик": ["qa-preparation"],
            "Тестировщик": ["qa-methodology"],
            "Аналитик": ["analyst-methodology"],
            "ПСИ-составитель": ["psi-methodology"],
        }
        # методологии агентов — скиллы реестра (developer/reviewer/qa/decomposer/psi/analyst-
        # methodology и preparation-скиллы), персона — имя + роль; свободного текста у агента
        # больше нет (решение владельца 27.10.2026)
        for name, role in PRESET_AGENTS:
            agent = await _one(session, User, name=name)
            if agent is None:
                agent = (await session.execute(
                    sa.insert(User).values(name=name, user_type="agent").returning(User))).scalar_one()
                await session.flush()
            profile = await _one(session, AgentProfile, user_id=agent.id)
            if profile is None:
                session.add(AgentProfile(
                    user_id=agent.id, role=role, is_preset=True,
                    model=AGENT_MODELS.get(name),
                    preset_source={"role": role, "skills": AGENT_SKILLS.get(name, [])},
                    skills=AGENT_SKILLS.get(name) or None))
            else:
                if not profile.skills:
                    profile.skills = AGENT_SKILLS.get(name) or None
                # модель проставляем и существующим пустым профилям (сид
                # идемпотентен), но заданную владельцем вручную не трогаем
                if profile.model is None and AGENT_MODELS.get(name):
                    profile.model = AGENT_MODELS[name]
        await session.commit()

        # Матрица назначений по умолчанию (ФТ-ah-31; заполнение «из коробки»):
        # типы без назначений получают пресет-раскладку по постановке. Ручные
        # настройки владельца не трогаем — только пустые типы.
        from repository.models import Assignment, TaskType

        DEFAULT_MATRIX = {
            "story": [("todo", "Планировщик", "replacement"),
                      ("in_testing", "ПСИ-составитель", "parallel"),
                      ("in_testing", "Тестировщик", "parallel")],
            "common_task": [("todo", "Планировщик", "replacement"),
                            ("in_progress", "Разработчик", "replacement"),
                            ("review_ready", "Ревьюер-подготовщик", "replacement"),
                            ("in_review", "Ревьюер", "parallel"),
                            ("in_review", "Ревьюер-критик", "parallel"),
                            ("qa_ready", "Тестировщик-подготовщик", "replacement"),
                            ("in_testing", "Тестировщик", "replacement")],
            "qa_task": [("todo", "Тестировщик-подготовщик", "replacement"),
                        ("in_testing", "Тестировщик", "replacement")],
            "bug": [("todo", "Планировщик", "replacement"),
                    ("in_progress", "Разработчик", "replacement"),
                    ("qa_ready", "Тестировщик-подготовщик", "replacement"),
                    ("in_testing", "Тестировщик", "replacement")],
            "analyse_task": [("todo", "Аналитик", "replacement"),
                             ("in_progress", "Аналитик", "replacement"),
                             ("review_ready", "Ревьюер-подготовщик", "replacement"),
                             ("in_review", "Ревьюер", "replacement")],
        }
        for type_key, rows in DEFAULT_MATRIX.items():
            ttype = (await session.execute(
                sa.select(TaskType).where(TaskType.key == type_key))).scalar_one_or_none()
            if ttype is None:
                continue
            has_any = (await session.execute(
                sa.select(sa.func.count()).select_from(Assignment)
                .where(Assignment.task_type_id == ttype.id))).scalar_one()
            if has_any:
                continue
            for position, (status_key, agent_name, mode) in enumerate(rows):
                agent = await _one(session, User, name=agent_name)
                if agent is None:
                    continue
                session.add(Assignment(task_type_id=ttype.id, status_key=status_key,
                                       user_id=agent.id, mode=mode, position=position))
        await session.commit()

        # Пользователи (этап 1: dev-вход без пароля, Argon2id — этап 4)
        from argon2 import PasswordHasher

        alexey = await _one(session, User, name="Алексей")
        if alexey is None:
            # Dev-пароль (вход по ФТ-ah-73 заработает в этапе 4)
            session.add(User(name="Алексей", user_type="human",
                             password_hash=PasswordHasher().hash("harness")))
        eve = await _one(session, User, name="Eve", is_chat_bot=True)
        if eve is None:
            session.add(User(name="Eve", user_type="agent", is_chat_bot=True))
        await session.commit()

        # Пресеты провайдеров (ФТ-ah-59; как PROV_PRESETS макета)
        from repository.models import ProviderPreset

        PROVIDER_PRESETS = [
            ("Anthropic", "anthropic", "https://api.anthropic.com"),
            ("OpenAI", "openai", "https://api.openai.com/v1"),
            ("OpenRouter", "openai", "https://openrouter.ai/api/v1"),
            ("Groq", "openai", "https://api.groq.com/openai/v1"),
            ("vLLM (локальный)", "openai", "http://localhost:8000/v1"),
            ("Ollama", "openai", "http://localhost:11434/v1"),
        ]
        for name, proto, url in PROVIDER_PRESETS:
            if await _one(session, ProviderPreset, name=name) is None:
                session.add(ProviderPreset(name=name, protocol=proto, base_url=url))
        await session.commit()

        # Настройки автомата по умолчанию (ФТ-ah-33…36, ФТ-ah-44)
        defaults = {
            "daemon.tick_seconds": "30",
            "daemon.timeout_start_seconds": "300",
            "daemon.timeout_work_seconds": "1800",
            "daemon.max_attempts": "3",
            "daemon.retry_pauses_minutes": "1,5,15",
            "rework.cycle_limit": "5",
            "psi.retention_days": "90",
            "eve.free_mode": "false",
        }
        for key, value in defaults.items():
            if await _one(session, AppSetting, key=key) is None:
                session.add(AppSetting(key=key, value=value))
        await session.commit()

        # Проект AH с demo-репозиторием для git-контура
        project = await _one(session, Project, mnemonic="AH")
        if project is None:
            demo_repo = Path(__file__).resolve().parents[2] / ".harness" / "demo-repo"
            demo_repo.mkdir(parents=True, exist_ok=True)
            if not (demo_repo / ".git").exists():
                subprocess.run(["git", "init", "-b", "main", str(demo_repo)],
                               check=True, capture_output=True)
                (demo_repo / "README.md").write_text("# Demo repo (AI-Harness)\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(demo_repo), "add", "."], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(demo_repo), "commit", "-m", "init"],
                               check=True, capture_output=True)
            session.add(Project(
                name="AI Harness", mnemonic="AH", path=str(demo_repo), base_branch="main",
                description="Демо-проект конвейера",
            ))
            await session.commit()

    await dispose_engine()
    print("Seed OK")


if __name__ == "__main__":
    asyncio.run(seed())
