# Переменные
VENV = .venv
PYTHON = $(VENV)/bin/python3
PIP = $(VENV)/bin/pip
PYTEST = $(VENV)/bin/pytest
UVICORN = $(VENV)/bin/uvicorn
RUFF = $(VENV)/bin/ruff
APP_MODULE = services.bot.main:app

.PHONY: help install test lint format run clean venv

help:
	@echo "Доступные команды:"
	@echo "  make install  - Создание .venv и установка зависимостей"
	@echo "  make run      - Запуск сервера из .venv и открытие UI"
	@echo "  make test     - Запуск тестов из .venv"
	@echo "  make lint     - Проверка ruff из .venv"
	@echo "  make format   - Форматирование ruff из .venv"
	@echo "  make clean    - Очистка временных файлов"

venv: $(VENV)/bin/activate

$(VENV)/bin/activate:
	@echo "Создание виртуального окружения..."
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv
	@echo "Установка зависимостей в $(VENV)..."
	$(PIP) install -e ".[dev]"

run: venv
	@echo "Запуск сервера из $(VENV) на http://127.0.0.1:8000..."
	@# Команда для открытия браузера в зависимости от ОС
	@if [ "$$(uname)" = "Darwin" ]; then \
		open http://127.0.0.1:8000; \
	elif [ "$$(expr substr $$(uname -s) 1 5)" = "Linux" ]; then \
		xdg-open http://127.0.0.1:8000 > /dev/null 2>&1 & \
	elif [ "$$(expr substr $$(uname -s) 1 10)" = "MINGW32_NT" ] || [ "$$(expr substr $$(uname -s) 1 10)" = "MINGW64_NT" ]; then \
		start http://127.0.0.1:8000; \
	fi
	$(UVICORN) $(APP_MODULE) --reload

test: venv
	$(PYTEST)

lint: venv
	$(RUFF) check .

format: venv
	$(RUFF) format .

clean:
	rm -rf `find . -name __pycache__`
	rm -f `find . -type f -name "*.py[co]"`
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf *.egg-info
	rm -rf dist
	rm -rf build
	@echo "Для удаления окружения выполните: rm -rf $(VENV)"
