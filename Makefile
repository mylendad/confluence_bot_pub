# Переменные
PYTHON = python3
PIP = $(PYTHON) -m pip
PYTEST = $(PYTHON) -m pytest
UVICORN = uvicorn
APP_MODULE = services.bot.main:app

.PHONY: help install test lint format run clean

help:
	@echo "Доступные команды:"
	@echo "  make install  - Установка зависимостей (включая инструменты разработки)"
	@echo "  make run      - Запуск сервера и автоматическое открытие UI"
	@echo "  make test     - Запуск тестов"
	@echo "  make lint     - Проверка кода линтером (ruff)"
	@echo "  make format   - Форматирование кода (ruff)"
	@echo "  make clean    - Очистка временных файлов"

install:
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

run:
	@echo "Запуск сервера на http://127.0.0.1:8000..."
	@# Команда для открытия браузера в зависимости от ОС
	@if [ "$$(uname)" = "Darwin" ]; then \
		open http://127.0.0.1:8000; \
	elif [ "$$(expr substr $$(uname -s) 1 5)" = "Linux" ]; then \
		xdg-open http://127.0.0.1:8000 > /dev/null 2>&1 & \
	elif [ "$$(expr substr $$(uname -s) 1 10)" = "MINGW32_NT" ] || [ "$$(expr substr $$(uname -s) 1 10)" = "MINGW64_NT" ]; then \
		start http://127.0.0.1:8000; \
	fi
	$(PYTHON) -m uvicorn $(APP_MODULE) --reload

test:
	$(PYTEST)

lint:
	ruff check .

format:
	ruff format .

clean:
	rm -rf `find . -name __pycache__`
	rm -f `find . -type f -name "*.py[co]"`
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf *.egg-info
	rm -rf dist
	rm -rf build
