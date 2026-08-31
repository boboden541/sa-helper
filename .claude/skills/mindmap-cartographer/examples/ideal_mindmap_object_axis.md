# Mindmap: Building-integrations — типы объектов (обзор)

> Карта погружения «от общего к частному». Обзорный документ: детали — в api/, integrations/, erd/, data_trace/. Задача: ad hoc.

**Сервис**: building-integrations · **Ось**: типы объектов · **Режим**: As-Is · **Цветовое измерение**: нет (одно хранилище-цель, цвет не кодируется)

**Источники фактов**: эталон скилла — рабочая карта владельца (BI → uat_db). При генерации здесь перечисляются использованные документы со статусами ✅/🟡 и дата repomix-снапшота.

```plantuml
@startmindmap
title Загрузка данных через BI в uat_db

*[#LightCyan] Building-integrations
** Шоу == show
*** 1. Поиск существующего маппинга
**** SELECT FROM bi_db.dbo.mapping
*** 2. Поиск типа шоу по названию (showType)
**** SELECT FROM uat_db.dbo.bi2_showtype_view
*** 3. Найти организатора (organizer)
**** SELECT FROM uat_db.dbo.Client
*** 4. Создать новое Шоу
**** EXEC uat_db.dbo.bi_AddShow
*** 5. Создать мапинг
**** INSERT bi_db.dbo.mapping
** Мероприятие == performance
*** 1. Поиск существующего мапинга
**** SELECT FROM bi_db.dbo.mapping
*** 2. Проверка зависимости Show
**** SELECT FROM bi_db.dbo.mapping
*** 3. Поиск типа шоу
**** SELECT FROM uat_db.dbo.bi2_showtype_view
*** 4. Поиск Организатора
**** SELECT FROM uat_db.dbo.Client
*** 5. Создание Шоу
**** EXEC uat_db.dbo.bi_AddShow
*** 6. Создание мапинга для Шоу
**** INSERT INTO bi_db.dbo.mapping
*** 7. Поиск связи с hall
**** SELECT FROM bi_db.dbo.mapping
*** 8. Создание Мероприятия
**** EXEC uat_db.dbo.BI_AddPerformance
*** 9. Создание мапинга для Мероприятия
**** INSERT bi_db.dbo.mapping
** Зал == hall
*** ...
** Секции == section
*** ...
** Билет == ticket
*** ...
** ...
@endmindmap
```

## Пруфы и источники

- Ось L1 — пары «бизнес-имя == тех.идентификатор» (`Шоу == show`); единицы без покрытия — честные заглушки `...` (принцип 7), НЕ молчаливый пропуск.
- Шаги L2 нумерованы в порядке выполнения; листья L3 — SQL-атомы с полным квалификатором (`EXEC uat_db.dbo.bi_AddShow`).
- Цвет не используется → legend отсутствует (правило: legend обязательна только при использовании цвета).
- При генерации здесь — относительные ссылки на использованные документы (`../erd/erd_*.md`, `../naming_conventions.md`).
