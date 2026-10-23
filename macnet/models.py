from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Interface(Model):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    label: str = Field(default="", max_length=100)
    kind: Literal["ethernet", "wifi", "usb", "logical"] = "ethernet"
    address: str = Field(default="", max_length=255)
    bssids: list[str] = Field(default_factory=list, max_length=32)


class Device(Model):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    label: str = Field(min_length=1, max_length=100)
    kind: Literal["gateway", "switch", "ac", "ap", "mac", "server", "printer", "device"] = "device"
    host: str = Field(default="", max_length=255)
    interfaces: list[Interface] = Field(default_factory=list, max_length=32)
    services: list[str] = Field(default_factory=list, max_length=32)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    credential_ref: str = Field(default="", max_length=64)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(default="root", max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    notes: str = Field(default="", max_length=2000)
    local: bool = False


class Link(Model):
    id: str = Field(min_length=1, max_length=128)
    source: str
    target: str
    source_interface: str = ""
    target_interface: str = ""
    kind: Literal["ethernet", "wifi", "usb", "management", "dependency"] = "ethernet"
    label: str = Field(default="", max_length=100)


class Probe(Model):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    device_id: str
    label: str = Field(min_length=1, max_length=100)
    kind: Literal["ping", "tcp", "dns", "http", "proxy", "mihomo", "minecraft_java", "minecraft_bedrock", "printing", "resources", "ssh"]
    target: str = Field(default="", max_length=2048)
    port: int = Field(default=0, ge=0, le=65535)
    interface: str = Field(default="", max_length=64, pattern=r"^[\w. -]*$")
    dns_server: str = Field(default="", max_length=255)
    proxy_url: str = Field(default="", max_length=255)
    expected_status: int = Field(default=200, ge=100, le=599)
    interval: int = Field(default=15, ge=5, le=3600)
    timeout: int = Field(default=4, ge=1, le=30)
    failures: int = Field(default=2, ge=1, le=10)
    enabled: bool = False
    collect_snapshot: bool = False
    required: bool = True
    process_id: int = Field(default=0, ge=0)
    ssh_preset: Literal["system", "openwrt", "nikki"] = "system"

    @field_validator("target", "proxy_url")
    @classmethod
    def no_embedded_auth(cls, v: str):
        if any(ord(c) < 32 for c in v):
            raise ValueError("目标不能包含控制字符")
        if "://" in v:
            u = urlsplit(v)
            if u.username or u.password or u.scheme not in ("http", "https", "socks5", "socks5h"):
                raise ValueError("仅支持无内嵌凭据的 HTTP / HTTPS / SOCKS 地址")
        return v


class Site(Model):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    name: str = Field(min_length=1, max_length=100)
    revision: int = Field(default=0, ge=0)
    devices: list[Device] = Field(default_factory=list, max_length=500)
    links: list[Link] = Field(default_factory=list, max_length=2000)
    probes: list[Probe] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def references(self):
        for items in (self.devices, self.links, self.probes):
            ids = [x.id for x in items]
            if len(ids) != len(set(ids)):
                raise ValueError("ID 不能重复")
        nodes = {x.id: x for x in self.devices}
        for d in self.devices:
            if len({i.id for i in d.interfaces}) != len(d.interfaces):
                raise ValueError("设备接口 ID 不能重复")
        for edge in self.links:
            if edge.source not in nodes or edge.target not in nodes:
                raise ValueError("连线引用不存在的设备")
            if edge.source == edge.target:
                raise ValueError("不能将设备连接到自己")
            for device_id, interface_id in ((edge.source, edge.source_interface), (edge.target, edge.target_interface)):
                if interface_id and interface_id not in {i.id for i in nodes[device_id].interfaces}:
                    raise ValueError("连线引用不存在的接口")
                if edge.kind in ("ethernet", "wifi", "usb"):
                    port = next((i for i in nodes[device_id].interfaces if i.id == interface_id), None)
                    if port is None or port.kind != edge.kind:
                        raise ValueError("物理连线必须连接两端同类型的真实接口")
        if any(p.device_id not in nodes for p in self.probes):
            raise ValueError("检测引用不存在的设备")
        return self


class Result(Model):
    status: Literal["healthy", "failed", "unknown", "paused", "gap"]
    message: str
    latency_ms: float | None = None
    detail: dict = Field(default_factory=dict)


class Credential(Model):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    password: str = Field(default="", max_length=10000)
    private_key: str = Field(default="", max_length=20000)
    api_token: str = Field(default="", max_length=2000)

    @field_validator("api_token")
    @classmethod
    def token_one_line(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("API 密钥不能包含控制字符")
        return value


class DiagnosticRequest(Model):
    issue: str = Field(default="", max_length=4000)
    observed_at: str = Field(default="", max_length=200)
    impact: str = Field(default="", max_length=2000)
    recent_changes: str = Field(default="", max_length=4000)
    attempts: str = Field(default="", max_length=4000)
    incident_id: str = Field(default="", max_length=64)


def sanitized_export(site: Site) -> dict:
    data = site.model_dump()
    for d in data["devices"]:
        d["credential_ref"] = ""
    # Imported topology must never start remote requests by itself.
    for p in data["probes"]:
        p["enabled"] = False
    data["revision"] = 0
    return data
