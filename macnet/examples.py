from .models import Device, Interface, Link, Probe, Site
from .store import uid


def template(kind="ac"):
    def device(id, label, kind, x, y, ports, **kw):
        return Device(id=id, label=label, kind=kind, position={"x": x, "y": y}, interfaces=[Interface(id=p, label=p, kind=t) for p, t in ports], **kw)
    if kind == "home":
        devices = [device("modem", "光猫", "gateway", 300, 0, [("lan", "ethernet")]), device("r1", "路由器 1", "gateway", 50, 180, [("lan", "ethernet"), ("radio", "wifi")]), device("r2", "KWRT 网关", "gateway", 500, 180, [("lan", "ethernet")], services=["Nikki"]), device("mac", "常开 Mac", "mac", 300, 400, [("ethernet", "ethernet"), ("wifi", "wifi"), ("usb", "usb")], services=["打印共享", "Minecraft"], local=True), device("printer", "USB 打印机", "printer", 600, 570, [("usb", "usb")])]
        links = [Link(id="m1", source="modem", target="r1", source_interface="lan", target_interface="lan"), Link(id="m2", source="modem", target="r2", source_interface="lan", target_interface="lan"), Link(id="r1mac", source="r1", target="mac", source_interface="radio", target_interface="wifi", kind="wifi"), Link(id="r2mac", source="r2", target="mac", source_interface="lan", target_interface="ethernet"), Link(id="usb", source="mac", target="printer", source_interface="usb", target_interface="usb", kind="usb")]
    else:
        devices = [device("gw", "出口网关", "gateway", 300, 0, [("lan", "ethernet")]), device("sw", "接入交换机", "switch", 300, 170, [("uplink", "ethernet"), ("lan", "ethernet")]), device("ac", "无线控制器 AC", "ac", 0, 340, [("mgmt", "ethernet")]), device("ap1", "AP · 机房", "ap", 300, 340, [("uplink", "ethernet"), ("radio", "wifi")]), device("ap2", "AP · 办公区", "ap", 600, 340, [("uplink", "ethernet"), ("radio", "wifi")]), device("mac", "维护 MacBook", "mac", 300, 560, [("ethernet", "ethernet"), ("wifi", "wifi"), ("usb", "usb")], local=True)]
        links = [Link(id="gw-sw", source="gw", target="sw", source_interface="lan", target_interface="uplink"), *[Link(id="sw-"+id, source="sw", target=id, source_interface="lan", target_interface=port) for id, port in (("ac", "mgmt"), ("ap1", "uplink"), ("ap2", "uplink"))], Link(id="wifi", source="ap1", target="mac", source_interface="radio", target_interface="wifi", kind="wifi"), *[Link(id="ac-"+id, source="ac", target=id, kind="management", label="管理") for id in ("ap1", "ap2")]]
    probes = [Probe(id="host-resources", device_id="mac", label="Mac 资源", kind="resources"), Probe(id="gateway", device_id=devices[0].id, label="网关连通性（请填写地址）", kind="ping")]
    return Site(id=uid(), name="家庭实验室 · 示例" if kind == "home" else "AC / AP 网络 · 示例", devices=devices, links=links, probes=probes)
