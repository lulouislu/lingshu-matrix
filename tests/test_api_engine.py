import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from macnet.app import create_app
from macnet.engine import Engine
from macnet.models import Device, Probe, Result, Site
from macnet.store import Store


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        c.get("/api/session")
        c.headers["X-MacNet"] = "1"
        yield c


def test_session_origin_and_host_protection(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8765") as c:
        assert c.get("/api/state").status_code == 401
        c.get("/api/session")
        assert c.post("/api/monitoring", json={"enabled": False}).status_code == 403
        assert c.get("/api/state", headers={"Origin": "https://attacker.example"}).status_code == 403
        assert c.get("/api/state", headers={"Host": "attacker.example"}).status_code == 403


def test_default_does_not_probe_network(client):
    state = client.get("/api/state").json()
    assert state["monitoring"] is False
    assert not any(p["enabled"] for p in state["active_site"]["probes"])
    assert not client.get(f"/api/sites/{state['active_site']['id']}/history").json()


def test_site_save_conflict_and_import_sanitization(client):
    body = client.get("/api/state").json()["active_site"]
    body["devices"][0]["credential_ref"] = "hidden"
    body["probes"][0]["enabled"] = True
    saved = client.post("/api/sites", json=body)
    assert saved.status_code == 200
    assert client.post("/api/sites", json=body).status_code == 409
    exported = client.get(f"/api/sites/{body['id']}/export").json()
    assert not exported["devices"][0]["credential_ref"]
    assert not exported["probes"][0]["enabled"]
    imported = client.post("/api/import", json=body).json()
    assert imported["id"] != body["id"]
    assert not imported["devices"][0]["credential_ref"]
    assert not imported["probes"][0]["enabled"]


def test_ai_integration_is_retired(client):
    for path in ("answer", "preview", "config"):
        response = client.post("/api/ai/" + path, json={"provider": "codex", "share_evidence": True})
        assert response.status_code == 410
    assert client.get("/api/ai/config").status_code == 410


def test_known_hosts_rejects_garbage(client):
    assert client.post("/api/known-hosts", json={"text": "garbage"}).status_code == 400
    assert client.post("/api/known-hosts", json={"text": "# empty"}).status_code == 400


def test_retention(client):
    assert client.post("/api/retention", json={"days": 2}).status_code == 200
    assert client.get("/api/state").json()["retention_days"] == 2
    assert client.post("/api/retention", json={"days": 0}).status_code == 422


def test_websocket_session_accepts_local_and_rejects_other_origins(client):
    from starlette.websockets import WebSocketDisconnect
    with client.websocket_connect("ws://127.0.0.1:8765/api/live"):
        pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1:8765/api/live", headers={"origin": "https://attacker.invalid"}):
            pass


def test_switch_site_stops_monitoring(client):
    assert client.post("/api/monitoring", json={"enabled": True}).status_code == 200
    assert client.get("/api/state").json()["monitoring"]
    new_site = client.post("/api/templates/empty", json={}).json()
    assert client.post("/api/active/" + new_site["id"], json={}).status_code == 200
    assert not client.get("/api/state").json()["monitoring"]


@pytest.mark.asyncio
async def test_failure_dedup_recovery_and_unknown(tmp_path):
    store = Store(tmp_path)
    site = store.save(Site(id="lab", name="Lab", devices=[Device(id="router", label="Router")], probes=[Probe(id="check", device_id="router", label="Check", kind="tcp")]))
    mock = AsyncMock()
    mock.run.side_effect = [Result(status=s, message=s) for s in ("failed", "failed", "failed", "unknown", "healthy", "healthy")]
    engine = Engine(store, mock)
    for _ in range(3):
        await engine.check(site, site.probes[0])
    incidents = store.incidents("lab")
    assert len(incidents) == 1 and incidents[0]["status"] == "open"
    assert store.evidence(incidents[0]["id"])[0]["body"]["phase"] == "failure"
    assert store.evidence(incidents[0]["id"])[0]["body"]["topology"]["id"] == "lab"
    await engine.check(site, site.probes[0])
    assert store.incidents("lab")[0]["status"] == "open"
    await engine.check(site, site.probes[0])
    assert store.incidents("lab")[0]["status"] == "open"
    await engine.check(site, site.probes[0])
    assert store.incidents("lab")[0]["status"] == "resolved"


def test_large_snapshot_stays_valid_json(tmp_path):
    store = Store(tmp_path)
    incident = store.open_incident("lab", "check", {})
    rows = store.evidence(incident, {"huge": "x" * 200000})
    assert rows[0]["body"]["truncated"]
