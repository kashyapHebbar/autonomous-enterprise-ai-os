PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3.11; fi)

.PHONY: install test lint format smoke demo dev up down

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src tests scripts

format:
	$(PYTHON) -m ruff format src tests scripts

smoke:
	$(PYTHON) scripts/smoke_check.py

demo:
	PYTHONPATH=src $(PYTHON) scripts/run_procurement_demo.py

dev:
	PYTHONPATH=src $(PYTHON) -m uvicorn aeai_os.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000

up:
	docker compose up --build

down:
	docker compose down --remove-orphans
