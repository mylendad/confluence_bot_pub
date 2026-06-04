# Confluence S2T RAG Bot

Интеллектуальный помощник для работы с документацией витрин данных. Проект объединяет данные из Confluence, S2T-маппингов (Excel/CSV) и предоставляет RAG-поиск (Retrieval-Augmented Generation) через GigaChat.

Проект организован в соответствии с лучшими практиками микросервисной архитектуры: логика разделена на независимые сервисы и общие компоненты.

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
```

## Запуск приложения

### Web UI (FastAPI)
Запуск сервера с веб-интерфейсом:
```bash
python main.py
```
После запуска интерфейс доступен по адресу: `http://localhost:8000/ui/`

### CLI (Командная строка)
Для выполнения административных задач и локальных проверок:
```bash
python cli.py update-rag --dry-run
python cli.py ask "В каких витринах есть атрибут epk_id?"
python cli.py chat
```

## Архитектура проекта

Проект разделен на три основных слоя:

### 1. Сервисы (`services/`)
*   **Ingestion (`services/ingestion`)**: Синхронизация с Confluence, парсинг S2T-файлов и контроль версий.
*   **RAG (`services/rag`)**: Семантический поиск, эмбеддинги и интеграция с GigaChat.
*   **Bot/API (`services/bot`)**: Интерфейсы взаимодействия (FastAPI, CLI).

### 2. Общий слой (`shared/`)
*   **Storage**: Доступ к SQLite (метаданные) и Vector Store.
*   **Models**: Единые контракты данных (Pydantic).
*   **Config & Logging**: Централизованная настройка и логирование.

### 3. Фронтенд (`web/`)
Современный SPA-интерфейс на Vanilla JS, разделенный на модули HTML/CSS/JS.

## Документация

Подробная информация о системе доступна в директории `docs/`:
- [Карта проекта](docs/project_map.md) — детальная структура директорий и назначение модулей.
- [Архитектура](docs/architecture.md) — описание логики работы, потоков данных и микросервисного подхода.
- [Операции](docs/operations.md) — подробные инструкции по запуску и обслуживанию.

## Настройка (.env)

Основные параметры для работы:
```env
CONFLUENCE_PAGE_URL=...      # Ссылка на корневую страницу в Confluence
CONFLUENCE_TOKEN=...         # Personal Access Token
GIGACHAT_CREDENTIALS=...     # API-ключ GigaChat
```
Полный список настроек см. в `.env.example`.
