PYTHON ?= python3.11

.PHONY: install test lint format smoke dev up down

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

lint:
	ruff check src tests scripts

format:
	ruff format src tests scripts

smoke:
	$(PYTHON) scripts/smoke_check.py

dev:
	uvicorn aeai_os.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000

up:
	docker compose up --build

down:
	docker compose down --remove-orphans
