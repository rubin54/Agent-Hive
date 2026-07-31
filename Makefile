.PHONY: help install dev backend frontend sync demo demo-checks templates image test lint typecheck check types clean

PY := backend/.venv/Scripts/python.exe
ifeq ($(OS),)
	PY := backend/.venv/bin/python
endif

API_PORT ?= 8000

help:
	@echo "install      Set up dependencies for backend and frontend"
	@echo "backend      Start FastAPI (API_PORT=$(API_PORT))"
	@echo "frontend     Start the Vite dev server"
	@echo "sync         Fetch the model catalog from OpenRouter (no API key needed)"
	@echo "demo         Replay a recorded agent run in a real sandbox"
	@echo "demo-checks  Show the full evaluation chain on minecraft-clone"
	@echo "templates    List the available task templates"
	@echo "image        Build the sandbox and checker images (otherwise done on first run)"
	@echo "check        Lint, typecheck and tests for both sides"
	@echo "types        Generate the TypeScript types from the OpenAPI schema"

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

# Needs Docker but no API key: the mock provider replaces only the model call, while
# sandbox, tools and loop are the same as in live operation.
demo:
	cd backend && .venv/Scripts/python -m hive.cli run --provider mock -v

demo-checks:
	cd backend && .venv/Scripts/python -m hive.cli run --template minecraft-clone --provider mock

templates:
	cd backend && .venv/Scripts/python -m hive.cli template list

image:
	docker build -f docker/node-web.Dockerfile -t hive/node-web:1 docker
	docker build -f docker/playwright-checker.Dockerfile -t hive/playwright-checker:1 docker

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
