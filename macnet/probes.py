from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import ssl
import struct
import sys
import time
from urllib.parse import urlsplit

import dns.message
import dns.rcode
import dns.rdatatype
import httpx
import h11
import psutil
from .models import Device, Probe, Result
from .platform import command, printing_info, resource_info


class Unobservable(ValueError):
    pass


def interface_options(interface):
    if sys.platform == "darwin":
        return [(socket.IPPROTO_IP, 25, socket.if_nametoindex(interface))]
    if sys.platform == "win32":
        from .windows import unicast_option
        return [unicast_option(interface)]
    raise Unobservable("此平台尚未实现接口绑定；不回退到系统默认路径")


def bound_socket(kind, interface=""):
    sock = socket.socket(socket.AF_INET, kind)
    try:
        if interface:
            for option in interface_options(interface):
                sock.setsockopt(*option)
        sock.setblocking(False)
        return sock
    except BaseException:
        sock.close()
        raise


async def resolve(name, server="", interface="", timeout=4):
    try:
        address = ipaddress.ip_address(name)
        if address.version != 4:
            raise Unobservable("当前检测器支持 IPv4；IPv6 不伪装为已检测")
        return str(address)
    except ValueError as exc:
        if isinstance(exc, Unobservable):
            raise
    if interface and not server:
        raise Unobservable("接口检测需指定该路径的 DNS 服务器，避免使用另一接口的解析结果")
    if not server:
        records = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(name, None, family=socket.AF_INET), timeout)
        return records[0][4][0]
    ipaddress.IPv4Address(server)
    query = dns.message.make_query(name, "A")
    sock = bound_socket(socket.SOCK_DGRAM, interface)
    try:
        loop = asyncio.get_running_loop()
        await loop.sock_connect(sock, (server, 53))
        await loop.sock_sendall(sock, query.to_wire())
        packet = await asyncio.wait_for(loop.sock_recv(sock, 65535), timeout)
        reply = dns.message.from_wire(packet)
        if not query.is_response(reply):
            raise ValueError("DNS 响应与请求不匹配")
        if reply.rcode() != dns.rcode.NOERROR:
            raise ValueError("DNS 返回 " + dns.rcode.to_text(reply.rcode()))
        for section in reply.answer:
            if section.rdtype == dns.rdatatype.A:
                return section[0].address
        raise ValueError("DNS 未返回 IPv4 地址")
    finally:
        sock.close()


async def tcp(host, port, interface="", timeout=4):
    sock = bound_socket(socket.SOCK_STREAM, interface)
    try:
        await asyncio.wait_for(asyncio.get_running_loop().sock_connect(sock, (host, port)), timeout)
        return await asyncio.open_connection(sock=sock)
    except BaseException:
        sock.close()
        raise


async def direct_http_status(url, interface="", dns_server="", timeout=4):
    """HTTP/1.1 over the same interface-bound socket used by TCP; no redirect or proxy."""
    parsed = httpx.URL(url)
    hostname = parsed.raw_host.decode("ascii")
    address = await resolve(hostname, dns_server, interface, timeout)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    reader, writer = await tcp(address, port, interface, timeout)
    try:
        if parsed.scheme == "https":
            await writer.start_tls(ssl.create_default_context(), server_hostname=hostname, ssl_handshake_timeout=timeout)
        protocol = h11.Connection(h11.CLIENT, max_incomplete_event_size=64000)
        authority = hostname if port == (443 if parsed.scheme == "https" else 80) else f"{hostname}:{port}"
        writer.write(protocol.send(h11.Request(method=b"GET", target=parsed.raw_path, headers=[(b"Host", authority.encode()), (b"Connection", b"close"), (b"User-Agent", b"MacNetLab/0.1")])) + protocol.send(h11.EndOfMessage()))
        await writer.drain()
        status, size = None, 0
        while True:
            event = protocol.next_event()
            if event is h11.NEED_DATA:
                packet = await reader.read(4096)
                protocol.receive_data(packet)
            elif isinstance(event, h11.Response):
                status = event.status_code
            elif isinstance(event, h11.Data):
                size += len(event.data)
                if size > 1048576:
                    raise ValueError("HTTP 响应超过 1 MiB 上限")
            elif isinstance(event, h11.EndOfMessage):
                if status is None:
                    raise ValueError("HTTP 响应缺少状态行")
                return status
            elif isinstance(event, h11.ConnectionClosed):
                raise ValueError("HTTP 服务在完整响应前断开")
            elif event is h11.PAUSED:
                raise ValueError("检测器不接受 HTTP 协议升级")
    finally:
        writer.close()
        await writer.wait_closed()


