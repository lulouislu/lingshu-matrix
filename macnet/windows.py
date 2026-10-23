"""Windows read-only adapters. Fixed PowerShell queries and Native Wi-Fi APIs only."""
from __future__ import annotations

import base64
import ctypes as ct
import json
import os
import struct
from ctypes import wintypes as wt
from pathlib import Path


def powershell(script):
    # Only application-owned constant scripts reach this function, never user text.
    prefix = "$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new();$OutputEncoding=[Console]::OutputEncoding;"
    binary = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode((prefix + script).encode("utf-16-le")).decode("ascii")
    return [str(binary), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


NETWORK_QUERY = r'''
$dns=@(Get-DnsClientServerAddress -AddressFamily IPv4);
$routes=@(Get-NetRoute -AddressFamily IPv4 | Where-Object DestinationPrefix -eq '0.0.0.0/0');
$rows=@(Get-NetAdapter -IncludeHidden | ForEach-Object {
 $a=$_;
 [PSCustomObject]@{name=$a.Name;description=$a.InterfaceDescription;index=[int]$a.ifIndex;
 guid=[string]$a.InterfaceGuid;hardware=[bool]$a.HardwareInterface;medium=[int]$a.NdisPhysicalMedium;
 dns=@($dns | Where-Object InterfaceIndex -eq $a.ifIndex | ForEach-Object {$_.ServerAddresses});
 routes=@($routes | Where-Object InterfaceIndex -eq $a.ifIndex | Sort-Object RouteMetric | ForEach-Object {
 [PSCustomObject]@{gateway=$_.NextHop;metric=[int]$_.RouteMetric}})}
});ConvertTo-Json -InputObject $rows -Depth 5 -Compress
'''

PRINT_QUERY = r'''
$service=Get-Service -Name Spooler;
$notes=@();$printers=@();try {$printers=@(Get-CimInstance Win32_Printer | Select-Object Name,PortName,Shared,WorkOffline,PrinterStatus,DetectedErrorState)}catch{$notes+='Printer inventory unavailable'};
$queues=@();try {$queues=@(Get-CimInstance Win32_PerfFormattedData_Spooler_PrintQueue | Where-Object Name -ne '_Total' | Select-Object Name,Jobs)}catch{$notes+='Queue counts unavailable'};
$usb=@();try {$usb=@(Get-CimInstance Win32_PnPEntity -Filter "PNPClass='Printer'" | Where-Object {$_.PNPDeviceID -like 'USB*'} | Select-Object Name,Status)}catch{$notes+='USB printer inventory unavailable'};
[PSCustomObject]@{scheduler=[PSCustomObject]@{exit_code=$(if($service.Status -eq 'Running'){0}else{1});state=[string]$service.Status};
 printers=$printers;queues=$queues;usb=$usb;unavailable=$notes} | ConvertTo-Json -Depth 5 -Compress
'''


async def network_metadata(command):
    code, out, _ = await command(powershell(NETWORK_QUERY), timeout=15, limit=128000)
    if code:
        raise ValueError("Windows 网络配置只读查询失败，未猜测网关或 DNS")
    rows = json.loads(out.lstrip("\ufeff"))
    return {r["name"]: r for r in rows}


async def printing_info(command):
    try:
        code, out, _ = await command(powershell(PRINT_QUERY), timeout=15, limit=128000)
        if code:
            raise ValueError("Windows 打印服务查询失败或权限不足")
        data = json.loads(out.lstrip("\ufeff"))
        data["note"] = "仅查询 Spooler、打印机、队列数量和 USB 打印设备；不读取任务标题/所有者，不代表 AirPrint 或实际打印成功"
        return data
    except (OSError, ValueError, TimeoutError) as exc:
        return {"status": "unknown", "reason": str(exc)}


def interface_identity(name):
    api = ct.WinDLL("iphlpapi.dll")
    luid, index = ct.c_ulonglong(), wt.ULONG()
    api.ConvertInterfaceAliasToLuid.argtypes = [wt.LPCWSTR, ct.POINTER(ct.c_ulonglong)]
    api.ConvertInterfaceAliasToLuid.restype = wt.ULONG
    code = api.ConvertInterfaceAliasToLuid(name, ct.byref(luid))
    if code:
        raise OSError(code, "无法识别指定的 Windows 接口")
    api.ConvertInterfaceLuidToIndex.argtypes = [ct.POINTER(ct.c_ulonglong), ct.POINTER(wt.ULONG)]
    api.ConvertInterfaceLuidToIndex.restype = wt.ULONG
    code = api.ConvertInterfaceLuidToIndex(ct.byref(luid), ct.byref(index))
    if code or not index.value:
        raise OSError(code, "无法读取 Windows 接口索引")
    return api, luid, index.value


def interface_index(name):
    return interface_identity(name)[2]


def unicast_option(name):
    # IP_UNICAST_IF: DWORD index in network byte order, not a source-address-only bind.
    return (0, 31, struct.pack("!I", interface_index(name)))


class GUID(ct.Structure):
    _fields_ = [("data", ct.c_ubyte * 16)]


class SSID(ct.Structure):
    _fields_ = [("length", wt.ULONG), ("data", ct.c_ubyte * 32)]


class Association(ct.Structure):
    _fields_ = [("ssid", SSID), ("bss_type", ct.c_int), ("bssid", ct.c_ubyte * 6),
                ("phy_type", ct.c_int), ("phy_index", wt.ULONG), ("quality", wt.ULONG),
                ("rx_rate", wt.ULONG), ("tx_rate", wt.ULONG)]


class Security(ct.Structure):
    _fields_ = [("security", wt.BOOL), ("one_x", wt.BOOL), ("auth", ct.c_int), ("cipher", ct.c_int)]


class Connection(ct.Structure):
    _fields_ = [("state", ct.c_int), ("mode", ct.c_int), ("profile", wt.WCHAR * 256),
                ("association", Association), ("security", Security)]


def wifi_info(name):
    """Query only current association, RSSI and channel. Never scan/connect/read keys."""
    handle = wt.HANDLE()
    dll = None
    try:
        api, luid, _ = interface_identity(name)
        guid = GUID()
        api.ConvertInterfaceLuidToGuid.argtypes = [ct.POINTER(ct.c_ulonglong), ct.POINTER(GUID)]
        api.ConvertInterfaceLuidToGuid.restype = wt.ULONG
        code = api.ConvertInterfaceLuidToGuid(ct.byref(luid), ct.byref(guid))
        if code:
            raise OSError(code, "无法读取无线接口标识")
        dll = ct.WinDLL("wlanapi.dll")
        dll.WlanOpenHandle.argtypes = [wt.DWORD, ct.c_void_p, ct.POINTER(wt.DWORD), ct.POINTER(wt.HANDLE)]
        dll.WlanOpenHandle.restype = wt.DWORD
        dll.WlanCloseHandle.argtypes = [wt.HANDLE, ct.c_void_p]
        dll.WlanQueryInterface.argtypes = [wt.HANDLE, ct.POINTER(GUID), ct.c_int, ct.c_void_p,
                                          ct.POINTER(wt.DWORD), ct.POINTER(ct.c_void_p), ct.c_void_p]
        dll.WlanQueryInterface.restype = wt.DWORD
        dll.WlanFreeMemory.argtypes = [ct.c_void_p]
        version = wt.DWORD()
        code = dll.WlanOpenHandle(2, None, ct.byref(version), ct.byref(handle))
        if code:
            raise OSError(code, "无法打开 Windows WLAN 服务")
        def query(opcode, kind):
            size, ptr = wt.DWORD(), ct.c_void_p()
            code = dll.WlanQueryInterface(handle, ct.byref(guid), opcode, None, ct.byref(size), ct.byref(ptr), None)
            if code:
                raise OSError(code, "无法读取无线关联；可能未连接或隐私权限受限")
            try:
                if not ptr.value or size.value < ct.sizeof(kind):
                    raise ValueError("无线 API 返回数据不完整")
                return kind.from_buffer_copy(ct.string_at(ptr, ct.sizeof(kind)))
            finally:
                if ptr.value:
                    dll.WlanFreeMemory(ptr)
        connection = query(7, Connection)
        assoc = connection.association
        if assoc.ssid.length > 32:
            raise ValueError("无线 API 返回 SSID 长度无效")
        data = {"available": True, "ssid": bytes(assoc.ssid.data[:assoc.ssid.length]).decode("utf-8", errors="replace"),
                "bssid": ":".join(f"{x:02x}" for x in assoc.bssid), "signal_quality_percent": assoc.quality,
                "tx_rate_mbps": assoc.tx_rate / 1000, "rx_rate_mbps": assoc.rx_rate / 1000,
                "rssi_dbm": None, "channel": None, "noise_dbm": None}
        for key, opcode, kind in (("channel", 8, wt.ULONG), ("rssi_dbm", 0x10000102, wt.LONG)):
            try:
                data[key] = query(opcode, kind).value
            except (OSError, ValueError):
                pass  # Optional metrics stay explicitly unknown; never estimate dBm from quality.
        return data
    except (OSError, ValueError, AttributeError) as exc:
        return {"available": False, "reason": str(exc), "identity_note": "未连接或 Windows WLAN/隐私权限受限；不猜测 SSID 或 AP"}
    finally:
        if handle.value and dll:
            dll.WlanCloseHandle(handle, None)
