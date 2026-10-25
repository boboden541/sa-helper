"""Доменные валидации задачи (чистые функции, без IO)."""

from __future__ import annotations

from domain.model.enums import AUTHOR_TAGS


class DomainError(Exception):
    """Ошибка домена: человекочитаемое сообщение + технический блок (два слоя, ФТ-ah-61-стиль)."""

    def __init__(self, message: str, tech: str = "", field: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.tech = tech
        self.field = field


def validate_title(title: str) -> str:
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= 64):
        raise DomainError(
            "Название обязательно: от 1 до 64 символов",
            tech=f"title length={len(title or '')}",
            field="title",
        )
    return title.strip()


def validate_description(description_md: str) -> str:
    if not isinstance(description_md, str) or len(description_md) > 20000:
        raise DomainError(
            "Описание — до 20 000 символов; не помещается — сигнал декомпозировать задачу",
            tech=f"description length={len(description_md or '')}",
            field="description_md",
        )
    return description_md


def validate_tags(author_tag: str, extra_tags: list[str] | None) -> list[str]:
    """Авторский тег обязателен (by_human/by_ai), всего от 1 до 5, без дублей (ФТ-ah-6)."""
    if author_tag not in AUTHOR_TAGS:
        raise DomainError(
            f"Авторский тег обязателен: {author_tag!r} — допустимо by_human или by_ai",
            tech=f"author_tag={author_tag!r}",
            field="authorTag",
        )
    tags: list[str] = [author_tag]
    for t in extra_tags or []:
        label = (t or "").strip().lstrip("#")
        if not label:
            continue
        if label in AUTHOR_TAGS:
            continue  # авторский уже добавлен
        if len(label) > 64:
            raise DomainError("Тег — до 64 символов", field="tags")
        if label not in tags:
            tags.append(label)
    if len(tags) > 5:
        raise DomainError(
            "Максимум 5 тегов на задаче (включая авторский)",
            tech=f"tags={tags!r}",
            field="tags",
        )
    return tags
