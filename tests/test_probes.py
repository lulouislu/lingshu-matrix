import asyncio
import json
import struct
from unittest.mock import Mock

import pytest
from macnet.models import Device, Probe
from macnet.probes import Probes, minecraft_java, read_varint, varint, resolve


@pytest.mark.asyncio
async def test_http_and_tcp_loopback():
    async def serve(reader, writer):
        try:
            await reader.read(4096)
            writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        runner = Probes(None, None)
        device = Device(id="d", label="Loopback", host="127.0.0.1")
        p = Probe(id="p", label="HTTP", device_id="d", kind="http", target=f"http://127.0.0.1:{port}", expected_status=204)
        result = await runner.run(p, device, {"interfaces": []})
        assert result.status == "healthy" and result.detail["http_status"] == 204
        p.expected_status = 200
        assert (await runner.run(p, device, {"interfaces": []})).status == "failed"


@pytest.mark.asyncio
async def test_java_status_protocol_without_player_identity():
    async def serve(reader, writer):
        size = await read_varint(reader)
        await reader.readexactly(size)
        await reader.readexactly(2)
        payload = json.dumps({"version": {"name": "test"}, "players": {"online": 2, "max": 10, "sample": [{"name": "private-player"}]}}).encode()
        data = b"\x00" + varint(len(payload)) + payload
        writer.write(varint(len(data)) + data)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        result = await minecraft_java("127.0.0.1", server.sockets[0].getsockname()[1], "localhost", "")
        assert result["online"] == 2
        assert "private-player" not in str(result)


@pytest.mark.asyncio
async def test_disconnected_optional_interface_is_paused():
    runner = Probes(None, None)
    p = Probe(id="p", label="Check", device_id="d", kind="tcp", interface="en9", required=False)
    result = await runner.run(p, Device(id="d", label="Device"), {"interfaces": []})
    assert result.status == "paused"


@pytest.mark.asyncio
async def test_no_cross_interface_dns_fallback():
    from macnet.probes import Unobservable
    with pytest.raises(Unobservable, match="DNS"):
        await resolve("example.com", interface="en0")


@pytest.mark.asyncio
async def test_resources_not_silently_collected_from_remote():
    runner = Probes(None, None)
    result = await runner.run(Probe(id="p", label="Resource", device_id="d", kind="resources"), Device(id="d", label="Remote"), {"interfaces": []})
    assert result.status == "unknown"
@pytest.mark.asyncio
async def test_ssh_never_silently_ignores_interface():
    from unittest.mock import AsyncMock
    ssh = AsyncMock()
    result = await Probes(ssh, None).run(
        Probe(id="ssh", device_id="remote", label="SSH", kind="ssh", interface="en0"),
        Device(id="remote", label="Remote"), {"interfaces": [{"id": "en0", "up": True}]},
    )
    assert result.status == "unknown"
    ssh.collect.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_proxy_ignores_environment_and_uses_proxy_protocol(monkeypatch):
    received = []
    async def serve(reader, writer):
        received.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        p = Probe(id="p", device_id="d", label="Proxy", kind="proxy", target="http://service.invalid/status", proxy_url=f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", expected_status=204)
        result = await Probes(None, None).run(p, Device(id="d", label="Device"), {"interfaces": []})
        assert result.status == "healthy"
        assert received[0].startswith(b"GET http://service.invalid/status HTTP/1.1")


@pytest.mark.asyncio
async def test_bound_http_keeps_resolved_ip_and_tls_hostname_separate(tmp_path, monkeypatch):
    import datetime
    import ssl
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from macnet import probes
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "service.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("service.test")]), critical=False).sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "test-cert.pem", tmp_path / "test-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    seen = []
    server_context.set_servername_callback(lambda _, hostname, __: seen.append(hostname))
    client_context = ssl.create_default_context(cafile=str(cert_path))
    monkeypatch.setattr(probes.ssl, "create_default_context", lambda: client_context)
    async def resolve(host, server, interface, timeout):
        assert (host, server, interface) == ("service.test", "192.0.2.53", "en-test")
        return "127.0.0.1"
    original_tcp = probes.tcp
    async def tcp(host, port, interface, timeout):
        assert host == "127.0.0.1" and interface == "en-test"
        return await original_tcp(host, port, "", timeout)
    monkeypatch.setattr(probes, "resolve", resolve)
    monkeypatch.setattr(probes, "tcp", tcp)
    async def serve(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        assert b"Host: service.test:" in request
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_server(serve, "127.0.0.1", 0, ssl=server_context)
    async with server:
        code = await probes.direct_http_status(f"https://service.test:{server.sockets[0].getsockname()[1]}/status", "en-test", "192.0.2.53")
        assert code == 200 and seen == ["service.test"]
