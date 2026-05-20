# Operations

## Setup

```bash
cd /home/mylendad/Desktop/Projects/confluence_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Если `python` отсутствует в системе, используйте:

```bash
.venv/bin/python -m app.cli --help
```

## Required environment

Основные переменные в `.env`:

```env
CONFLUENCE_BASE_URL=...
CONFLUENCE_SPACE_KEY=...
CONFLUENCE_ROOT_PAGE_ID=...
CONFLUENCE_USERNAME=...
CONFLUENCE_API_TOKEN=...
LLM_PROVIDER=gigachat
GIGACHAT_CREDENTIALS=...
```

Секреты не коммитить и не писать в README.

## Local S2T smoke test

```bash
.venv/bin/python -m app.cli parse-s2t s2t_template_5_sheets_filled.xlsx \
  --datamart "Витрина клиентских операций"
.venv/bin/python -m app.cli build-rag --full
.venv/bin/python -m app.cli ask "В каких витринах есть атрибут epk_id?"
```

Ожидаемый ответ:

```text
Атрибут найден в витринах: Витрина клиентских операций
```

## Terminal chat

```bash
.venv/bin/python -m app.cli chat
```

Выход:

```text
exit
```

Проверочный вопрос:

```text
кто владелец Витрина клиентских операций
```

## HTTP API

Запуск:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Ask:

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"В каких витринах есть атрибут epk_id?"}'
```

OpenAPI UI:

```text
http://127.0.0.1:8000/docs
```

## Confluence dry-run

Проверка поиска витрин и S2T без обновления локального RAG:

```bash
.venv/bin/python -m app.cli parse-confluence --dry-run
```

## Incremental RAG dry-run

Проверка metadata-first плана без скачивания/парсинга/RAG update:

```bash
.venv/bin/python -m app.cli update-rag --dry-run
```

Поля отчета:

| Поле | Значение |
| --- | --- |
| `metadata_changed` | Изменились ли metadata Confluence относительно `s2t_state`. |
| `reasons` | Почему ресурс считается измененным. |
| `will_download` | Будет ли скачан S2T. |
| `will_parse` | Будет ли запущен парсер S2T. |
| `will_reindex` | Будет ли обновлен RAG по витрине. |

## Incremental RAG update

Реальное обновление:

```bash
.venv/bin/python -m app.cli update-rag
```

Команда:

1. Получает metadata Confluence.
2. Пропускает неизмененные S2T.
3. Скачивает только metadata-changed S2T.
4. Сравнивает `sha256(content)`.
5. Парсит только реально изменившиеся файлы.
6. Обновляет только затронутые витрины в RAG.
7. Обновляет `change_log` и `s2t_state`.

## Full rebuild

Использовать вручную, если локальный индекс нужно восстановить с нуля:

```bash
.venv/bin/python -m app.cli build-rag --full
```

Для планового Confluence refresh использовать `update-rag`, а не full rebuild.

## Inspect local state

Проверить количество документов в JSONL vector store:

```bash
wc -l data/vector_store/documents.jsonl
```

Проверить CLI-команды:

```bash
.venv/bin/python -m app.cli --help
.venv/bin/python -m app.cli update-rag --help
```

## Tests and lint

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check app tests
```

## Troubleshooting

### `python: command not found`

Используйте:

```bash
.venv/bin/python -m app.cli ...
```

### `S2T file not found: path/to/s2t.xlsx`

`path/to/s2t.xlsx` — placeholder. Укажите реальный путь к Excel/CSV S2T.

### Вопрос по витрине возвращает "данных нет"

Проверьте, что эта витрина действительно загружена в локальную SQLite-базу. Например,
если загружена только `Витрина клиентских операций`, вопрос про `Витрина счетов` должен
возвращать отсутствие данных, а не подставлять похожую витрину.

### GigaChat недоступен

Structured ответы должны работать без LLM. Генеративные ответы вернут ошибку вида:

```text
Не удалось вызвать LLM для генеративного ответа: ...
```

### Confluence DNS/network error

Проверьте сеть, VPN, URL Confluence и credentials в `.env`.
