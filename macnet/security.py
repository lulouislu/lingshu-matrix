from __future__ import annotations

import json
import re
import keyring
from .models import Credential


def redact(value, field=""):
    """Redact before persistence and diagnostic export; never read worlds/chat logs."""
    if isinstance(value, dict):
        return {k: "[已脱敏]" if re.search(r"password|token|secret|private.?key|authorization|cookie|subscription|uuid|player.*name|serial", k, re.I) else redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, field) for v in value]
    if isinstance(value, str):
        value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----", "[私钥已移除]", value)
        value = re.sub(r'''(?im)(password|passwd|secret|token|authorization|cookie|api[_-]?key|subscription|(?:USB )?SerialNumber|serial number)["']?\s*[:=]\s*[^\r\n]+''', r"\1=[已脱敏]", value)
        value = re.sub(r"https?://[^\s\"<>]+", "[URL 已移除]", value)
        if field in {"id", "probe", "device_id", "source", "target", "incident", "source_interface", "target_interface"}:
            return value[:30000]
        value = re.sub(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b", "[UUID 已移除]", value)
        return value[:30000]
    return value


class Vault:
    SERVICE = "MacNetLab"

    def put(self, credential: Credential):
        try:
            keyring.set_password(self.SERVICE, credential.id, credential.model_dump_json())
        except Exception as e:
            raise ValueError("系统钥匙串不可用，未保存凭据；不降级为明文文件") from e

    def get(self, ref: str) -> Credential:
        if not ref:
            return Credential(id="none")
        try:
            raw = keyring.get_password(self.SERVICE, ref)
        except Exception as e:
            raise ValueError("无法访问系统钥匙串") from e
        if not raw:
            raise ValueError("凭据不存在，请重新配置")
        return Credential.model_validate_json(raw)
