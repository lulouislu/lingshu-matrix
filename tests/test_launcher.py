import asyncio
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from macnet import cli
from macnet.app import create_app


def test_reserved_socket_is_exclusive_and_closed_after_use():
    with cli.reserve_listener(("127.0.0.1", 0)) as first:
        with pytest.raises(OSError):
            cli.reserve_listener(first.getsockname())


@pytest.mark.parametrize("health,marker,expected", [
    ({"product": "macnet-lab", "status": "ok", "instance": "a" * 32}, "a" * 32, True),
    ({"product": "macnet-lab", "status": "ok", "instance": "b" * 32}, "a" * 32, False),
    ({"product": "foreign-service", "status": "ok", "instance": "a" * 32}, "a" * 32, False),
    ({"status": "ok", "version": "0.1.0"}, "a" * 32, False),
    ({"product": "macnet-lab", "status": "ok", "instance": ""}, "", False),
])
def test_duplicate_handshake_requires_this_launch_and_directory(tmp_path, monkeypatch, health, marker, expected):
    (tmp_path / "runtime.json").write_text(json.dumps({"instance": marker}), encoding="utf-8")
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(health).encode()
    opener = Mock()
    opener.open.return_value = response
    build = Mock(return_value=opener)
    monkeypatch.setattr(cli.urllib.request, "build_opener", build)
    assert cli.existing_instance(tmp_path, timeout=0) is expected
    assert isinstance(build.call_args.args[0], cli.urllib.request.ProxyHandler)
    assert build.call_args.args[0].proxies == {}


def test_port_conflict_does_not_create_data_or_open_foreign_page(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "reserve_listener", Mock(side_effect=OSError("occupied")))
    monkeypatch.setattr(cli, "existing_instance", Mock(return_value=False))
    browser = Mock()
    monkeypatch.setattr(cli, "open_browser", browser)
    with pytest.raises(RuntimeError, match="8765"):
        cli.run(tmp_path / "new-data")
    browser.assert_not_called()
    assert not (tmp_path / "new-data").exists()


def test_duplicate_opens_existing_without_creating_app(tmp_path, monkeypatch):
    import macnet.app
    create = Mock()
    browser = Mock()
    monkeypatch.setattr(macnet.app, "create_app", create)
    monkeypatch.setattr(cli, "reserve_listener", Mock(side_effect=OSError("occupied")))
    monkeypatch.setattr(cli, "existing_instance", Mock(return_value=True))
    monkeypatch.setattr(cli, "open_browser", browser)
    assert cli.run(tmp_path) == 0
    browser.assert_called_once()
    create.assert_not_called()


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_browser_opens_only_after_server_startup(tmp_path, monkeypatch, platform):
    import uvicorn
    import macnet.app
    # Reserve with the host's real socket options before simulating another OS.
    listener = cli.reserve_listener(("127.0.0.1", 0))
    create = Mock(side_effect=macnet.app.create_app)
    monkeypatch.setattr(macnet.app, "create_app", create)
    monkeypatch.setattr(cli.sys, "platform", platform)
    browser = Mock()
    monkeypatch.setattr(cli, "open_browser", browser)

    class InlineThread:
        def __init__(self, *, target, daemon):
            assert daemon
            self.target = target
        def start(self):
            self.target()

    async def startup(server, sockets):
        browser.assert_not_called()
        assert sockets[0].getsockname()[0] == "127.0.0.1"
        server.started = True

    def serve(server, sockets):
        asyncio.run(server.startup(sockets))

    monkeypatch.setattr(cli, "reserve_listener", lambda: listener)
    monkeypatch.setattr(cli.threading, "Thread", InlineThread)
    monkeypatch.setattr(uvicorn.Server, "startup", startup)
    monkeypatch.setattr(uvicorn.Server, "run", serve)
    assert cli.run(tmp_path) == 0
    browser.assert_called_once()
    assert callable(create.call_args.kwargs["shutdown"]) is (platform == "win32")


def test_shutdown_requires_session_and_confirmation_header(tmp_path):
    stop = Mock()
    with TestClient(create_app(tmp_path, instance_id="launch", shutdown=stop), base_url=cli.URL) as client:
        assert client.get("/api/health").json()["instance"] == "launch"
        assert client.post("/api/shutdown", json={}).status_code == 401
        client.get("/api/session")
        assert client.post("/api/shutdown", json={}).status_code == 403
        assert client.post("/api/shutdown", json={}, headers={"X-MacNet": "1", "Origin": "https://evil.example"}).status_code == 403
        stop.assert_not_called()
        assert client.post("/api/shutdown", json={}, headers={"X-MacNet": "1"}).status_code == 200
        stop.assert_called_once()


def test_embedded_app_cannot_stop_external_service(tmp_path):
    with TestClient(create_app(tmp_path), base_url=cli.URL) as client:
        client.get("/api/session")
        assert client.post("/api/shutdown", json={}, headers={"X-MacNet": "1"}).status_code == 409


def test_frozen_start_error_without_console_input_returns_failure(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.sys, "frozen", True, raising=False)
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli.sys, "argv", ["MacNetLab.exe", "--no-browser", "--data-dir", str(tmp_path)])
    monkeypatch.setattr(cli, "run", Mock(side_effect=RuntimeError("occupied")))
    monkeypatch.setattr("builtins.input", Mock(side_effect=EOFError))
    assert cli.main() == 1
    assert "occupied" in capsys.readouterr().err
