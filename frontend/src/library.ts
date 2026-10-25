// User-supplied design presets describe hardware, not discovered devices or drivers.
// No sample IP, credential or probe is provisioned when a preset is added.
export const hardwarePresets = [
  {
    id: "nbr",
    kind: "gateway",
    label: "锐捷 NBR6205-E",
    model: "Ruijie NBR6205-E · 网关 / AC",
    group: "网关与路由 / GATEWAYS",
  },
  {
    id: "tr3000",
    kind: "gateway",
    label: "Cudy TR3000 旁路网关",
    model: "KWRT / OpenWrt · Nikki",
    group: "网关与路由 / GATEWAYS",
  },
  {
    id: "ont",
    kind: "gateway",
    label: "光猫 / 上游网关",
    model: "EPON / 桥接上游",
    group: "网关与路由 / GATEWAYS",
  },
  {
    id: "es118",
    kind: "switch",
    label: "锐捷 RG-ES118GS-LP",
    model: "PoE 接入交换机",
    group: "交换与无线 / SWITCHING",
  },
  {
    id: "rap2261",
    kind: "ap",
    label: "锐捷 RAP2261(G)",
    model: "Wi-Fi 6 吸顶 AP",
    group: "交换与无线 / SWITCHING",
  },
  {
    id: "nas",
    kind: "server",
    label: "群晖 Synology NAS",
    model: "DSM · 存储与应用",
    group: "服务器与边缘 / COMPUTE",
  },
  {
    id: "mini",
    kind: "mac",
    label: "Mac mini 2014",
    model: "常开主机 / 本地工作台",
    group: "服务器与边缘 / COMPUTE",
  },
  {
    id: "n1",
    kind: "server",
    label: "斐讯 Phicomm N1",
    model: "Armbian · 边缘主机",
    group: "服务器与边缘 / COMPUTE",
  },
  {
    id: "tunnel",
    kind: "device",
    label: "Cloudflare Tunnel",
    model: "cloudflared · 逻辑服务节点",
    group: "隧道与服务 / SERVICES",
  },
];
