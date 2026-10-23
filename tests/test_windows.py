import asyncio
import json
import socket
import struct
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from macnet import platform, probes, windows
from macnet.models import Device, Probe, Site


def test_windows_option_uses_network_order(monkeypatch):
    monkeypatch.setattr(windows, "interface_index", lambda name: 17)
    assert windows.unicast_option("无线网卡 (测试)") == (socket.IPPROTO_IP, 31, b"\0\0\0\x11")


def test_bound_socket_dispatch_and_no_fallback(monkeypatch):
    created = Mock()
    monkeypatch.setattr(probes.socket, "socket", lambda *a: created)
    monkeypatch.setattr(probes.sys, "platform", "win32")
    monkeypatch.setattr(windows, "interface_index", lambda name: 17)
    assert probes.bound_socket(socket.SOCK_STREAM, "网卡") is created
    created.setsockopt.assert_called_once_with(socket.IPPROTO_IP, 31, struct.pack("!I", 17))
    created.setsockopt.side_effect = OSError("binding rejected")
    with pytest.raises(OSError, match="rejected"):
        probes.bound_socket(socket.SOCK_STREAM, "网卡")
    created.close.assert_called_once()


def test_mac_socket_contract_preserved(monkeypatch):
    monkeypatch.setattr(probes.sys, "platform", "darwin")
    monkeypatch.setattr(probes.socket, "if_nametoindex", lambda _: 4)
    assert probes.interface_options("en0") == [(socket.IPPROTO_IP, 25, 4)]


def test_windows_aliases_and_generic_computer_are_valid():
    Site(id="site", name="Lab", devices=[Device(id="pc", label="Windows laptop", kind="computer")],
         probes=[Probe(id="p", device_id="pc", label="TCP", kind="tcp", interface="Ethernet (USB-C) #2")])
    with pytest.raises(ValueError):
        Probe(id="p", device_id="pc", label="TCP", kind="tcp", interface="bad\nname")


@pytest.mark.asyncio
async def test_windows_network_and_printer_queries_are_fixed_and_structured():
    command = AsyncMock(return_value=(0, json.dumps([{"name": "无线网卡 (测试)", "index": 17}]), ""))
    data = await windows.network_metadata(command)
    assert data["无线网卡 (测试)"]["index"] == 17
    argv = command.call_args.args[0]
    assert "-EncodedCommand" in argv and "-NoProfile" in argv
    command.return_value = (0, json.dumps({"scheduler": {"exit_code": 0}, "printers": [], "queues": [], "usb": [], "unavailable": []}), "")
    data = await windows.printing_info(command)
    assert data["scheduler"]["exit_code"] == 0
    assert "任务标题" in data["note"]
    command.return_value = (1, "", "denied")
    assert (await windows.printing_info(command))["status"] == "unknown"
    assert "Get-PrintJob" not in windows.PRINT_QUERY
    assert "UserName" not in windows.PRINT_QUERY and "Document" not in windows.PRINT_QUERY


