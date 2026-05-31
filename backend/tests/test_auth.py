"""Tests for the authentication module."""

from datetime import UTC

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth import (
    UserManager,
    create_access_token,
    decode_access_token,
)


@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path / "data"


class TestUserManager:
    def test_create_user(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        user = um.create_user("testuser", "password123")
        assert user.username == "testuser"
        assert user.is_admin is False
        assert user.created_at != ""

    def test_create_admin(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        user = um.create_user("admin", "password", is_admin=True)
        assert user.is_admin is True

    def test_create_duplicate_user(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        um.create_user("testuser", "password")
        with pytest.raises(ValueError, match="already exists"):
            um.create_user("testuser", "password2")

    def test_create_user_case_insensitive(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        um.create_user("TestUser", "password")
        with pytest.raises(ValueError, match="already exists"):
            um.create_user("testuser", "password2")

    def test_username_too_short(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        with pytest.raises(ValueError, match="3-20"):
            um.create_user("ab", "password")

    def test_username_too_long(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        with pytest.raises(ValueError, match="3-20"):
            um.create_user("a" * 21, "password")

    def test_username_invalid_chars(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        with pytest.raises(ValueError, match="alphanumeric"):
            um.create_user("user@name", "password")

    def test_authenticate_success(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        um.create_user("testuser", "password123")
        user = um.authenticate("testuser", "password123")
        assert user is not None
        assert user.username == "testuser"

    def test_authenticate_wrong_password(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        um.create_user("testuser", "password123")
        user = um.authenticate("testuser", "wrongpass")
        assert user is None

    def test_authenticate_nonexistent_user(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        user = um.authenticate("nobody", "password")
        assert user is None

    def test_persistence(self, tmp_data_dir):
        um1 = UserManager(data_dir=str(tmp_data_dir))
        um1.create_user("testuser", "password")

        um2 = UserManager(data_dir=str(tmp_data_dir))
        assert um2.get_user("testuser") is not None

    def test_list_users(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        um.create_user("alice", "pass1")
        um.create_user("bob_2", "pass2", is_admin=True)
        users = um.list_users()
        assert len(users) == 2
        names = [u.username for u in users]
        assert "alice" in names
        assert "bob_2" in names

    def test_delete_user(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        um.create_user("testuser", "password")
        assert um.delete_user("testuser") is True
        assert um.get_user("testuser") is None

    def test_delete_nonexistent(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        assert um.delete_user("nobody") is False

    def test_change_password(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        um.create_user("testuser", "oldpass")
        um.change_password("testuser", "newpass")
        assert um.authenticate("testuser", "oldpass") is None
        assert um.authenticate("testuser", "newpass") is not None

    def test_creates_user_data_dir(self, tmp_data_dir):
        um = UserManager(data_dir=str(tmp_data_dir))
        um.create_user("testuser", "password")
        user_dir = tmp_data_dir / "users" / "testuser"
        assert user_dir.exists()


class TestJWT:
    def test_create_and_decode(self):
        secret = "test-secret-key"
        token = create_access_token("testuser", secret)
        data = decode_access_token(token, secret)
        assert data is not None
        assert data.username == "testuser"

    def test_invalid_token(self):
        data = decode_access_token("invalid.token.here", "secret")
        assert data is None

    def test_wrong_secret(self):
        token = create_access_token("testuser", "secret1")
        data = decode_access_token(token, "secret2")
        assert data is None

    def test_expired_token(self):
        from datetime import datetime, timedelta

        import jwt as pyjwt

        secret = "test-secret"
        payload = {
            "sub": "testuser",
            "exp": datetime.now(UTC) - timedelta(hours=1),
        }
        token = pyjwt.encode(payload, secret, algorithm="HS256")
        data = decode_access_token(token, secret)
        assert data is None


@pytest_asyncio.fixture
async def auth_client(tmp_path):
    """Client with auth infrastructure set up."""
    from backend.main import app

    data_dir = str(tmp_path / "data")
    um = UserManager(data_dir=data_dir)
    um.create_user("testuser", "testpass")
    um.create_user("adminuser", "adminpass", is_admin=True)

    jwt_secret = "test-secret-for-integration"

    app.state.jwt_secret = jwt_secret
    app.state.user_manager = um
    app.state.user_state_managers = {}
    app.state.data_dir = data_dir
    app.state.claude_handler = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
class TestAuthAPI:
    async def test_login_success(self, auth_client):
        resp = await auth_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "testpass"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["username"] == "testuser"
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, auth_client):
        resp = await auth_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "wrong"},
        )
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, auth_client):
        resp = await auth_client.post(
            "/api/auth/login",
            data={"username": "nobody", "password": "pass"},
        )
        assert resp.status_code == 401

    async def test_protected_route_no_token(self, auth_client):
        resp = await auth_client.get("/game_state")
        assert resp.status_code == 401

    async def test_protected_route_with_token(self, auth_client):
        # Login first
        login_resp = await auth_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "testpass"},
        )
        token = login_resp.json()["access_token"]

        resp = await auth_client.get(
            "/game_state",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    async def test_me_endpoint(self, auth_client):
        login_resp = await auth_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "testpass"},
        )
        token = login_resp.json()["access_token"]

        resp = await auth_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"
        assert data["is_admin"] is False

    async def test_admin_list_users(self, auth_client):
        login_resp = await auth_client.post(
            "/api/auth/login",
            data={"username": "adminuser", "password": "adminpass"},
        )
        token = login_resp.json()["access_token"]

        resp = await auth_client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["users"]) == 2

    async def test_admin_route_non_admin(self, auth_client):
        login_resp = await auth_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "testpass"},
        )
        token = login_resp.json()["access_token"]

        resp = await auth_client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
