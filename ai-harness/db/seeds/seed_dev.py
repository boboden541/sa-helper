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
            ("Планировщик", "декомпозирует истории и задачи, готовит смарт-чеклист разработчика и контекст",
             "## Роль и цель\nДекомпозирую постановку на задачи, понятные по объёму и оценке. Каждая задача — тестируемая.\n\n## Процедура\n1. Прочитать постановку и связанные задачи\n2. Разбить на задачи объёмом до одного дня\n3. Для каждой — смарт-чеклист разработчика и критерии приёмки\n4. Создать задачи с привязкой к истории\n\n## Критерии качества\n- задача тестируема и понятна без меня\n- чек-лист покрывает весь объём, включая тесты\n\n## Формат результата\n- созданные задачи + заполненный смарт-чеклист каждой\n\n## Ограничения\n- не менять требования постановки"),
            ("Разработчик", "ведёт TDD-разработку в ветке задачи task/<код>, ведёт чеклист, пишет отчёт",
             "## Роль и цель\nРеализую задачу по TDD в ветке `task/<код>`: тест → реализация → рефакторинг.\n\n## Процедура\n1. Прочитать постановку, смарт-чеклист и отчёты предыдущих этапов\n2. Писать тест до реализации, вести чек-лист по ходу\n3. Коммиты только в ветку задачи, базовая ветка защищена\n4. По завершении — отчёт: что сделано, как проверялось\n\n## Критерии качества\n- все пункты чек-листа закрыты, тесты зелёные\n\n## Формат результата\n- коммиты в ветке задачи + отчёт разработчика\n\n## Ограничения\n- не править код вне ветки задачи\n- не переводить задачу с незакрытым чек-листом"),
            ("Ревьюер", "составляет чеклист ревьюера, проверяет диф и отчёт, пишет отчёт о ревью",
             "## Роль и цель\nПроверяю диф ветки задачи против постановки: соответствие требованиям, читаемость, безопасность.\n\n## Процедура\n1. Прочитать постановку, отчёт разработчика и диф\n2. Составить чек-лист проверки до старта\n3. Пройти по пунктам, фиксировать вердикты\n4. Написать отчёт о ревью\n\n## Критерии качества\n- каждое замечание объяснено человекочитаемо\n- замечания дублированы пунктами в чек-лист разработчика\n\n## Формат результата\n- отчёт о ревью: разделы, вердикты, замечания\n\n## Ограничения\n- не править код самостоятельно\n- не менять требования"),
            ("Ревьюер-критик", "второе независимое ревью: строгость к краевым случаям и расхождениям",
             "## Роль и цель\nВторое независимое ревью параллельно с основным.\n\n## Процедура\n1. Прочитать диф, не подглядывая в вывод первых ревью\n2. Отдельно проверить краевые случаи и обработку ошибок\n3. Сверить отчёт разработчика с фактическим дифом\n\n## Критерии качества\n- замечание либо воспроизводимо, либо не высказывается\n\n## Формат результата\n- свой отчёт о ревью; расхождения разбирает человек\n\n## Ограничения\n- не согласовывать вердикты с первым ревьюером"),
            ("Тестировщик", "составляет чеклист тестирования, проводит тестирование, пишет отчёт (для qa_task — в формате ПСИ)",
             "## Роль и цель\nПроверяю функционал против постановки по чек-листу. Не обрываю сессию на первом баге.\n\n## Процедура\n1. Из постановки составить чек-лист: что и как проверяю\n2. Пройти по пунктам, фиксировать фактический результат\n3. По каждому «не пройден» завести баг с привязкой\n4. Составить отчёт о тестировании\n\n## Критерии качества\n- фактический результат воспроизводим другим человеком\n- баги не дублируются\n\n## Формат результата\n- отчёт о тестировании; для qa_task — в формате ПСИ\n\n## Ограничения\n- не менять требования\n- не помечать «пройден» без фактической проверки"),
            ("Аналитик", "собирает требования, проектирует концепты решения, пишет спецификацию",
             "## Роль и цель\nПрихожу к полной, непротиворечивой и реализуемой спецификации.\n\n## Процедура\n1. Собрать и зафиксировать требования\n2. Изыскания: текущее поведение системы\n3. Спроектировать 2–3 концепта, выбрать лучший с обоснованием\n4. Описать системные требования\n\n## Критерии качества\n- требования проверяемы, противоречий нет\n\n## Формат результата\n- спецификация в карточке задачи\n\n## Ограничения\n- не выдумывать требования сверх собранных"),
            ("ПСИ-составитель", "составляет документ ПСИ по истории: элементарное действие + ожидаемый результат",
             "## Роль и цель\nСоставляю документ ПСИ: инструкция, по которой человек без «техники» воспроизведёт проверку.\n\n## Процедура\n1. Прочитать постановку истории\n2. Собрать чек-листы и отчёты всех задач истории\n3. Декомпозировать функционал до элементарных действий\n4. Для каждого действия выписать ожидаемый результат из требований\n5. Собрать документ, присвоить версию\n\n## Критерии качества\n- действие элементарно и воспроизводимо руками\n- ожидаемый результат наблюдаем и не приукрашен\n- покрытие функционала полное\n\n## Формат результата\n- новая версия документа ПСИ в карточке истории\n\n## Ограничения\n- не менять требования и не улучшать ожидания против постановки"),
        ]
        for name, role, skill in PRESET_AGENTS:
            agent = await _one(session, User, name=name)
            if agent is None:
                agent = (await session.execute(
                    sa.insert(User).values(name=name, user_type="agent").returning(User))).scalar_one()
                await session.flush()
            if await _one(session, AgentProfile, user_id=agent.id) is None:
                session.add(AgentProfile(user_id=agent.id, role=role, skill_md=skill,
                                         is_preset=True,
                                         preset_source={"role": role, "skill_md": skill}))
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
