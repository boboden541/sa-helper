# Стандарты визуализации документации (Visual Standards)

**Версия**: 1.0
**Статус**: Обязателен к исполнению

## 1. Основной инструмент

- **PlantUML** — единственный разрешенный инструмент для всех типов диаграмм.
- **Mermaid** — **ЗАПРЕЩЕН** к использованию в финальной документации (допускается только для черновиков "на полях", если это не идет в `sa_documentation`).

## 2. Типы диаграмм по назначению

| Тип документа | Тип диаграммы (PlantUML) | Обязательные элементы |
| :--- | :--- | :--- |
| **API Doc** | `sequence` (Последовательность) | Акторы, Контроллеры, Сервисы, БД. Блоки `note` с примерами JSON. |
| **API Doc** | `activity` (Алгоритм) | `partition` для слоев, `fork` для параллельных запросов. |
| **Data Trace** | `activity` или `component` | Трассировка от URL до конкретной таблицы БД. |
| **Architecture** | `component` (C4 L3) | Использование нотации C4 (System, Container, Component). |

## 3. Правила оформления (Hard Rules)

### 3.1 Язык и Лейблы

- Все текстовые описания на стрелках и внутри блоков должны быть на **РУССКОМ** языке.
- Текст должен описывать **бизнес-смысл** действия (например: *"Запрос метаданных шоу"*).
- Техническое имя метода/функции указывается в скобках (например: `CatalogService::getById`).
- В случае если это интеграционное взаимодействие разных сервисов, то **обязательно** указывать url API обращения
- В случае если это обращение к базе данных, то **обязательно** указывать запрос обращения к БД

### 3.2 Глубина детализации

- **Слой данных:** Обязательно указывать логическое имя хранилища (например: `main_db`, `search_index`) и конкретный объект (View, Table, Index).
- **Примеры данных:** В местах передачи ключевых объектов (DTO, Response) обязателен блок `note` с примером структуры.

### 3.3 Стиль (Skinparam)

Для поддержания чистоты схем рекомендуется использовать минималистичный стиль:

```plantuml
skinparam handwritten false
skinparam monochrome true
skinparam shadowing false
skinparam DefaultFontName "Arial"

# Visual & UML Standards
## PlantUML C4 Inclusions (Golden Links)
Использовать ВСТРОЕННУЮ библиотеку (рекомендуется для стабильности):
- Core: `!include <C4/C4_Component>`
Если отсутсвует встроенная библиотека, то:
- Core: `https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4.puml`
- Context: `https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Context.puml`
- Container: `https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Container.puml`
- Component: `https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Component.puml`
## Запрещенные ссылки (Deprecated)
- `plantuml-office/...` (часто выдает 404)
- `C4_Context.puml` без полного URL (если не установлены локально)
