from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from travel_agent.agent.memory import open_memory
from travel_agent.api.admin import router as admin_router
from travel_agent.settings import settings

JID = "5511999999999@s.whatsapp.net"


def _client(tmp_path, monkeypatch, token: str):
    monkeypatch.setattr(settings, "admin_token", token)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with open_memory(tmp_path / "agent.sqlite") as memory:
            app.state.memory = memory
            yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(admin_router, prefix="/v1")
    return TestClient(app)


def test_admin_reset_clears_thread(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, "secret") as client:
        memory = client.app.state.memory
        memory.prefs.update(JID, home_city="Palmas")
        memory.trips.update(JID, origin="Palmas", destination="Santiago, Chile")

        response = client.delete(
            f"/v1/admin/threads/{JID}",
            headers={"Authorization": "Bearer secret"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "thread_id": JID}
        assert memory.prefs.get(JID) == {}
        assert memory.trips.get(JID) == {}

        again = client.delete(
            f"/v1/admin/threads/{JID}",
            headers={"Authorization": "Bearer secret"},
        )
        assert again.status_code == 200


def test_admin_reset_rejects_wrong_or_missing_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, "secret") as client:
        missing = client.delete(f"/v1/admin/threads/{JID}")
        assert missing.status_code == 401
        wrong = client.delete(
            f"/v1/admin/threads/{JID}",
            headers={"Authorization": "Bearer nope"},
        )
        assert wrong.status_code == 401


def test_admin_reset_rejects_when_token_not_configured(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, "") as client:
        response = client.delete(
            f"/v1/admin/threads/{JID}",
            headers={"Authorization": "Bearer anything"},
        )
        assert response.status_code == 401