@pytest.mark.asyncio
async def test_windows_discovery_does_not_guess_from_alias(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(windows, "network_metadata", AsyncMock(return_value={
        "custom": {"name": "custom", "description": "Physical adapter", "index": 17, "hardware": True, "medium": 9, "dns": ["192.0.2.53"], "routes": [{"gateway": "192.0.2.1", "metric": 10}]},
        "vpn": {"name": "vpn", "description": "VPN", "index": 9, "hardware": False, "medium": 14, "dns": [], "routes": []}}))
    monkeypatch.setattr(platform.psutil, "net_if_stats", lambda: {k: SimpleNamespace(isup=True, speed=1000) for k in ("custom", "vpn")})
    monkeypatch.setattr(platform.psutil, "net_if_addrs", lambda: {k: [] for k in ("custom", "vpn")})
    monkeypatch.setattr(platform.psutil, "net_io_counters", lambda **_: {})
    monkeypatch.setattr(platform, "wifi_info", lambda _: {"available": False, "reason": "privacy denied"})
    result = await platform.observation()
    assert result["supported_platform"] is True and result["macos_supported"] is False
    physical, logical = result["interfaces"]
    assert physical["kind"] == "wifi" and physical["addresses"] == []
    assert physical["route"]["gateway"] == "192.0.2.1" and physical["dns_servers"] == ["192.0.2.53"]
    assert logical["kind"] == "logical"
    assert result["capabilities"]["interface_bound_ping"] == "unavailable"


@pytest.mark.asyncio
async def test_windows_bound_icmp_never_uses_default_or_dns(monkeypatch):
    monkeypatch.setattr(probes.sys, "platform", "win32")
    resolver = AsyncMock()
    monkeypatch.setattr(probes, "resolve", resolver)
    result = await probes.Probes(None, None).run(
        Probe(id="p", device_id="pc", label="ICMP", kind="ping", interface="Wi-Fi"),
        Device(id="pc", label="PC"), {"interfaces": [{"id": "Wi-Fi", "up": True}]})
    assert result.status == "unknown" and "TCP/DNS/HTTP" in result.message
    resolver.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows socket integration")
@pytest.mark.asyncio
async def test_native_windows_loopback_tcp_http_and_udp_binding():
    loopback = "Loopback Pseudo-Interface 1"
    # Resolve the actual localized loopback alias from the system index, not a hardcoded English label.
    import ctypes as ct
    from ctypes import wintypes as wt
    dll = ct.WinDLL("iphlpapi.dll")
    luid, alias = ct.c_ulonglong(), ct.create_unicode_buffer(257)
    dll.ConvertInterfaceIndexToLuid.argtypes = [wt.ULONG, ct.POINTER(ct.c_ulonglong)]
    dll.ConvertInterfaceLuidToAlias.argtypes = [ct.POINTER(ct.c_ulonglong), wt.LPWSTR, ct.c_size_t]
    assert dll.ConvertInterfaceIndexToLuid(1, ct.byref(luid)) == 0
    assert dll.ConvertInterfaceLuidToAlias(ct.byref(luid), alias, 257) == 0
    loopback = alias.value
    async def serve(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        assert await probes.direct_http_status(f"http://127.0.0.1:{port}/", loopback) == 204
    receiver = probes.bound_socket(socket.SOCK_DGRAM, loopback)
    sender = probes.bound_socket(socket.SOCK_DGRAM, loopback)
    try:
        assert sender.getsockopt(socket.IPPROTO_IP, 31) == 1
        receiver.bind(("127.0.0.1", 0))
        loop = asyncio.get_running_loop()
        await loop.sock_connect(sender, receiver.getsockname())
        await loop.sock_sendall(sender, b"bound-interface")
        packet = await asyncio.wait_for(loop.sock_recv(receiver, 100), 2)
        assert packet == b"bound-interface"
    finally:
        receiver.close();sender.close()


def test_windows_and_legacy_data_directory_selection(tmp_path, monkeypatch):
    from macnet import app
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(app.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("MACNET_DATA_DIR", raising=False)
    assert app.default_directory() == tmp_path / "local/MacNetLab"
    legacy = tmp_path / "home/Library/Application Support/MacNetLab"
    legacy.mkdir(parents=True)
    (legacy / "macnet.sqlite3").touch()
    assert app.default_directory() == legacy
    target = tmp_path / "local/MacNetLab"
    target.mkdir(parents=True)
    (target / "macnet.sqlite3").touch()
    assert app.default_directory() == target
    monkeypatch.setenv("MACNET_DATA_DIR", str(tmp_path / "explicit"))
    assert app.default_directory() == tmp_path / "explicit"


def test_windows_cli_is_a_normal_supported_entry_point(tmp_path, monkeypatch):
    from macnet import cli
    run = Mock(return_value=0)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.sys, "argv", ["macnet-lab", "--no-browser", "--data-dir", str(tmp_path)])
    monkeypatch.setenv("MACNET_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "run", run)
    assert cli.main() == 0
    assert run.call_args.args == (tmp_path, True)


def test_installer_preserves_project_local_scope(monkeypatch):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("macnet_installer", Path(__file__).parents[1] / "scripts/install.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.setattr(installer.shutil, "which", lambda name: "C:/tools/" + name)
    calls = Mock()
    monkeypatch.setattr(installer.subprocess, "run", calls)
    monkeypatch.setattr(installer.venv, "EnvBuilder", lambda **_: SimpleNamespace(create=lambda _: None))
    installer.main()
    rows = [c.args[0] for c in calls.call_args_list]
    assert ["C:/tools/npm.cmd", "--prefix", "frontend", "ci"] in rows
    assert any(".venv" in str(r[0]) and r[1:5] == ["-m", "pip", "install", "."] for r in rows)
    assert not any("sudo" in r or "Set-ExecutionPolicy" in r for r in rows)


@pytest.mark.asyncio
async def test_windows_print_timeout_is_unknown_not_a_false_service_failure(monkeypatch):
    monkeypatch.setattr(probes.sys, "platform", "win32")
    monkeypatch.setattr(probes, "printing_info", AsyncMock(side_effect=TimeoutError))
    result = await probes.Probes(None, None).run(
        Probe(id="p", device_id="pc", label="Print", kind="printing"),
        Device(id="pc", label="PC", kind="computer", local=True), {"interfaces": []})
    assert result.status == "unknown" and "15 秒" in result.message


@pytest.mark.asyncio
async def test_failed_windows_metadata_does_not_invent_physical_interfaces(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(windows, "network_metadata", AsyncMock(side_effect=ValueError("metadata unavailable")))
    monkeypatch.setattr(platform.psutil, "net_if_stats", lambda: {"custom": SimpleNamespace(isup=True, speed=1000)})
    monkeypatch.setattr(platform.psutil, "net_if_addrs", lambda: {"custom": []})
    monkeypatch.setattr(platform.psutil, "net_io_counters", lambda **_: {})
    result = await platform.observation()
    assert result["interfaces"][0]["kind"] == "unknown"
    assert result["interfaces"][0]["route"] == {}
    assert "unavailable" in result["note"]
