# 🗺 Стандарт преобразования "Код -> C4 Component" (Agnostic Roles)

Этот стандарт определяет, как программные сущности любого языка программирования переводятся в визуальные блоки на диаграммах C4 Level 3 (System Component).

## 1. Маппинг ролей компонентов

| Архитектурная роль | Тип в C4 | Признаки в коде (Любой стек) |
| :--- | :--- | :--- |
| **Ingress Handler** | `Component` | Обработчики входа: Controllers, Handlers, Func, Resolvers (GraphQL), Listeners (MQ). |
| **Domain Logic** | `Component` | Ядро системы: Services, Use-Cases, Managers, Domain Entities, Business Logic Layers. |
| **Persistence Adapter** | `Component` | Доступ к данным: Repositories, DAO, Stores, Mappers, DB-Adapters. |
| **Integration Bridge** | `Component` | Выходные шлюзы: Clients, Integration Gates, Proxies, Providers, Adapters. |
| **Infrastructure Svc** | `Component` | Служебные функции: Controllers (Infrastructure), Loggers, Cache Managers. |

## 2. Маппинг внешних сущностей (External Systems)

| Сущность | Тип в C4 | Характеристика |
| :--- | :--- | :--- |
| **Database Instance** | `ContainerDb` | Физическая БД: SQL инстанс, NoSQL кластер. |
| **Sidecar / Broker** | `Container` | Инфраструктурный элемент: Message Broker, Cache Node, CI/CD Sidecar. |
| **External Service** | `System_Ext` | Полностью внешняя система (Вендор, Другой департамент). |

## 3. Стандарт описания связей (Relations)

Каждое ребро диаграммы (`Rel`) должно быть строго типизировано:
- **Действие:** На РУССКОМ языке (бизнес-смысл).
- **Протокол:** Техническая реализация в скобках.
- **Пример:** `Rel(OrderHandler, BasketSvc, "Добавление товара", "gRPC")`
- **Пример:** `Rel(CatalogSvc, WebDB, "Поиск по афише", "SQL/ODBC")`

---
**МЕТОДОЛОГИЯ:** Аналитик обязан сначала определить **Роль** найденного файла, а затем применить к нему соответствующий тип компонента. Названия файлов (суффиксы) являются лишь подсказкой, а не правилом.
