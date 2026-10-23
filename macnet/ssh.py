from __future__ import annotations
import asyncio
import asyncssh
from .models import Device
from .security import Vault, redact

COMMANDS = {
    "system": "uptime; free; ip route",
    "openwrt": "ubus call system info; logread | tail -n 80; dmesg | tail -n 40",
    "nikki": "/etc/init.d/nikki status",
}


class SSH:
    def __init__(self, directory, vault: Vault):
        self.known_hosts = directory / "known_hosts"
        self.vault = vault

    async def connect(self, device: Device):
        if not self.known_hosts.exists():
            raise ValueError("先在设置中导入已核实的 SSH known_hosts 公钥记录")
        credential = self.vault.get(device.credential_ref)
        keys = [asyncssh.import_private_key(credential.private_key)] if credential.private_key else []
        return await asyncssh.connect(
            device.host, port=device.ssh_port, username=device.ssh_user,
            known_hosts=str(self.known_hosts), client_keys=keys,
            password=credential.password or None, agent_path=None, config=None, login_timeout=8,
        )

    async def collect(self, device: Device, preset="system"):
        if preset not in COMMANDS:
            raise ValueError("不支持的只读采集动作")
        async with asyncio.timeout(15):
            async with await self.connect(device) as conn:
                async with conn.create_process(COMMANDS[preset]) as process:
                    async def read(stream):
                        text = await stream.read(32001)
                        if len(text) > 32000:
                            process.terminate()
                            text = text[:32000] + "\n[输出已截断]"
                        return text
                    stdout, stderr = await asyncio.gather(read(process.stdout), read(process.stderr))
                    await process.wait_closed()
                    return redact({"preset": preset, "exit_code": process.exit_status, "stdout": stdout, "stderr": stderr})
