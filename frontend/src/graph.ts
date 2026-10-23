import type { Device, Site, Sample, Status } from "./types";
export const kinds: Record<string, string> = {
  gateway: "网关 / 路由器",
  switch: "交换机",
  ac: "无线控制器",
  ap: "无线 AP",
  computer: "运维电脑 / 笔记本",
  mac: "Mac / MacBook",
  server: "服务器",
  printer: "打印机",
  device: "普通设备",
};
export const links: Record<string, string> = {
  ethernet: "有线",
  wifi: "Wi-Fi",
  usb: "USB",
  management: "管理关系",
  dependency: "服务依赖",
};
export const colors: Record<string, string> = {
  ethernet: "#647b9a",
  wifi: "#4e6ff7",
  usb: "#a17c43",
  management: "#9ca8b9",
  dependency: "#9560bf",
};
export const statusNames: Record<Status, string> = {
  healthy: "正常",
  failed: "异常",
  unknown: "未知",
  paused: "暂停",
  gap: "数据中断",
};
export function deviceStatus(
  site: Site,
  device: string,
  latest: Sample[],
): Status {
  const probes = site.probes.filter((p) => p.device_id === device);
  const rows = probes
    .map((p) => latest.find((s) => s.probe === p.id))
    .filter(Boolean) as Sample[];
  if (rows.some((x) => x.status === "failed")) return "failed";
  if (
    probes.length &&
    rows.length === probes.length &&
    rows.every((x) => x.status === "healthy")
  )
    return "healthy";
  return "unknown";
}
export function newDevice(kind: string, x: number, y: number): Device {
  const ports = ["mac", "computer"].includes(kind)
    ? [
        ["ethernet", "ethernet"],
        ["wifi", "wifi"],
        ["usb", "usb"],
      ]
    : kind === "ap"
      ? [
          ["uplink", "ethernet"],
          ["radio", "wifi"],
        ]
      : kind === "printer"
        ? [["usb", "usb"]]
        : [["lan", "ethernet"]];
  return {
    id: crypto.randomUUID().replaceAll("-", "").slice(0, 16),
    label: kinds[kind] || "设备",
    kind,
    host: "",
    interfaces: ports.map(([id, kind]) => ({
      id,
      label: id,
      kind,
      address: "",
      bssids: [],
    })),
    services: [],
    position: { x, y },
    credential_ref: "",
    ssh_port: 22,
    ssh_user: "root",
    notes: "",
    local: false,
  };
}