def varint(value):
    output = bytearray()
    value &= 0xffffffff
    while True:
        byte = value & 127
        value >>= 7
        output.append(byte | (128 if value else 0))
        if not value:
            return bytes(output)


async def read_varint(reader):
    value = 0
    for i in range(5):
        byte = (await reader.readexactly(1))[0]
        value |= (byte & 127) << (7 * i)
        if not byte & 128:
            return value
    raise ValueError("Minecraft 数据包长度无效")


async def minecraft_java(host, port, original_host, interface):
    reader, writer = await tcp(host, port, interface)
    try:
        name = original_host.encode()
        handshake = b"\x00" + varint(-1) + varint(len(name)) + name + struct.pack(">H", port) + b"\x01"
        writer.write(varint(len(handshake)) + handshake + b"\x01\x00")
        await writer.drain()
        size = await read_varint(reader)
        if not 1 < size <= 65536:
            raise ValueError("Minecraft 响应超过上限")
        payload = await reader.readexactly(size)
        if payload[0] != 0:
            raise ValueError("不是 Minecraft 状态响应")
        offset, length = 1, 0
        for i in range(5):
            byte = payload[offset]
            offset += 1
            length |= (byte & 127) << (7 * i)
            if not byte & 128:
                break
        value = json.loads(payload[offset:offset + length])
        return {"edition": "Java", "version": value.get("version", {}).get("name"), "online": value.get("players", {}).get("online"), "max": value.get("players", {}).get("max")}
    finally:
        writer.close()
        await writer.wait_closed()


async def minecraft_bedrock(host, port, interface):
    magic = bytes.fromhex("00ffff00fefefefefdfdfdfd12345678")
    sock = bound_socket(socket.SOCK_DGRAM, interface)
    try:
        loop = asyncio.get_running_loop()
        await loop.sock_connect(sock, (host, port))
        await loop.sock_sendall(sock, b"\x01" + struct.pack(">q", int(time.time() * 1000)) + magic + struct.pack(">q", 1))
        payload = await loop.sock_recv(sock, 65535)
        if len(payload) < 35 or payload[0] != 0x1c or payload[17:33] != magic:
            raise ValueError("不是 Bedrock 状态响应")
        length = struct.unpack(">H", payload[33:35])[0]
        parts = payload[35:35 + length].decode(errors="replace").split(";")
        if len(parts) < 6:
            raise ValueError("Bedrock 状态字段不完整")
        return {"edition": "Bedrock", "version": parts[3], "online": int(parts[4]), "max": int(parts[5])}
    finally:
        sock.close()


