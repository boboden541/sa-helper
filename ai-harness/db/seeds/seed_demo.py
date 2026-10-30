"""Демо-набор для личной проверки интерфейса (идемпотентно).

История с дочерними в разных колонках, баг, pending на модерацию, blocked,
распределение на агентов (ФТ-ah-31) — карточки «в работе у агента X».
Запуск: python -m db.seeds.seed_demo
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import sqlalchemy as sa  # noqa: E402


async def demo() -> None:
    from database import dispose_engine, get_sessionmaker, init_engine
    from config import get_settings
    from repository.models import Task, User
    from usecase.task.create_task import CreateTaskInput, create_task

    init_engine(get_settings().database_url)
    async with get_sessionmaker()() as session:
        human = (await session.execute(
            sa.select(User).where(User.name == "Алексей"))).scalar_one()

        def inp(**kw):
            base = dict(project_mnemonic="AH", title="Демо", priority="medium",
                        author_tag="by_human", description_md="")
            base.update(kw)
            return CreateTaskInput(**base)

        # --- распределение на агентов (ФТ-ah-31) ------------------------------
        # Пока в базе нет ни одной задачи с агентом — раскладываем демо-набор.
        has_agent = (await session.execute(
            sa.select(sa.func.count()).select_from(Task).where(Task.reserved_by.isnot(None)))).scalar_one()
        if has_agent == 0:
            async def agent_user(name: str):
                return (await session.execute(
                    sa.select(User).where(User.name == name))).scalar_one_or_none()

            dev = await agent_user("Разработчик")
            rev = await agent_user("Ревьюер")
            qa = await agent_user("Тестировщик")
            if dev and rev and qa:
                story2 = await create_task(session, human, inp(
                    type_key="story", title="Уведомления в браузере", priority="medium",
                    tags=["демо", "backend"],
                    description_md="## Цель\nКлиент получает push о статусе заказа.\n\n"
                                   "### Шаги\n- сервис уведомлений\n- настройка подписки"))
                print("story:", story2.code)
                kids = [
                    ("common_task", "Сервис уведомлений", "in_progress", dev, ["backend"]),
                    ("common_task", "Настройка подписки", "review_ready", rev, ["frontend"]),
                    ("qa_task", "Проверка доставки уведомлений", "in_testing", qa, ["демо"]),
                ]
                for ttype, title, status, agent, tags in kids:
                    t = await create_task(session, human, inp(
                        type_key=ttype, title=title, priority="medium", tags=tags,
                        story_code=story2.code,
                        description_md=f"Часть истории {story2.code}: {title}."))
                    await session.execute(sa.update(Task).where(Task.code == t.code)
                                          .values(status_key=status, reserved_by=agent.id))
                solo = await create_task(session, human, inp(
                    type_key="common_task", title="Починить флапающий тест очереди", priority="high",
                    tags=["демо"], description_md="Тест падает 1 раз из 5 в CI."))
                await session.execute(sa.update(Task).where(Task.code == solo.code)
                                      .values(status_key="in_progress", reserved_by=dev.id))
                await session.commit()
                print("распределение на агентов готово")

        # --- базовый демо-набор ------------------------------------------------
        # Идемпотентность по своему артефакту, а не по общему числу задач:
        # гвардия «уже есть ≥5 задач» отсекала этот блок сразу после блока
        # распределения (он сам создаёт 5) — на свежем сиде «Личный кабинет»
        # никогда не появлялся, и e2e full-sweep 04+ не могли пройти
        # (дрейф спек против сида, анализ 30.10.2026)
        lk = (await session.execute(
            sa.select(sa.func.count()).select_from(Task)
            .where(Task.title == "Личный кабинет клиента"))).scalar_one()
        if lk:
            print("Демо-набор «Личный кабинет» уже есть — пропускаю")
            await dispose_engine()
            return

        story = await create_task(session, human, inp(
            type_key="story", title="Личный кабинет клиента", priority="high",
            tags=["демо", "frontend"],
            description_md="## Цель\nДать клиенту личный кабинет.\n\n"
                           "### Что входит\n- профиль\n- история заказов\n- настройки уведомлений"))
        print("story:", story.code)

        children = [
            ("common_task", "Профиль пользователя", "in_progress", ["frontend"]),
            ("common_task", "История заказов", "review_ready", ["backend"]),
            ("common_task", "Настройки уведомлений", "todo", ["frontend"]),
        ]
        codes = []
        for ttype, title, status, tags in children:
            t = await create_task(session, human, inp(
                type_key=ttype, title=title, priority="medium", tags=tags,
                story_code=story.code,
                description_md=f"Часть истории {story.code}: {title}."))
            codes.append((t.code, status))

        bug = await create_task(session, human, inp(
            type_key="bug", title="Ошибка 500 при сохранении профиля", priority="critical",
            tags=["демо"], story_code=story.code,
            description_md="**Воспроизведение:** сохранить профиль без email."))
        codes.append((bug.code, "in_progress"))

        pending = await create_task(session, human, inp(
            type_key="common_task", title="Экспорт отчёта в Excel", priority="low",
            tags=["демо"],
            description_md="Предложение: кнопка экспорта в списке заказов."))
        print("pending:", pending.code)

        for code, status in codes:
            await session.execute(sa.update(Task).where(Task.code == code)
                                  .values(status_key=status))
        await session.commit()

        # blocked-пример: дочерняя с незакрытым чеклистом контекста
        blocked = await create_task(session, human, inp(
            type_key="common_task", title="Интеграция платежного шлюза", priority="high",
            tags=["демо"], story_code=story.code))
        await session.execute(sa.update(Task).where(Task.code == blocked.code)
                              .values(status_key="blocked",
                                      blocked_reason="Ждём доступы к sandbox шлюза от вендора"))
        await session.commit()
        print("blocked:", blocked.code)

    await dispose_engine()
    print("Демо-данные готовы")


if __name__ == "__main__":
    asyncio.run(demo())
