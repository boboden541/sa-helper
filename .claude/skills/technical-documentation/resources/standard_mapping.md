# Стандарт преобразования "Код -> C4 Component" (Agnostic Mapping)

Данный стандарт определяет правила трансляции программных сущностей в архитектурные блоки на схемах C4 Level 3.

| Роль в коде | Тип в C4 (PlantUML) | Описание и примеры реализации |
| :--- | :--- | :--- |
| **Ingress Handler / API Point** | `Component` | Точка входа, роутинг. (напр. Controllers, Handlers, Resolvers, Listeners) |
| **Domain Logic / Orchestrator** | `Component` | Бизнес-логика системы. (напр. Services, UseCases, Managers, Domain Logic) |
| **Persistence Adapter / DAO** | `Component` | Абстракция доступа к данным. (напр. Repositories, DAO, Stores, Models) |
| **Integration Bridge / Client** | `Component` | Шлюз интеграции с внешними системами. (напр. Clients, Gates, External Proxies) |
| **Configuration Context** | `Component` | Компонент управления настройками. (напр. Config Managers, Env Providers) |

## Маппинг хранилищ и инфраструктуры

| Тип ресурса | Тип в C4 (PlantUML) | Протокол на связи (Rel) |
| :--- | :--- | :--- |
| **Persistent Storage** | `ContainerDb` | Физическая БД (SQL, NoSQL, Document Store). Протокол: SQL, TCP, ODBC |
| **Search Engine** | `Container` | Поисковые движки (Sphinx, Elasticsearch). Протокол: SphinxQL, REST, RPC |
| **State Cache / KV** | `Container` | Кэширование данных (Redis, Memcached). Протокол: TCP, Redis protocol |
| **Message Broker** | `Container` | Шина данных (Kafka, RabbitMQ). Протокол: Pub/Sub, AMQP |

## Обязательное именование связей (Rel)
- Каждая связь между компонентами должна содержать: `Rel(Source, Target, "Бизнес-действие на русском", "Технический протокол")`.
- **Пример:** `Rel(CatalogService, PaymentGateway, "Проверка оплаты", "REST/HTTPS")`.

---
**Примечание:** Если в проекте используются специфические паттерны именования (напр. суффиксы `_Handler` вместо `Controller`), следуй логике ролей, а не названию.
