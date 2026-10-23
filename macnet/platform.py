"""Read-only host adapters. macOS fields are not simulated on other systems."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import sys
from pathlib import Path

import psutil


async def command(argv: list[str], timeout=5, limit=64000) -> tuple[int, str, str]:
    """No shell. Bound runtime and output; reap children on cancellation too."""
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    async def read(stream):
        result = bytearray()
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return bytes(result).decode("utf-8", errors="replace")
            result.extend(chunk)
            if len(result) > limit:
                raise ValueError("采集输出超过大小限制")

    try:
        async with asyncio.timeout(timeout):
            stdout, stderr = await asyncio.gather(read(process.stdout), read(process.stderr))
            await process.wait()
            return process.returncode, stdout, stderr
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def parse_hardware_ports(text: str) -> dict[str, str]:
    ports = {}
    for block in text.split("\n\n"):
        name = re.search(r"Hardware Port:\s*(.+)", block)
        device = re.search(r"Device:\s*(\S+)", block)
        if name and device:
            ports[device[1]] = name[1].strip()
    return ports


def parse_route(text: str) -> dict:
    values = {}
    for key in ("gateway", "interface"):
        match = re.search(rf"^\s*{key}:\s*(\S+)", text, re.M)
        if match:
            values[key] = match[1]
    return values


def parse_dns(text: str) -> dict[str, list[str]]:
    result = {}
    for block in re.split(r"resolver #\d+", text):
        match = re.search(r"if_index\s*:\s*\d+\s*\(([^)]+)\)", block)
        if match:
            result.setdefault(match[1], [])
            for address in re.findall(r"nameserver\[\d+\]\s*:\s*(\S+)", block):
                if address not in result[match[1]]:
                    result[match[1]].append(address)
    return result


def wifi_info(name: str) -> dict:
    if sys.platform != "darwin":
        return {"available": False, "reason": "此采集器仅支持 macOS"}
    try:
        import CoreWLAN
        import objc

        with objc.autorelease_pool():
            interface = CoreWLAN.CWWiFiClient.sharedWiFiClient().interfaceWithName_(name)
            if interface is None:
                return {"available": False, "reason": "未找到无线接口"}
            ssid, bssid = interface.ssid(), interface.bssid()
            channel = interface.wlanChannel()
            return {
                "available": True,
                "ssid": ssid,
                "bssid": bssid,
                "rssi_dbm": interface.rssiValue() if ssid else None,
                "noise_dbm": interface.noiseMeasurement() if ssid else None,
                "tx_rate_mbps": interface.transmitRate() if ssid else None,
                "channel": channel.channelNumber() if channel else None,
                "identity_note": "" if bssid else "系统未提供 BSSID：检查无线关联状态和系统隐私权限",
            }
    except (ImportError, AttributeError, RuntimeError) as e:
        return {"available": False, "reason": f"CoreWLAN 不可用：{type(e).__name__}"}


def interface_kind(name, label, ips):
    if name.startswith(("lo", "utun", "gif", "stf", "awdl", "llw", "bridge")) or re.search(
        r"loopback|mihomo|clash|tun(?:nel)?|tap|virtual|vmware|vethernet|tailscale|wireguard", label, re.I
    ) or (ips and all(ipaddress.ip_address(ip.split("%")[0]).is_loopback for ip in ips)):
        return "logical"
    return "wifi" if re.search(r"wi-fi|airport|wireless|wlan", label, re.I) else "ethernet"


async def observation() -> dict:
    hardware, dns = {}, {}
    if sys.platform == "darwin":
        try:
            _, out, _ = await command(["/usr/sbin/networksetup", "-listallhardwareports"])
            hardware = parse_hardware_ports(out)
            _, out, _ = await command(["/usr/sbin/scutil", "--dns"])
            dns = parse_dns(out)
        except (OSError, TimeoutError, ValueError):
            pass
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    interfaces = []
    for name, addresses in psutil.net_if_addrs().items():
        stat = stats.get(name)
        ips = [a.address for a in addresses if a.family in (socket.AF_INET, socket.AF_INET6)]
        if not stat or not ips:
            continue
        label = hardware.get(name, name)
        kind = interface_kind(name, label, ips)
        item = {
            "id": name, "label": label, "kind": kind, "up": stat.isup,
            "addresses": ips, "speed_mbps": stat.speed or None,
            "dns_servers": dns.get(name, []), "route": {},
        }
        if counters.get(name):
            item["counters"] = counters[name]._asdict()
        if sys.platform == "darwin" and stat.isup and kind != "logical":
            try:
                code, out, _ = await command(["/sbin/route", "-n", "get", "-ifscope", name, "default"], timeout=2)
                if code == 0:
                    item["route"] = parse_route(out)
            except (OSError, TimeoutError, ValueError):
                item["route_note"] = "未读取到接口作用域内的默认路由"
        if kind == "wifi":
            item["wifi"] = await asyncio.to_thread(wifi_info, name)
        interfaces.append(item)
    return {
        "platform": sys.platform,
        "macos_supported": sys.platform == "darwin",
        "hostname": socket.gethostname(),
        "interfaces": interfaces,
        "note": "" if sys.platform == "darwin" else "当前为开发预览环境；macOS 网络和外设功能未在此环境验证",
    }


def resource_info() -> dict:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(Path.home()))
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1), "memory_percent": memory.percent,
        "memory_available_bytes": memory.available, "disk_free_bytes": disk.free,
        "disk_percent": disk.percent, "uptime_seconds": __import__("time").time() - psutil.boot_time(),
    }


async def printing_info() -> dict:
    if sys.platform != "darwin":
        return {"status": "unknown", "reason": "打印与 USB 采集需要 macOS"}
    data = {}
    for key, argv in {
        "scheduler": ["/usr/bin/lpstat", "-r"],
        "printers": ["/usr/bin/lpstat", "-p"],
        "queues": ["/usr/bin/lpstat", "-o"],
        "devices": ["/usr/bin/lpstat", "-v"],
        "usb": ["/usr/sbin/ioreg", "-p", "IOUSB", "-l", "-w", "0"],
    }.items():
        try:
            code, out, err = await command(argv, limit=48000)
            # Job owner and document title must not enter evidence or AI prompts.
            if key == "queues":
                data[key] = {"jobs": len(out.strip().splitlines()) if out.strip() else 0}
            else:
                data[key] = {"exit_code": code, "output": out, "error": err}
        except (OSError, TimeoutError, ValueError) as e:
            data[key] = {"error": str(e)}
    return data
