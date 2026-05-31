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


@pytest_asyncio.fixture
async def admin_client(monkeypatch, tmp_path):
    """Client authenticated as an admin user, plus a plain-user token."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from backend.main import app

    data_dir = str(tmp_path / "data")
    jwt_secret = "test-secret-key-for-admin"

    um = UserManager(data_dir=data_dir)
    um.create_user("adminuser", "adminpass1", is_admin=True)
    um.create_user("plainuser", "plainpass1")

    app.state.jwt_secret = jwt_secret
    app.state.user_manager = um
    app.state.user_state_managers = {}
    app.state.data_dir = data_dir
    app.state.claude_handler = None

    admin_token = create_access_token("adminuser", jwt_secret)
    plain_token = create_access_token("plainuser", jwt_secret)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = f"Bearer {admin_token}"
        c.plain_headers = {"Authorization": f"Bearer {plain_token}"}
        yield c


@pytest.mark.asyncio
class TestAdminAndValidation:
    async def test_create_user_requires_admin(self, admin_client):
        resp = await admin_client.post(
            "/api/admin/users",
            json={"username": "newbie", "password": "secret123"},
            headers=admin_client.plain_headers,
        )
        assert resp.status_code == 403

    async def test_list_users_requires_admin(self, admin_client):
        resp = await admin_client.get("/api/admin/users", headers=admin_client.plain_headers)
        assert resp.status_code == 403

    async def test_create_user_weak_password_rejected(self, admin_client):
        resp = await admin_client.post(
            "/api/admin/users",
            json={"username": "newbie", "password": "short"},
        )
        assert resp.status_code == 400

    async def test_create_user_success(self, admin_client):
        resp = await admin_client.post(
            "/api/admin/users",
            json={"username": "newbie", "password": "strong123", "player_name": "Neu"},
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "newbie"

    async def test_player_name_empty_rejected(self, admin_client):
        resp = await admin_client.put("/api/player_name", json={"player_name": "  "})
        assert resp.status_code == 400

    async def test_player_name_too_long_rejected(self, admin_client):
        resp = await admin_client.put("/api/player_name", json={"player_name": "x" * 31})
        assert resp.status_code == 400

    async def test_scenario_empty_rejected(self, admin_client):
        resp = await admin_client.put("/api/scenario", json={"scenario": ""})
        assert resp.status_code == 400

    async def test_scenario_too_long_rejected(self, admin_client):
        resp = await admin_client.put("/api/scenario", json={"scenario": "x" * 5001})
        assert resp.status_code == 400

    async def test_tts_generate_unavailable(self, admin_client):
        # No TTS service configured on app.state → 503.
        resp = await admin_client.post("/api/tts/generate", json={"text": "こんにちは"})
        assert resp.status_code == 503
