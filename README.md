# Confluence S2T RAG Bot

Минимально рабочий Python-проект для чат-бота по витринам данных: парсинг Confluence, выбор актуального S2T, разбор Excel/CSV, хранение структурированных данных, история изменений и RAG-поиск.

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
.venv/bin/python -m pytest
```

CLI:

```bash
.venv/bin/python -m app.cli parse-confluence --dry-run
.venv/bin/python -m app.cli parse-s2t s2t_template_5_sheets_filled.xlsx --datamart "Витрина клиентских операций"
.venv/bin/python -m app.cli build-rag --full
.venv/bin/python -m app.cli update-rag --dry-run
.venv/bin/python -m app.cli ask "В каких витринах есть атрибут epk_id?"
.venv/bin/python -m app.cli chat
```

В примерах команды запускаются через `.venv/bin/python`, чтобы не зависеть от
активированного shell. Путь `path/to/s2t.xlsx` в примерах нужно заменять на реальный
Excel/CSV-файл S2T.

Для приложенного 5-листового шаблона S2T поддерживаются листы `Target columns`, `Source columns`,
`Datamart info` и `S2T`. Тестовый заполненный пример лежит в
`s2t_template_5_sheets_filled.xlsx`:

```bash
.venv/bin/python -m app.cli parse-s2t s2t_template_5_sheets_filled.xlsx --datamart "Витрина клиентских операций"
.venv/bin/python -m app.cli build-rag --full
.venv/bin/python -m app.cli ask "Какая логика преобразования используется для epk_id?"
```

HTTP:

```bash
uvicorn app.main:app --reload
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Кто владелец витрины клиентских операций?"}'
```

## Секреты

Токены и пароли не хранятся в коде. Задайте их в `.env`:

```env
CONFLUENCE_PAGE_URL=https://confluence.delta.sbrf.ru/pages/viewpage.action?pageId=4700310446
CONFLUENCE_AUTH_TYPE=bearer
CONFLUENCE_TOKEN=...
LLM_PROVIDER=gigachat
GIGACHAT_CREDENTIALS=...
GIGACHAT_SCOPE=GIGACHAT_API_PERS
CONFLUENCE_REQUEST_DELAY=0.2
```

Для корпоративного Confluence с Personal Access Token используйте `CONFLUENCE_AUTH_TYPE=bearer`
и `CONFLUENCE_TOKEN`, оставив `CONFLUENCE_USERNAME` пустым. `CONFLUENCE_PAGE_URL`
автоматически задает `CONFLUENCE_BASE_URL` и `CONFLUENCE_ROOT_PAGE_ID` из ссылки
с `pageId`. Для Atlassian Cloud совместимый режим Basic auth остается прежним:
задайте `CONFLUENCE_USERNAME` и `CONFLUENCE_API_TOKEN`.

`GIGACHAT_CREDENTIALS` не выводится в логи. Для совместимости приложение также умеет
читать ключ из `GIGACHAT_API_KEY` или `GIGACHAT_API_PERS`, но основной вариант для
новой настройки — `GIGACHAT_CREDENTIALS`.

Переменная `CONFLUENCE_REQUEST_DELAY` задает задержку в секундах между запросами к
Confluence, чтобы избежать блокировки при слишком частых запросах (ошибка 429).

## Архитектура

- `app/confluence` — клиент и парсер Confluence.
- `app/s2t` — парсеры S2T Excel/CSV/Confluence tables.
- `app/storage` — SQLite-репозитории для документов, атрибутов и метаданных.
- `app/changes` — сравнение снимков и change log.
- `app/rag` — индексирование, retrieval и промпты.
- `app/sync` — инкрементальная metadata-first синхронизация Confluence/S2T/RAG.
- `app/bot` — бизнес-сервис и адаптеры CLI/HTTP/SberChat.

MVP использует SQLite для точных вопросов и простой локальный JSONL vector store для
смыслового поиска. Для генерации ответов используется GigaChat, если
`LLM_PROVIDER=gigachat` и в `.env` задан ключ.

`.venv/bin/python -m app.cli update-rag` работает инкрементально: сначала сравнивает metadata Confluence,
скачивает только изменившиеся S2T, проверяет `sha256(content)` и обновляет только
затронутые витрины/chunks. Режим `--dry-run` показывает, что будет скачано,
распарсено и переиндексировано, без фактического обновления RAG.

## Документация

- [docs/README.md](docs/README.md) — индекс документации.
- [docs/architecture.md](docs/architecture.md) — архитектура, модули, хранилища и потоки данных.
- [docs/confluence-workflow.md](docs/confluence-workflow.md) — Confluence API, выбор S2T и metadata-first workflow.
- [docs/incremental-sync.md](docs/incremental-sync.md) — metadata-first обновление S2T/RAG.
- [docs/rag-and-bot.md](docs/rag-and-bot.md) — RAG, structured retriever и логика ответов.
- [docs/operations.md](docs/operations.md) — команды запуска, dry-run, тестирование и troubleshooting.
