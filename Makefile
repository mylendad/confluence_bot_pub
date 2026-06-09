# Используем bash для поддержки команды source
SHELL := /bin/bash

# Переменные
VENV = .venv
VENV_BIN = $(VENV)/bin
PYTHON = $(VENV_BIN)/python3
PIP = $(PYTHON) -m pip
UVICORN = $(VENV_BIN)/uvicorn
RUFF = $(VENV_BIN)/ruff
PYTEST = $(VENV_BIN)/pytest
APP_MODULE = services.bot.main:app

.PHONY: help install test lint format run clean setup

help:
	@echo "Доступные команды:"
	@echo "  make setup    - Подготовка окружения (создание .env и .venv)"
	@echo "  make install  - Установка зависимостей (активирует существующий .venv)"
	@echo "  make run      - Запуск сервера и открытие UI"
	@echo "  make test     - Запуск тестов"
	@echo "  make lint     - Проверка ruff"
	@echo "  make format   - Форматирование ruff"
	@echo "  make clean    - Очистка временных файлов"

setup:
	@if [ ! -f .env ]; then \
		echo "Создаю .env из шаблона..."; \
		cp .env.example .env; \
	fi
	@if [ ! -d $(VENV) ]; then \
		echo "Создаю виртуальное окружение..."; \
		python3 -m venv $(VENV); \
	fi

install: setup
	@echo "Активация окружения и обновление pip..."
	source $(VENV_BIN)/activate && \
	$(PYTHON) -m pip install --upgrade pip
	@echo "Установка зависимостей проекта..."
	source $(VENV_BIN)/activate && \
	$(PIP) install -e ".[dev]"

run: setup
	@echo "Останавливаю процесс на порту 8000, если он существует..."
	@kill -9 $$(lsof -t -i:8000) 2>/dev/null || true
	@echo "Запуск сервера на http://127.0.0.1:8000..."
	@if [ "$$(uname)" = "Darwin" ]; then \
		open http://127.0.0.1:8000; \
	elif [ "$$(expr substr $$(uname -s) 1 5)" = "Linux" ]; then \
		xdg-open http://127.0.0.1:8000 > /dev/null 2>&1 & \
	elif [ "$$(expr substr $$(uname -s) 1 10)" = "MINGW32_NT" ] || [ "$$(expr substr $$(uname -s) 1 10)" = "MINGW64_NT" ]; then \
		start http://127.0.0.1:8000; \
	fi
	source $(VENV_BIN)/activate && $(UVICORN) $(APP_MODULE) --reload

test:
	source $(VENV_BIN)/activate && $(PYTEST)

lint:
	source $(VENV_BIN)/activate && $(RUFF) check .

format:
	source $(VENV_BIN)/activate && $(RUFF) format .

clean:
	rm -rf `find . -name __pycache__`
	rm -f `find . -type f -name "*.py[co]"`
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf *.egg-info
	rm -rf dist
	rm -rf build
