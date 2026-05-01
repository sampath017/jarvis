import pytest
from httpx import AsyncClient, ASGITransport
import sys
import os

# Add src to python path so it can import main
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from src.main import app

@pytest.mark.asyncio
async def test_create_task():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/tasks", json={
            "id": "test-auto-1",
            "title": "Automated Backend Task",
            "category": "work"
        })
    assert response.status_code == 200
    assert response.json()["title"] == "Automated Backend Task"

@pytest.mark.asyncio
async def test_get_tasks():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/tasks")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert any(t["id"] == "test-auto-1" for t in response.json())

@pytest.mark.asyncio
async def test_update_task():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.put("/tasks/test-auto-1", json={"isCompleted": True})
    assert response.status_code == 200
    assert response.json()["isCompleted"] is True

@pytest.mark.asyncio
async def test_delete_task():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.delete("/tasks/test-auto-1")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
