# Операции (Operations)

## Установка и настройка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Для всех команд проекта используйте Python из виртуального окружения. В корне проекта находятся удобные точки входа: `main.py` для сервера и `cli.py` для командной строки.

## Командный интерфейс (CLI)

### Проверка поиска витрин (Dry-run)
```bash
python cli.py update-rag --dry-run
```

### Парсинг локального файла S2T
```bash
python cli.py parse-s2t path/to/your/s2t.xlsx --datamart "Название витрины"
```

### Полная пересборка индекса RAG
Используется при изменении модели эмбеддингов или логики индексации.
```bash
python cli.py build-rag --full
```

### Инкрементальное обновление RAG
Основная команда для синхронизации с Confluence.
```bash
python cli.py update-rag
```

### Чат в терминале
```bash
python cli.py chat
```

## Запуск Web UI и API

Запуск сервера через точку входа в корне:
```bash
python main.py
```

### Проверка работоспособности
```bash
curl http://127.0.0.1:8000/health
```

### Документация API (Swagger)
Доступна по адресу: `http://127.0.0.1:8000/docs`

## Тестирование и Линтинг

```bash
pytest
ruff check .
ruff format .
```

## Troubleshooting (Решение проблем)

### Ошибка 429 (Too Many Requests) от Confluence
Добавьте задержку между запросами в `.env`:
```env
CONFLUENCE_REQUEST_DELAY=0.2
```

### GigaChat недоступен
Технические ответы (через SQL к SQLite) продолжат работать, но генеративные ответы (RAG) будут возвращать ошибку.

### Ошибки подключения (VPN/Сеть)
Проверьте доступность Confluence и Jira API, а также правильность токенов в настройках UI или в `.env`.
