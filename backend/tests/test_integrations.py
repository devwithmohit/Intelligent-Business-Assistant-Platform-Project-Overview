import asyncio
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import integration_manager as im


class DummyService:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def register_integration(self, name: str, cfg: Dict[str, Any]) -> None:
        # simulate a small async delay to surface await usage
        await asyncio.sleep(0)
        self.calls.append({"name": name, "cfg": cfg})


@pytest.fixture(autouse=True)
def reset_integration_manager_singleton():
    # Ensure singleton is reset between tests to avoid cross-test state
    im._default_integration_manager = None
    yield
    im._default_integration_manager = None


@pytest.mark.asyncio
async def test_register_and_list_and_get_config():
    manager = im.get_integration_manager()
    await manager.register_integration("my_unknown", {"name": "my_unknown", "type": "custom"})
    cfg = await manager.get_config("my_unknown")
    assert cfg is not None
    assert cfg["name"] == "my_unknown"
    lst = await manager.list_integrations()
    assert "my_unknown" in lst
    # deletion via direct store mutation to verify cleanup behavior
    async with manager._lock:
        manager._cfg.pop("my_unknown", None)
    assert await manager.get_config("my_unknown") is None


@pytest.mark.asyncio
async def test_register_routes_to_email_service(monkeypatch):
    dummy = DummyService()
    monkeypatch.setattr(im, "get_email_service", lambda: dummy)
    manager = im.get_integration_manager()
    cfg = {"name": "gmail_integ", "type": "gmail", "credentials": {"token": "x"}}
    await manager.register_integration("gmail_integ", cfg)
    # ensure the email service register hook was called
    assert len(dummy.calls) == 1
    assert dummy.calls[0]["name"] == "gmail_integ"
    assert dummy.calls[0]["cfg"]["type"] == "gmail"
    # stored config should be present
    stored = await manager.get_config("gmail_integ")
    assert stored is not None and stored["name"] == "gmail_integ"


@pytest.mark.asyncio
async def test_register_routes_to_calendar_and_get_handler(monkeypatch):
    dummy = DummyService()
    monkeypatch.setattr(im, "get_calendar_service", lambda: dummy)
    manager = im.get_integration_manager()
    cfg = {"name": "gcal", "type": "google_calendar"}
    await manager.register_integration("gcal", cfg)
    # handler resolution should return the same dummy object
    handler = await manager.get_handler("gcal")
    assert handler is dummy
    assert len(dummy.calls) == 1
    assert dummy.calls[0]["name"] == "gcal"


@pytest.mark.asyncio
async def test_unknown_provider_is_stored_but_no_service_called(monkeypatch):
    # do not patch any service; unknown provider should be stored without error
    manager = im.get_integration_manager()
    cfg = {"name": "weird", "type": "some_obscure_provider"}
    await manager.register_integration("weird", cfg)
    stored = await manager.get_config("weird")
    assert stored is not None
    assert stored["type"] == "some_obscure_provider"


def test_api_create_and_delete_integration_endpoints():
    # Use real FastAPI app router to exercise endpoints
    client = TestClient(app)
    # create
    payload = {"name": "api_integ", "type": "gmail", "extra": {"x": 1}}
    resp = client.post("/api/v1/integrations/", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "api_integ"
    assert body["config"]["name"] == "api_integ"
    # get
    resp = client.get("/api/v1/integrations/api_integ")
    assert resp.status_code == 200
    # delete
    resp = client.delete("/api/v1/integrations/api_integ")
    assert resp.status_code == 200
    assert resp.json().get("deleted") is True
    # subsequent get returns 404
    resp = client.get("/api/v1/integrations/api_integ")
    assert resp.status_code == 404