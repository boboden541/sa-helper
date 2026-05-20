import os
import json

def generate_taxonomy(root_dir):
    taxonomy = {
        "domains": {},
        "integrations": []
    }
    
    # Простой анализ структуры папок для определения доменов
    for root, dirs, files in os.walk(root_dir):
        if 'protected/components' in root:
            domain_name = os.path.basename(root)
            taxonomy["domains"][domain_name] = files[:10] # берем первые 10 файлов как пример
            
    # Поиск упоминаний внешних протоколов
    # (Здесь может быть логика grep по repomix-output.xml)
    
    return taxonomy

# Результат работы скрипта сохраняется в resources/project_context.json