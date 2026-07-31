.PHONY: help install dev backend frontend sync demo image test lint typecheck check types clean

PY := backend/.venv/Scripts/python.exe
ifeq ($(OS),)
	PY := backend/.venv/bin/python
endif

API_PORT ?= 8000

help:
	@echo "install    Abhängigkeiten für Backend und Frontend einrichten"
	@echo "backend    FastAPI starten (API_PORT=$(API_PORT))"
	@echo "frontend   Vite-Dev-Server starten"
	@echo "sync       Modellkatalog von OpenRouter holen (kein API-Key nötig)"
	@echo "demo       Aufgezeichneten Agentenlauf in echter Sandbox abspielen"
	@echo "image      Sandbox-Image bauen (passiert sonst beim ersten Lauf)"
	@echo "check      Lint, Typecheck und Tests für beide Seiten"
	@echo "types      TypeScript-Typen aus dem OpenAPI-Schema generieren"

install:
	python -m venv backend/.venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "backend[dev]"
	npm install --prefix frontend

backend:
	$(PY) -m uvicorn hive.api.app:app --reload --port $(API_PORT) --app-dir backend

frontend:
	npm run dev --prefix frontend

sync:
	cd backend && .venv/Scripts/python -m hive.cli catalog sync

# Braucht Docker, aber keinen API-Key: Der Mock-Provider ersetzt nur den Modellaufruf,
# Sandbox, Werkzeuge und Loop sind dieselben wie im Echtbetrieb.
demo:
	cd backend && .venv/Scripts/python -m hive.cli run --provider mock -v

image:
	docker build -f docker/node-web.Dockerfile -t hive/node-web:1 docker

test:
	cd backend && .venv/Scripts/python -m pytest -q
	npm run test --prefix frontend

lint:
	cd backend && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .

typecheck:
	cd backend && .venv/Scripts/python -m mypy hive
	npm run typecheck --prefix frontend

check: lint typecheck test

types:
	cd backend && .venv/Scripts/python -m hive.cli openapi --out ../openapi.json
	npm run types --prefix frontend

clean:
	rm -rf backend/.pytest_tmp backend/.ruff_cache backend/.mypy_cache frontend/dist
