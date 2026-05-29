# [ШАБЛОН] Data Trace Report: {Entity Name}

> [!IMPORTANT]
> **CRITICAL REQUIREMENTS:**
>
> 1. **Data Examples:** Every UML Sequence diagram MUST contain a `note` block with a data example (JSON/Array).
> 2. **Full Entity Coverage:** All fields from the source code (DTO/Entity/$schema) MUST be listed in the mapping table or explicitly justified for exclusion.
> 3. **Physical Origin:** Every field MUST have a `Store.Table.Column` mapping.

## 1. Общее описание (Overview)

Краткое резюме того, какой путь проходят данные от инициации пользователем до записи/чтения в хранилище.

- **Technical Endpoint:** {METHOD} {/path/url}
- **Source:** {Откуда приходят данные в начале цепочки}
- **Destination:** {Конечная точка хранения или внешняя система}

## 2. The Chain (Слои обработки)

Пошаговое описание движения данных с указанием конкретных файлов и методов.

### {Layer Name: напр. Controller/Service/DAO}

- **Компонент:** `Class::method`
- **Бизнес-логика:** {Описание действия на человеческом языке}.
- **Технические детали:** {Условия фильтрации, флаги, SQL-запросы или имена индексов}.

## 3. Визуализация (PlantUML)

Диаграмма последовательности со следующими требованиями:

- Текст на стрелках — только на РУССКОМ.
- В скобках под описанием — технический метод.
- **Обязательно:** Наличие `note` с примером структуры данных (JSON/Array).
- Описание конкретных SQL-запросов (`SELECT FROM...`) или индексов.

## 4. Сводная таблица маппинга (Data Lineage)

| Параметр | Тип | Описание | Origin (Происхождение: БД/Метод/API) |
| :--- | :--- | :--- | :--- |
| {param_name} | {type} | {Бизнес-смысл} | {Table.Column или Calculated} |

## 5. Якоря истины (Anchors of Truth)

[{FileName}](../../path/to/File)

## 6. Побочные эффекты (Side Effects)

Список действий, которые не влияют на основной результат, но важны для системы (Аналитика, Кэширование, Логи, СОРМ).
