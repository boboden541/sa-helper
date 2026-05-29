---
description: Построение графа кодовой базы проекта в Neo4j
---

## Использование

```
/project-map
```

## Результат

Граф проекта в Neo4j: классы, функции, вызовы, импорты, SQL-запросы. Доступен для визуализации и навигации в Neo4j Browser.

---

## Инструкция для LLM

### Этап 1: Проверка окружения

1. Проверь, установлен ли Docker:
   ```
   docker --version
   ```
   Если нет — выведи инструкцию: "Установите Docker Desktop и перезапустите терминал".

2. Проверь, запущен ли Neo4j:
   ```
   curl -s http://localhost:7474 > /dev/null 2>&1 && echo "RUNNING" || echo "STOPPED"
   ```

3. Если Neo4j не запущен — подними его:
   ```
   docker compose -f indexer/docker-compose.yml up -d
   ```
   Дождись запуска (~10 секунд). Проверь:
   ```
   curl -s http://localhost:7474 > /dev/null 2>&1 && echo "OK" || echo "WAITING"
   ```

### Этап 2: Установка зависимостей

1. Проверь наличие папки `indexer/` в корне проекта. Если её нет — файлы индексатора не установлены. Выведи ошибку.

2. Установи Python-зависимости:
   ```
   pip install -r indexer/requirements.txt
   ```

### Этап 3: Запуск индексации

1. Запусти индексатор:
   ```
   python indexer/main.py .
   ```

2. Дождись завершения. Индексатор выведет статистику: количество узлов и связей.

### Этап 4: Отчёт

Выведи итоговый отчёт:

```
Граф проекта построен.

Узлы: <N> узлов (<C> классов, <F> функций, <I> импортов)
Связи: <R> связей

Визуализация: http://localhost:7474
Логин: neo4j / sahelper2026

Полезные Cypher-запросы:
- Все классы: MATCH (c:Class) RETURN c.name, c.file
- Методы класса: MATCH (c:Class)-[:HAS_METHOD]->(f:Function) WHERE c.name = 'ClassName' RETURN f.name
- Вызовы функций: MATCH (a:Function)-[:CALLS]->(b:Function) RETURN a.name, b.name
- Все SQL-таблицы: MATCH (t:Table) RETURN t.name, t.source_file
- Импорты файла: MATCH (f:File {path: 'path/to/file'})-[:IMPORTS]->(i:Import) RETURN i.source
```
