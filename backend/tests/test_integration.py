"""Integration tests for the FastAPI endpoints."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth import UserManager, create_access_token


@pytest_asyncio.fixture
async def client(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from backend.main import app

    data_dir = str(tmp_path / "data")
    jwt_secret = "test-secret-key-for-integration"

    # Set up auth infrastructure
    um = UserManager(data_dir=data_dir)
    um.create_user("testuser", "testpass")

    app.state.jwt_secret = jwt_secret
    app.state.user_manager = um
    app.state.user_state_managers = {}
    app.state.data_dir = data_dir
    app.state.claude_handler = None

    token = create_access_token("testuser", jwt_secret)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


@pytest.mark.asyncio
class TestAPI:
    async def test_get_game_state(self, client):
        resp = await client.get("/game_state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["day_number"] == 1
        assert "current_location" in data
        assert data["has_history"] is False
        assert data["last_scene"] is None
        # New fields
        assert "time" in data
        assert data["time"]["day"] == 1
        assert data["time"]["hour"] == 14
        assert "affection" in data
        assert "tone" in data["affection"]
        assert data["affection"]["tone"] == "neutral"
        assert "learning" in data
        assert data["learning"]["overall_level"] == "N5"

    async def test_reset_game_state(self, client):
        resp = await client.post("/game_state/reset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["day_number"] == 1
        assert data["has_history"] is False
        assert data["last_scene"] is None
        assert data["time"]["day"] == 1
        assert data["affection"]["tone"] == "neutral"

    async def test_get_available_assets(self, client):
        resp = await client.get("/api/assets/available")
        assert resp.status_code == 200
        data = resp.json()
        assert "characters" in data
        assert "backgrounds" in data

    async def test_generate_scene_no_api_key(self, client):
        resp = await client.post(
            "/generate_scene",
            json={"user_input": "hello"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "API" in data["dialog_de"] or "api" in data["dialog_de"].lower()
        assert len(data["parse_errors"]) > 0
        # New fields should be present
        assert "aoi_affection" in data
        assert "time" in data

    async def test_unauthenticated_returns_401(self, client):
        resp = await client.get("/game_state", headers={"Authorization": ""})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestSaveSlotAPI:
    async def test_list_save_slots_empty(self, client):
        resp = await client.get("/api/save_slots")
        assert resp.status_code == 200
        data = resp.json()
        assert data["slots"] == []

    async def test_save_to_slot(self, client):
        resp = await client.post(
            "/api/save_slots/1",
            json={"name": "Test Save"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["slot_id"] == 1
        assert data["name"] == "Test Save"
        assert data["day_number"] == 1

    async def test_save_and_list(self, client):
        await client.post("/api/save_slots/1", json={"name": "Save 1"})
        await client.post("/api/save_slots/3", json={"name": "Save 3"})

        resp = await client.get("/api/save_slots")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["slots"]) == 2
        ids = [s["slot_id"] for s in data["slots"]]
        assert 1 in ids
        assert 3 in ids

    async def test_load_from_slot(self, client):
        await client.post("/api/save_slots/1", json={"name": "Slot 1"})

        resp = await client.post("/api/save_slots/1/load")
        assert resp.status_code == 200
        # The load endpoint returns the restored game state (GameStateResponse),
        # which the frontend consumes directly; it has no "success" flag.
        data = resp.json()
        assert data["day_number"] == 1
        assert "time" in data
        assert "affection" in data

    async def test_load_nonexistent_slot(self, client):
        resp = await client.post("/api/save_slots/5/load")
        assert resp.status_code == 404

    async def test_delete_slot(self, client):
        await client.post("/api/save_slots/2", json={"name": "Del Me"})
        resp = await client.delete("/api/save_slots/2")
        assert resp.status_code == 200

        resp = await client.get("/api/save_slots")
        assert len(resp.json()["slots"]) == 0

    async def test_delete_nonexistent_slot(self, client):
        resp = await client.delete("/api/save_slots/9")
        assert resp.status_code == 404

    async def test_save_slot_invalid_id(self, client):
        resp = await client.post("/api/save_slots/0", json={"name": "Bad"})
        assert resp.status_code == 400

        resp = await client.post("/api/save_slots/10", json={"name": "Bad"})
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestSceneHistoryAPI:
    async def test_scene_history_empty(self, client):
        resp = await client.get("/api/scene_history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenes"] == []

    async def test_scene_history_after_generate(self, client):
        await client.post("/generate_scene", json={"user_input": "hello"})

        resp = await client.get("/api/scene_history")
        assert resp.status_code == 200
