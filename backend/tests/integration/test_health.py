"""Integration tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Environment, Settings
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        secret_key="test-secret-key-at-least-32-characters-long",
        database_url="postgresql+asyncpg://ifnotus:ifnotus@localhost:5432/ifnotus_test",
        redis_url="redis://localhost:6379/1",
        environment=Environment.TESTING,
        debug=True,
    )


@pytest.fixture
async def client(test_settings: Settings):
    app = create_app(test_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_liveness(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
