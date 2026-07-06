.PHONY: dev dev-local up down migrate seed-admin setup-local test lint install install-backend install-frontend backend frontend

dev:
	docker compose up

dev-local:
	@echo "Starting IFNOTUS locally (backend :8000, frontend :5173)..."
	@echo "Run in separate terminals:"
	@echo "  make backend"
	@echo "  make frontend"

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

seed-admin:
	cd backend && . .venv/bin/activate && ifnotus-seed-admin admin admin123

setup-local: migrate seed-admin
	@echo "Database migrated and admin user ready (admin / admin123)"

up:
	docker compose up -d

down:
	docker compose down

migrate:
	cd backend && alembic upgrade head

test:
	cd backend && pytest

lint:
	cd backend && ruff check app tests
	cd frontend && npm run lint

install-backend:
	cd backend && pip install -e ".[dev]"

install-frontend:
	cd frontend && npm install

install: install-backend install-frontend
