PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3.11; fi)

.PHONY: install test lint format smoke demo k8s-validate db-upgrade db-validate dev up down

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src tests scripts

format:
	$(PYTHON) -m ruff format src tests scripts

smoke:
	$(PYTHON) scripts/smoke_check.py

demo:
	PYTHONPATH=src $(PYTHON) scripts/run_procurement_demo.py

k8s-validate:
	$(PYTHON) scripts/validate_kubernetes_manifests.py deploy/kubernetes
	$(PYTHON) scripts/validate_kubernetes_manifests.py deploy/kubernetes/overlays/local
	$(PYTHON) scripts/validate_kubernetes_manifests.py deploy/kubernetes/overlays/staging
	$(PYTHON) scripts/validate_kubernetes_manifests.py deploy/kubernetes/overlays/production

db-upgrade:
	PYTHONPATH=src $(PYTHON) scripts/manage_database.py upgrade

db-validate:
	PYTHONPATH=src $(PYTHON) scripts/manage_database.py validate

dev:
	PYTHONPATH=src $(PYTHON) -m uvicorn aeai_os.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000

up:
	docker compose up --build

down:
	docker compose down --remove-orphans