class Probes:
    def __init__(self, ssh, vault):
        self.ssh, self.vault = ssh, vault

    async def run(self, probe: Probe, device: Device, context: dict):
        start = time.perf_counter()
        path = {"interface": probe.interface or "system", "target": probe.target or device.host}
        source = next((i for i in context["interfaces"] if i["id"] == probe.interface), None)
        if source:
            path["observation"] = {"addresses": source.get("addresses", []), "route": source.get("route", {}), "bssid": source.get("wifi", {}).get("bssid")}
        try:
            async with asyncio.timeout(probe.timeout + 2):
                if probe.interface:
                    interface = next((i for i in context["interfaces"] if i["id"] == probe.interface), None)
                    if not interface or not interface["up"]:
                        return Result(status="failed" if probe.required else "paused", message="指定接口未连接", detail=path)
                result = await self._run(probe, device, context)
                result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
                result.detail.update(path)
                return result
        except Unobservable as e:
            return Result(status="unknown", message=str(e), detail=path)
        except TimeoutError:
            if sys.platform == "win32" and probe.kind == "printing":
                return Result(status="unknown", message="Windows 打印查询超时，未判定打印服务故障；可将此项超时设为 15 秒后重试", detail=path)
            return Result(status="failed", message="检测超时", latency_ms=round((time.perf_counter() - start) * 1000, 2), detail=path)
        except Exception as e:
            return Result(status="failed", message=str(e) or type(e).__name__, latency_ms=round((time.perf_counter() - start) * 1000, 2), detail=path)

    async def _run(self, p, d, context):
        detail = {}
        if p.kind in ("resources", "printing"):
            if not d.local:
                raise Unobservable("此项只采集本机；请将对应电脑标为本机设备")
            if p.kind == "resources":
                detail = await asyncio.to_thread(resource_info)
                if p.process_id:
                    process = psutil.Process(p.process_id)
                    detail["process"] = {"pid": p.process_id, "name": process.name(), "created_at": process.create_time(), "rss_bytes": process.memory_info().rss, "cpu_seconds": sum(process.cpu_times()[:2])}
            else:
                detail = await printing_info()
                if detail.get("status") == "unknown":
                    raise Unobservable(detail["reason"])
                scheduler = detail.get("scheduler", {})
                return Result(status="healthy" if scheduler.get("exit_code") == 0 else "failed", message="已读取打印状态；不代表手机发现或实际打印已验证", detail=detail)
        elif p.kind == "ssh":
            if p.interface:
                raise Unobservable("SSH 只读采集尚不支持接口绑定；未改用默认路径执行")
            detail = await self.ssh.collect(d, p.ssh_preset)
            return Result(status="healthy" if detail["exit_code"] == 0 else "failed", message="SSH 只读采集完成；使用系统管理路径", detail=detail)
        elif p.kind in ("http", "proxy", "mihomo"):
            url = p.target or ("http://" + d.host + ":9090/version" if p.kind == "mihomo" else "")
            u = urlsplit(url)
            if u.scheme not in ("http", "https") or not u.hostname:
                raise ValueError("请配置完整的 HTTP(S) 地址")
            if p.kind == "mihomo":
                options = None
                if p.interface:
                    try:
                        ipaddress.IPv4Address(u.hostname)
                    except ValueError:
                        raise Unobservable("绑定接口的控制 API 请填写 IPv4 地址，避免跨接口 DNS 解析")
                    options = interface_options(p.interface)
                token = self.vault.get(d.credential_ref).api_token
                transport = httpx.AsyncHTTPTransport(socket_options=options, trust_env=False)
                async with httpx.AsyncClient(transport=transport, timeout=p.timeout, trust_env=False) as client:
                    async with client.stream("GET", url, headers={"Authorization": "Bearer " + token} if token else {}) as response:
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 256000:
                                raise ValueError("控制 API 响应超过采集大小限制")
                        return Result(status="healthy" if response.status_code == p.expected_status else "failed", message=f"Mihomo API HTTP {response.status_code}；不代表代理上网已验证", detail={"http_status": response.status_code})
            if p.kind == "proxy":
                proxy = urlsplit(p.proxy_url)
                if proxy.scheme not in ("http", "https", "socks5", "socks5h") or not proxy.hostname:
                    raise ValueError("请设置显式代理地址")
                options = None
                if p.interface:
                    ipaddress.IPv4Address(proxy.hostname)
                    options = interface_options(p.interface)
                transport = httpx.AsyncHTTPTransport(proxy=p.proxy_url, socket_options=options, trust_env=False)
                async with httpx.AsyncClient(transport=transport, timeout=p.timeout, trust_env=False) as client:
                    async with client.stream("GET", url) as response:
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 1048576:
                                raise ValueError("代理响应超过 1 MiB 上限")
                        status = response.status_code
                detail["dns_scope"] = "目标域名交给显式代理解析；不等同于终端透明代理验证"
            else:
                status = await direct_http_status(url, p.interface, p.dns_server, p.timeout)
            return Result(status="healthy" if status == p.expected_status else "failed", message=f"HTTP {status}，预期 {p.expected_status}", detail={**detail, "http_status": status})
        else:
            if p.kind == "ping" and p.interface and sys.platform != "darwin":
                raise Unobservable("此系统的 ICMP 尚无可靠接口绑定；请改用绑定接口的 TCP/DNS/HTTP，不回退默认路径")
            host = await resolve(p.target or d.host, p.dns_server, p.interface, p.timeout)
            if p.kind == "dns":
                detail = {"answer": host, "server": p.dns_server or "system"}
            elif p.kind == "tcp":
                if not p.port:
                    raise ValueError("TCP 检测需设置端口")
                _, writer = await tcp(host, p.port, p.interface, p.timeout)
                writer.close()
                await writer.wait_closed()
            elif p.kind == "ping":
                if sys.platform == "darwin":
                    args = ["/sbin/ping", "-c", "1", "-W", str(p.timeout * 1000)]
                    if p.interface:
                        args += ["-b", p.interface]
                elif p.interface:
                    raise Unobservable("此系统的 ICMP 尚无可靠接口绑定；请改用绑定接口的 TCP/DNS/HTTP，不回退默认路径")
                else:
                    args = ["ping", "-n", "1", "-w", str(p.timeout * 1000)] if sys.platform == "win32" else ["ping", "-c", "1", "-W", str(p.timeout)]
                code, out, err = await command(args + [host], timeout=p.timeout + 1)
                detail = {"packet_loss_percent": 100 if code else 0}
                if code:
                    raise ValueError("ICMP 无响应；不直接等同于设备关机")
            elif p.kind == "minecraft_java":
                detail = await minecraft_java(host, p.port or 25565, p.target or d.host, p.interface)
            elif p.kind == "minecraft_bedrock":
                detail = await minecraft_bedrock(host, p.port or 19132, p.interface)
        return Result(status="healthy", message="检测成功", detail=detail)
