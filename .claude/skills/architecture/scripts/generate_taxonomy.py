import os
import json

def generate_taxonomy(root_dir):
    taxonomy = {
        "domains": {},
        "integrations": []
    }

    # Анализ структуры папок для определения доменов
    for root, dirs, files in os.walk(root_dir):
        # Пропускаем скрытые и vendor-папки
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('vendor', 'node_modules', '__pycache__', 'dist')]

        # Определяем домен по имени папки (универсальная эвристика)
        parts = root.replace(root_dir, '').split(os.sep)
        if len(parts) >= 2:
            domain_name = parts[-1]
            if domain_name and files:
                taxonomy["domains"][domain_name] = files[:10]

    # Поиск упоминаний внешних протоколов
    # (Здесь может быть логика grep по repomix-output.xml)

    return taxonomy

# Результат работы скрипта сохраняется в resources/project_context.json
