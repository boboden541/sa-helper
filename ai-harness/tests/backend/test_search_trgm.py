"""НФТ-ah-1 / AC-4.1.2.2: триграммный нечёткий поиск по названию, префикс по коду."""

from __future__ import annotations

from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.list_tasks import list_tasks


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Настройка оплаты счетов",
                priority="high", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def test_search_by_word_fragment(session, actor_id):
    """Поиск по фрагменту слова внутри названия находит задачу."""
    from repository.models import User

    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    total, cards = await list_tasks(session, q="оплат")
    assert total >= 1 and any(c.code == t.code for c in cards)


async def test_search_by_code_prefix(session, actor_id):
    from repository.models import User

    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    total, cards = await list_tasks(session, q=t.code)
    assert any(c.code == t.code for c in cards)
    # префикс без полного номера
    prefix = t.code[:4]
    total, cards = await list_tasks(session, q=prefix)
    assert any(c.code == t.code for c in cards)


async def test_empty_query_returns_all(session, actor_id):
    from repository.models import User

    actor = await session.get(User, actor_id)
    await create_task(session, actor, _inp())
    total, _ = await list_tasks(session, q="")
    assert total >= 1
