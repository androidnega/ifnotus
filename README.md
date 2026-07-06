# IFNOTUS — Infrastructure and Operations Platform

A production-grade platform combining infrastructure monitoring, server management, deployment automation, application management, and email administration.

## Architecture Overview

```
ifnotUs/
├── backend/                    # Python 3.13+ / FastAPI
│   ├── app/
│   │   ├── api/                # Dependency injection, API assembly
│   │   │   ├── deps.py         # FastAPI Depends wiring
│   │   │   └── v1/             # API v1 router aggregation
│   │   ├── core/               # Cross-cutting concerns
│   │   │   ├── config.py       # Pydantic Settings
│   │   │   ├── container.py    # DI container (dependency-injector)
│   │   │   ├── database.py     # SQLAlchemy engine/session
│   │   │   ├── security.py     # JWT, password hashing
│   │   │   ├── permissions.py  # RBAC roles & permissions
│   │   │   ├── exceptions.py   # Error hierarchy
│   │   │   ├── logging.py      # structlog configuration
│   │   │   ├── events.py       # Lifespan startup/shutdown
│   │   │   └── openapi.py      # OpenAPI customization
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── schemas/            # Pydantic v2 request/response DTOs
│   │   ├── repositories/       # Data access layer
│   │   ├── services/           # Business logic layer
│   │   ├── routers/            # HTTP route handlers (by version)
│   │   │   └── v1/
│   │   │       ├── auth.py
│   │   │       ├── health.py
│   │   │       └── monitoring.py
│   │   ├── workers/            # Background task processing
│   │   ├── plugins/            # Extensible plugin system
│   │   ├── integrations/       # External system adapters
│   │   │   ├── nginx/
│   │   │   ├── netdata/
│   │   │   ├── git/
│   │   │   ├── github/
│   │   │   ├── supervisor/
│   │   │   └── systemd/
│   │   ├── utils/              # Shared utilities
│   │   └── main.py             # Application factory
│   ├── alembic/                # Database migrations
│   └── tests/
├── frontend/                   # Vue 3 / Vite / TypeScript
│   └── src/
│       ├── api/                # HTTP client & API modules
│       ├── stores/             # Pinia state management
│       ├── router/             # Vue Router
│       ├── views/              # Page components
│       ├── composables/        # Reusable composition functions
│       └── types/              # TypeScript interfaces
├── docker-compose.yml
└── .env.example
```

## Layer Responsibilities

| Layer | Responsibility |
|-------|----------------|
| **routers** | HTTP endpoints, request validation, response serialization |
| **services** | Business logic, orchestration, authorization checks |
| **repositories** | Database queries, CRUD operations |
| **schemas** | Pydantic DTOs for API contracts |
| **models** | SQLAlchemy ORM entities |
| **integrations** | External system adapters (Nginx, Netdata, GitHub, etc.) |
| **workers** | Async background task execution via Redis queue |
| **plugins** | Runtime-extensible capabilities |

## Request Flow

```
HTTP Request
    → Middleware (CORS, Request ID, Logging)
    → Router (routers/v1/)
    → Dependencies (api/deps.py)
    → Service (services/)
    → Repository (repositories/)
    → Database (PostgreSQL)
```

## Quick Start

### Prerequisites

- Python 3.13+
- Node.js 22+
- Docker & Docker Compose (recommended)

### Development with Docker

```bash
cp .env.example .env
docker compose up -d
```

- API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Frontend: http://localhost:5173

### Local Development

**Backend:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env
alembic upgrade head
uvicorn app.main:app --reload
```

**Worker:**

```bash
python -m app.workers.cli
```

**Frontend:**

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## API Endpoints (Skeleton)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Liveness probe |
| GET | `/api/v1/health/ready` | Readiness probe (DB + Redis) |
| POST | `/api/v1/auth/login` | JWT authentication |
| POST | `/api/v1/auth/refresh` | Token refresh |
| GET | `/api/v1/auth/me` | Current user profile |
| GET | `/api/v1/monitoring/metrics` | System metrics |
| GET | `/api/v1/monitoring/integrations` | Integration status |

## Configuration

All settings are managed via environment variables (see `.env.example`). The `Settings` class in `app/core/config.py` uses Pydantic Settings with validation.

## Authentication & Authorization

- **JWT** access + refresh token pairs
- **RBAC** with roles: `superadmin`, `admin`, `operator`, `viewer`
- Permission-based endpoint guards via `RequirePermission` dependency
- Passkeys support planned for future release

## Background Tasks

Tasks are enqueued to Redis and processed by worker processes:

```python
from app.workers.base import BaseTask, TaskContext, TaskResult

class MyTask(BaseTask):
    name = "my_task"

    async def execute(self, payload, context: TaskContext) -> TaskResult:
        ...
```

## Plugin System

Plugins implement `PluginBase` and are auto-discovered at startup:

```python
class Plugin(PluginBase):
    metadata = PluginMetadata(name="my-plugin", version="1.0.0", ...)

    async def on_load(self): ...
    async def on_unload(self): ...
    def get_routers(self): ...
```

## Database Migrations

```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## License

Proprietary — All rights reserved.
