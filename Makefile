# Chromecast Web — developer tasks.  Run `make help`.
SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON   ?= python3
VENV     := backend/.venv
VPY      := $(VENV)/bin/python
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 3000

.PHONY: help setup setup-backend setup-frontend browsers dev dev-backend dev-frontend serve \
        test test-backend test-browser test-frontend lint build docker docker-up clean \
        demo screenshots brand

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

setup: setup-backend setup-frontend ## Install backend venv + frontend node_modules

setup-backend: ## Create backend/.venv and install deps (incl. dev)
	test -x $(VPY) || $(PYTHON) -m venv $(VENV)
	$(VPY) -m pip install -U pip
	$(VPY) -m pip install -r backend/requirements-dev.txt
	$(VPY) -m pip install --no-deps -e backend

setup-frontend: ## npm ci in frontend/
	cd frontend && npm ci

browsers: ## Install Playwright Chromium (needed for web pages, remote browser, browser tests)
	cd backend && .venv/bin/playwright install chromium

dev: ## Backend (CAST_DRIVER=fake, :8000) + Next dev server (:3000) together
	@trap 'kill 0' INT TERM EXIT; \
	$(MAKE) --no-print-directory dev-backend & \
	$(MAKE) --no-print-directory dev-frontend & \
	wait

dev-backend: ## Backend only, fake Chromecast, auto-reload
	cd backend && CAST_DRIVER=$${CAST_DRIVER:-fake} DATA_DIR=$${DATA_DIR:-./data} \
		.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port $(BACKEND_PORT)

dev-frontend: ## Next dev server on the LAN (:3000); API = same host the page is opened from, backend port
	cd frontend && NEXT_PUBLIC_API_PORT=$(BACKEND_PORT) npx next dev -H 0.0.0.0 -p $(FRONTEND_PORT)

serve: build ## Production-like: backend serving the static export on :8000 (fake driver)
	cd backend && CAST_DRIVER=$${CAST_DRIVER:-fake} FRONTEND_DIR=../frontend/out .venv/bin/python -m app

test: test-backend test-frontend ## Run ALL checks (backend pytest + ruff, frontend typecheck/lint/test/build)

test-backend: ## pytest (incl. @browser tests when Chromium is installed) + ruff
	cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .

test-browser: ## Only the real-Chromium integration tests
	cd backend && .venv/bin/pytest -q -m browser

test-frontend: ## typecheck, lint, vitest, static build
	cd frontend && npm run typecheck && npm run lint && npm test && npm run build

lint: ## ruff + eslint
	cd backend && .venv/bin/ruff check .
	cd frontend && npm run lint

build: ## Static export of the frontend into frontend/out
	cd frontend && npm run build

demo: build ## Fake Chromecast + fictional demo data (playlists, history, a live stream) on :8000
	cd backend && .venv/bin/python scripts/demo.py --port $(BACKEND_PORT)

screenshots: build ## Regenerate docs/screenshots/*.png and docs/assets/hero.png (runs its own demo)
	$(VPY) -m pip install -q pillow
	cd backend && .venv/bin/python scripts/screenshots.py

brand: ## Render icons, favicon and social preview from docs/assets/icon*.svg
	$(VPY) -m pip install -q pillow
	cd backend && .venv/bin/python scripts/brand.py

docker: ## Build the Docker image
	docker build -t chromecast-web:latest .

docker-up: ## docker compose up (host network)
	docker compose up -d --build

clean: ## Remove build artifacts and caches
	rm -rf frontend/.next frontend/out backend/.pytest_cache backend/.ruff_cache
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +
