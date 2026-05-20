# 1.1 Метод actionIndex (Карточка шоу)
**Endpoint:** GET /{genre}/{subgenre}/{alias}/

**Пример:** GET /theatre/drama/hamlet/Internal 

**Route:** show/index

**Входные параметры (Код vs API):**

| Параметр | Тип | Источник | В коде (Argument) | Описание |
|----------|-----|----------|-------------------|----------|
| id | int | URL Alias | $id | ID шоу, извлеченный из {alias} компонентом ShowRule|
| nocache | bool | GET/Query | $nocache | Если 1, байпас кэша Redis |

**Логика БД (Deep Dive):**
1. Поиск в `db_web.dbo.st_show_view`: фильтр по `show_id = $id AND is_active = 1`. 
2. Если запись не найдена — throw new CHttpException(404).