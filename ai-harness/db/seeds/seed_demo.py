"""Демо-набор для личной проверки интерфейса (идемпотентно).

История с дочерними в разных колонках, баг, pending на модерацию, blocked.
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
        existing = (await session.execute(sa.select(sa.func.count()).select_from(Task))).scalar_one()
        if existing >= 5:
            print(f"Демо-данные уже есть ({existing} задач) — пропускаю")
            await dispose_engine()
            return

        human = (await session.execute(
            sa.select(User).where(User.name == "Алексей"))).scalar_one()

        def inp(**kw):
            base = dict(project_mnemonic="AH", title="Демо", priority="medium",
                        author_tag="by_human", description_md="")
            base.update(kw)
            return CreateTaskInput(**base)

        story = await create_task(session, human, inp(
            type_key="story", title="Личный кабинет клиента", priority="high",
            tags=["демо", "frontend"],
            description_md="## Цель\nДать клиенту личный кабинет.\n\n"
                           "### Что входит\n- профиль\n- история заказов\n- настройки уведомлений"))
        print("story:", story.code)

        children = [
            ("common_task", "Профиль пользователя", "progress", ["frontend"]),
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
