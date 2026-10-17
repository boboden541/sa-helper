# AI Harness — витрина + демон + claude CLI в одном образе.
# Сборка: docker build -t sa-helper-harness -f harness/web/Dockerfile .
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force

# Код конвейера (сервер, демон, утилиты)
COPY harness/ /app/harness/
# Команды конвейера — попадают в воркспейс при инициализации (см. entrypoint)
COPY .claude/commands/ /opt/harness-commands/

WORKDIR /work
ENV HARNESS_API=http://127.0.0.1:4040

# Точка входа: разово скопировать команды конвейера в воркспейс (если их нет),
# затем выполнить переданную команду (сервер или демон).
COPY harness/web/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python3", "harness/web/server.py", "--workspace", "/work", "--port", "4040"]
