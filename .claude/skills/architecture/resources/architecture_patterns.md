# Библиотека архитектурных паттернов

Используй эти признаки для идентификации структуры системы при анализе кода.

## 1. Pattern: Backend For Frontend (BFF)
- **Признаки:** Контроллеры агрегируют данные из нескольких внешних сервисов; много прокси-методов; наличие папок `gateways`, `clients`.
- **C4 Mapping:** Приложение — это Container "BFF", а внешние вызовы — связи с другими Container.

## 2. Pattern: Layered Monolith
- **Признаки:** Четкое разделение на `Controllers`, `Services/Business`, `DAO/Repositories/Models`.
- **C4 Mapping:** Используй `Boundary` для каждого слоя внутри одного Container.

## 3. Pattern: Double Caching Strategy
- **Признаки:** Использование `LocalCache` (in-memory) + `DistributedCache` (Redis/Memcached и т.п.).
- **C4 Mapping:** Обязательная отрисовка компонента `DoubleCache` как посредника между логикой и БД.

## 4. Pattern: Legacy Gateway
- **Признаки:** Наличие адаптеров к legacy-БД или специфических протоколов (ODBC, SOAP).
- **C4 Mapping:** Выделять в отдельный `Boundary` (Integration Layer).