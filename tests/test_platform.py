import pytest

from macnet.platform import command, parse_dns, parse_hardware_ports, parse_route
from macnet.platform import interface_kind


def test_virtual_interfaces_are_not_physical_ethernet():
    assert interface_kind("Mihomo", "Mihomo", ["198.18.0.1"]) == "logical"
    assert interface_kind("Loopback Pseudo-Interface 1", "Loopback", ["127.0.0.1"]) == "logical"
    assert interface_kind("en4", "USB 10/100/1000 LAN", ["192.0.2.4"]) == "ethernet"
    assert interface_kind("en0", "Wi-Fi", ["192.0.2.5"]) == "wifi"


def test_mac_interface_parsers():
    assert parse_hardware_ports("Hardware Port: Wi-Fi\nDevice: en1\n") == {"en1": "Wi-Fi"}
    assert parse_route("gateway: 192.0.2.1\ninterface: en1")["interface"] == "en1"
    assert parse_dns("resolver #1\n nameserver[0] : 192.0.2.53\n if_index : 5 (en1)") == {"en1": ["192.0.2.53"]}


@pytest.mark.asyncio
async def test_command_is_bounded():
    import sys
    code, stdout, _ = await command([sys.executable, "-c", "print('ok')"])
    assert code == 0 and stdout.strip() == "ok"
    with pytest.raises(ValueError):
        await command([sys.executable, "-c", "print('x'*10000)"], limit=100)
    with pytest.raises(TimeoutError):
        await command([sys.executable, "-c", "import time;time.sleep(10)"], timeout=0.1)
