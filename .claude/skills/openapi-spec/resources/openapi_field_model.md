# Модель полей: артефакт кода → ключ OpenAPI Schema

Таблица соответствия для перевода описания поля из кода в OpenAPI 3.0.3 Schema Object. Цель — не потерять ни одного валидационного ограничения, присутствующего в коде, и не выдумать отсутствующего.

> Целевая версия — **3.0.3** (см. `SKILL.md`, принцип 3): одиночный `type` + `nullable: true`. Union-тип 3.1 запрещён для плагина «OpenAPI (Swagger) Editor».

## 1. Базовые типы

| Источник в коде (примеры разных стеков) | `type` | `format` |
|------------------------------------------|--------|----------|
| `int`, `Integer`, `int32` | `integer` | `int32` |
| `long`, `bigint`, `int64` | `integer` | `int64` |
| `float`, `double`, `decimal` | `number` | `float` / `double` |
| `string`, `varchar`, `text` | `string` | — |
| `uuid`, `Guid` | `string` | `uuid` |
| `date` | `string` | `date` |
| `datetime`, `timestamp` | `string` | `date-time` |
| `email` (валидатор) | `string` | `email` |
| `uri`, `url` | `string` | `uri` |
| `bool`, `boolean`, `bit` | `boolean` | — |
| `bytes`, `blob`, base64 | `string` | `byte` / `binary` |

## 2. Валидационные ограничения

| Аспект | Ключ OpenAPI | Откуда в коде |
|--------|-------------|---------------|
| Обязательность | имя поля в массиве `required` родительского объекта | not-null/`@NotNull`/`@NonNull`, `required=True`, отсутствие default, NOT NULL в DDL |
| Обнуляемость | `nullable: true` (рядом с `type`) | nullable-колонка БД, `Optional[...]`, `T?`, `@Nullable` |
| Регэксп | `pattern` | `@Pattern(regexp=…)`, `regex=…`, `RegularExpression`, проверка в коде |
| Мин/макс длина строки | `minLength` / `maxLength` | `@Size(min,max)`, `max_length`, `@Length`, длина `varchar(N)` в DDL |
| Мин/макс число | `minimum` / `maximum` | `@Min`/`@Max`, `@DecimalMin`, `ge=/le=`, явные проверки границ |
| Строгие границы | `exclusiveMinimum: true` / `exclusiveMaximum: true` (в 3.0 — булевы!) | `gt=/lt=`, `@DecimalMin(inclusive=false)` |
| Перечисление | `enum: [...]` | enum-тип, набор констант, `Literal[...]`, проверка `in [...]` |
| Значение по умолчанию | `default` | дефолт поля/параметра в коде |
| Только для чтения | `readOnly: true` | поле выставляется сервером (id, created_at) |
| Пример | `example` | дефолт, фикстура, тест, сидер, комментарий |

> В 3.0.3 `exclusiveMinimum`/`exclusiveMaximum` — **булевы** модификаторы к `minimum`/`maximum`, а НЕ числа (число — это синтаксис 3.1/JSON Schema).

## 3. Контейнеры (перевод нотации `Object<…>`/`Array<…>` из `ideal_api_document.md:80`)

| Нотация в Markdown-документе | OpenAPI Schema |
|------------------------------|----------------|
| `Object<Foo>` (одиночный объект) | вынести в `components/schemas/Foo`; в месте использования `$ref: '#/components/schemas/Foo'` |
| `Array<Foo>` (массив объектов) | `type: array` + `items: { $ref: '#/components/schemas/Foo' }` |
| `Array<string>` / `Array<int>` (массив скаляров) | `type: array` + `items: { type: string }` / `{ type: integer }` |
| вложенный объект без имени DTO | `type: object` + `properties: {...}` (инлайн) |

**Правила:**
1. Имя схемы (`Foo`) = имя класса/DTO из кода — сохраняет трассируемость.
2. Каждый повторно используемый объект — отдельная схема в `components/schemas`, не дублировать инлайн.
3. `type: array` без `items` — невалидно.
4. `type: object` для известного DTO без `properties` — теряет состав полей (помечать `[NEEDS_INVESTIGATION]`, если состав действительно неизвестен).

## 4. Нуллабельный `$ref` (особый случай 3.0)

Пометить ссылку `nullable` напрямую нельзя. Если поле-объект может быть `null`:

```yaml
poster:
  nullable: true
  allOf:
    - $ref: '#/components/schemas/Image'
```

Если `null` для объекта в коде не предусмотрен — просто `$ref` без обёртки.

## 5. Размещение в документе

| Что | Где в спеке |
|-----|-------------|
| Path-параметры (`{id}`) | `paths.<path>.<method>.parameters` с `in: path`, `required: true` |
| Query-параметры | `parameters` с `in: query` |
| Заголовки | `parameters` с `in: header` |
| Тело запроса | `requestBody.content.<media-type>.schema` (`$ref` на DTO) |
| Ответы | `responses.<код>.content.<media-type>.schema` |
| Все именованные DTO | `components.schemas.<Name>` |

## 6. Что НЕ выдумывать (связь с принципом 2 навыка)

Если в коде НЕТ ограничения — ключ НЕ добавляется. Отсутствие подтверждённого значения для поля фиксируется в его `description` строкой `[NEEDS_INVESTIGATION]: <что проверить>`, без выдуманных `example`/`pattern`/`min*`/`max*`.

## 7. Идентичность DTO и доменный файл (принципы 5а и 9 навыка)

Документ — один на домен (`<domain>.yaml`), методы дописываются, `components/schemas` общий.

| Ситуация в коде | Решение в схемах |
|-----------------|------------------|
| Метод B использует ТОТ ЖЕ класс, что метод A | Один `$ref` на общую схему; не дублировать |
| Два РАЗНЫХ класса с идентичными полями | ДВЕ схемы (разные имена) — поля совпадают случайно, идентичность по классу |
| Короткие имена двух разных классов совпадают | Дизамбигуация префиксом модуля: `Shows_Building`, `Search_Building` |
| Один класс, но разное заполнение в разных контекстах | Одна схема; контекстные различия (какие поля null) — в `description` |

**Ключ идентичности — `x-source`** (FQCN или относительный путь к файлу класса). Указывай его у каждой схемы. Перед добавлением схемы при мёрже ищи существующую с тем же `x-source`: нашёл → переиспользуй, не нашёл → добавь новую.

> Эвристика: «похожие поля» ≠ «один DTO». Сначала смотри, один ли это класс в коде, и только потом решай про переиспользование.
