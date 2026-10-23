<script setup lang="ts">
import {
  computed,
  onMounted,
  onBeforeUnmount,
  ref,
  shallowRef,
  watch,
  nextTick,
  toRaw,
} from "vue";
import {
  VueFlow,
  useVueFlow,
  type Node,
  type Edge,
  type Connection,
} from "@vue-flow/core";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import {
  Activity,
  Network,
  Radio,
  ArrowUpRight,
  Plus,
  Play,
  Pause,
  Save,
  Download,
  Upload,
  Settings,
  Clock,
  ChevronRight,
  Trash2,
  X,
  RefreshCw,
  Link2,
  FileText,
  Check,
  Search,
  ShieldCheck,
  Monitor,
  Printer,
  Server,
  Router,
  Box,
  Image,
  HelpCircle,
  Maximize,
  Power,
} from "@lucide/vue";
import { toPng } from "html-to-image";
import DeviceNode from "./DeviceNode.vue";
import { api, download } from "./api";
import {
  kinds,
  links,
  colors,
  statusNames,
  deviceStatus,
  newDevice,
} from "./graph";
import type {
  Site,
  State,
  Device,
  Probe,
  Sample,
  Incident,
  Status,
} from "./types";

const { screenToFlowCoordinate, fitView } = useVueFlow();
const state = ref<State>({
  sites: [],
  active_site: null,
  monitoring: false,
  context: { interfaces: [] },
  latest: [],
  error: "",
  ap_associations: [],
});
const site = ref<Site | null>(null),
  nodes = shallowRef<Node[]>([]),
  edges = shallowRef<Edge[]>([]);
const selected = ref(""),
  panel = ref("device"),
  editing = ref(false),
  dirty = ref(false),
  toast = ref(""),
  busy = ref(false),
  ready = ref(false);
const linkKind = ref("ethernet"),
  selectedEdge = ref(""),
  templateMenu = ref(false);
const history = ref<Sample[]>([]),
  incidents = ref<Incident[]>([]),
  events = ref<any[]>([]),
  selectedIncident = ref(""),
  evidence = ref<any>(null),
  sampleView = ref<Sample | null>(null);
const probeDraft = ref<Probe | null>(null),
  settingsTab = ref("general"),
  credential = ref({ id: "", password: "", private_key: "", api_token: "" }),
  knownHosts = ref("");
const reportNotes = ref({
  issue: "",
  observed_at: "",
  impact: "",
  recent_changes: "",
  attempts: "",
});
const diagnostic = ref<{ report: any; markdown: string } | null>(null);
const reportPreview = ref(false);
const quitPrompt = ref(false),
  stopped = ref(false);
watch(
  [reportNotes, selectedIncident],
  () => {
    diagnostic.value = null;
  },
  { deep: true },
);
let timer: ReturnType<typeof setInterval>,
  socket: WebSocket | undefined,
  reconnect: ReturnType<typeof setTimeout> | undefined;
const device = computed(() =>
  site.value?.devices.find((d) => d.id === selected.value),
);
const deviceProbes = computed(
  () => site.value?.probes.filter((p) => p.device_id === selected.value) || [],
);
const openCount = computed(
  () => incidents.value.filter((i) => i.status === "open").length,
);
const enabledCount = computed(
  () => site.value?.probes.filter((p) => p.enabled).length || 0,
);
const icons: Record<string, any> = {
  gateway: Router,
  switch: Network,
  ac: ShieldCheck,
  ap: Radio,
  mac: Monitor,
  computer: Monitor,
  server: Server,
  printer: Printer,
  device: Box,
};
const contextUp = computed(() =>
  state.value.context.interfaces.filter(
    (i) => i.up && ["ethernet", "wifi"].includes(i.kind),
  ),
);
const latest = (id: string) => state.value.latest.find((s) => s.probe === id);
const fmtTime = (at: number) =>
  new Date(at * 1000).toLocaleTimeString("zh-CN", { hour12: false });
const fmtDate = (at: number) =>
  new Date(at * 1000).toLocaleString("zh-CN", { hour12: false });
function notify(error: unknown) {
  toast.value = error instanceof Error ? error.message : String(error);
}
async function guarded(fn: () => Promise<void>) {
  busy.value = true;
  try {
    await fn();
  } catch (e) {
    notify(e);
  } finally {
    busy.value = false;
  }
}
function markDirty() {
  dirty.value = true;
}
async function printGraph() {
  await fitView({ padding: 0.15 });
  window.print();
}
function renderGraph() {
  if (!site.value) {
    nodes.value = [];
    edges.value = [];
    return;
  }
  nodes.value = site.value.devices.map((d) => ({
    id: d.id,
    type: "device",
    position: { ...d.position },
    data: {
      device: d,
      status: deviceStatus(site.value!, d.id, state.value.latest),
      editing: editing.value,
    },
  }));
  edges.value = site.value.links.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_interface ? e.source_interface + ":out" : undefined,
    targetHandle: e.target_interface ? e.target_interface + ":in" : undefined,
    type: "smoothstep",
    label: e.label || links[e.kind],
    style: {
      stroke: colors[e.kind],
      strokeWidth: 1.8,
      strokeDasharray:
        e.kind === "wifi" ? "6 4" : e.kind === "management" ? "3 5" : undefined,
    },
    labelStyle: { fill: colors[e.kind], fontSize: 11 },
    data: { kind: e.kind },
  }));
}
watch(editing, () => {
  nodes.value = nodes.value.map((n) => ({
    ...n,
    data: { ...n.data, editing: editing.value },
  }));
});
async function refresh() {
  const incoming = await api<State>("/state");
  state.value = incoming;
  if (!site.value || site.value.id !== incoming.active_site?.id) {
    site.value = incoming.active_site
      ? structuredClone(incoming.active_site)
      : null;
    selected.value = "";
    selectedIncident.value = "";
    diagnostic.value = null;
    reportPreview.value = false;
    reportNotes.value = {
      issue: "",
      observed_at: "",
      impact: "",
      recent_changes: "",
      attempts: "",
    };
    dirty.value = false;
    renderGraph();
    await nextTick();
    fitView({ padding: 0.18, duration: 250 });
  } else if (
    !dirty.value &&
    incoming.active_site &&
    site.value.revision !== incoming.active_site.revision
  ) {
    site.value = structuredClone(incoming.active_site);
    renderGraph();
  } else
    nodes.value = nodes.value.map((n) => ({
      ...n,
      data: {
        ...n.data,
        status: deviceStatus(site.value!, n.id, incoming.latest),
      },
    }));
  if (site.value) {
    history.value = await api("/sites/" + site.value.id + "/history");
    const data = await api("/sites/" + site.value.id + "/incidents");
    incidents.value = data.incidents;
    events.value = data.events;
  }
}
async function save() {
  if (!site.value) return;
  site.value.devices.forEach((d) => {
    const n = nodes.value.find((n) => n.id === d.id);
    if (n) d.position = { ...n.position };
  });
  site.value = await api("/sites", site.value);
  dirty.value = false;
  renderGraph();
  await refresh();
}
async function selectSite(id: string) {
  if (dirty.value && !confirm("有未保存修改，放弃后切换站点？")) return;
  await guarded(async () => {
    await api("/active/" + id, {});
    site.value = null;
    await refresh();
  });
}
async function makeSite(kind: string) {
  templateMenu.value = false;
  await guarded(async () => {
    if (dirty.value && !confirm("有未保存修改，放弃后创建站点？")) return;
    const created = await api<Site>("/templates/" + kind, {});
    await selectSite(created.id);
  });
}
async function toggleMonitor() {
  await guarded(async () => {
    if (dirty.value) await save();
    if (!state.value.monitoring && !enabledCount.value)
      throw new Error("先为设备添加并启用检测，再开始监控");
    await api("/monitoring", { enabled: !state.value.monitoring });
    await refresh();
  });
}
function addDevice(kind: string, position?: { x: number; y: number }) {
  if (!site.value) return;
  if (!position) {
    let slot = site.value.devices.length;
    do {
      position = {
        x: 100 + (slot % 3) * 280,
        y: 100 + Math.floor(slot / 3) * 230,
      };
      slot++;
    } while (
      site.value.devices.some(
        (d) =>
          Math.abs(d.position.x - position!.x) < 240 &&
          Math.abs(d.position.y - position!.y) < 200,
      )
    );
  }
  const d = newDevice(kind, position.x, position.y);
  site.value.devices.push(d);
  selected.value = d.id;
  panel.value = "device";
  markDirty();
  renderGraph();
}
function drop(event: DragEvent) {
  event.preventDefault();
  if (!editing.value) return;
  const kind = event.dataTransfer?.getData("application/macnet");
  if (kind && kinds[kind])
    addDevice(
      kind,
      screenToFlowCoordinate({ x: event.clientX, y: event.clientY }),
    );
}
function connect(connection: Connection) {
  if (!site.value || !editing.value) return;
  const source = site.value.devices.find((d) => d.id === connection.source),
    target = site.value.devices.find((d) => d.id === connection.target);
  const a = connection.sourceHandle?.replace(/:out$/, ""),
    b = connection.targetHandle?.replace(/:in$/, "");
  if (source?.id === target?.id) {
    notify("不能将设备连接到自己");
    return;
  }
  if (
    ["ethernet", "wifi", "usb"].includes(linkKind.value) &&
    [
      source?.interfaces.find((i) => i.id === a),
      target?.interfaces.find((i) => i.id === b),
    ].some((i) => i?.kind !== linkKind.value)
  ) {
    notify("连线类型与接口类型不符，请选择匹配的接口或更改连线类型");
    return;
  }
  site.value.links.push({
    id: crypto.randomUUID(),
    source: connection.source!,
    target: connection.target!,
    source_interface: a || "",
    target_interface: b || "",
    kind: linkKind.value,
    label: "",
  });
  markDirty();
  renderGraph();
}
function removeDevice() {
  if (
    !site.value ||
    !device.value ||
    !confirm("删除此设备及其连线、检测配置？历史记录仍会保留。")
  )
    return;
  site.value.devices = site.value.devices.filter(
    (d) => d.id !== selected.value,
  );
  site.value.probes = site.value.probes.filter(
    (p) => p.device_id !== selected.value,
  );
  site.value.links = site.value.links.filter(
    (e) => e.source !== selected.value && e.target !== selected.value,
  );
  selected.value = "";
  markDirty();
  renderGraph();
}
function removeEdge() {
  if (!site.value) return;
  site.value.links = site.value.links.filter(
    (e) => e.id !== selectedEdge.value,
  );
  selectedEdge.value = "";
  markDirty();
  renderGraph();
}
function addPort() {
  if (!device.value) return;
  device.value.interfaces.push({
    id: "port" + (device.value.interfaces.length + 1),
    label: "新接口",
    kind: "ethernet",
    address: "",
    bssids: [],
  });
  markDirty();
}
function editProbe(p?: Probe) {
  if (!device.value) return;
  probeDraft.value = p
    ? structuredClone(toRaw(p))
    : {
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 16),
        device_id: device.value.id,
        label: "新检测",
        kind: "ping",
        target: device.value.host,
        port: 0,
        interface: "",
        dns_server: "",
        proxy_url: "",
        expected_status: 200,
        interval: 15,
        timeout: 4,
        failures: 2,
        enabled: false,
        collect_snapshot: false,
        required: true,
        process_id: 0,
        ssh_preset: "system",
      };
}
function keepProbe() {
  if (!site.value || !probeDraft.value) return;
  const i = site.value.probes.findIndex((p) => p.id === probeDraft.value!.id);
  if (i < 0) site.value.probes.push(probeDraft.value);
  else site.value.probes[i] = probeDraft.value;
  probeDraft.value = null;
  markDirty();
}
async function runProbe(p: Probe) {
  await guarded(async () => {
    if (dirty.value) await save();
    await api("/probes/" + p.id + "/run", {});
    await refresh();
  });
}
async function exportJSON() {
  if (!site.value) return;
  await guarded(async () => {
    if (dirty.value) await save();
    const data = await api("/sites/" + site.value!.id + "/export");
    download("macnet-topology.json", JSON.stringify(data, null, 2));
    toast.value =
      "导出已移除凭据引用并禁用检测；IP、BSSID 和备注仍保留，分享前请检查";
  });
}
async function importJSON(event: Event) {
  const input = event.target as HTMLInputElement,
    file = input.files?.[0];
  if (!file) return;
  await guarded(async () => {
    if (file.size > 2_000_000) throw new Error("导入文件不能超过 2 MB");
    const created = await api<Site>("/import", JSON.parse(await file.text()));
    await selectSite(created.id);
  });
  input.value = "";
}
async function exportPNG() {
  await guarded(async () => {
    await fitView({ padding: 0.15 });
    await new Promise((r) => setTimeout(r, 200));
    const el = document.querySelector(".vue-flow") as HTMLElement;
    const data = await toPng(el, {
      pixelRatio: 2,
      backgroundColor: "#f5f7fb",
      filter: (n) =>
        !(n as HTMLElement).classList?.contains("vue-flow__controls"),
    });
    const a = document.createElement("a");
    a.href = data;
    a.download = "macnet-topology.png";
    a.click();
  });
}
async function openEvidence(id: string) {
  selectedIncident.value = id;
  evidence.value = await api("/sites/" + site.value!.id + "/incidents/" + id);
}
async function prepareReport() {
  await guarded(async () => {
    if (!site.value) throw new Error("先选择站点");
    if (dirty.value) await save();
    diagnostic.value = await api("/sites/" + site.value.id + "/diagnostics", {
      ...reportNotes.value,
      incident_id: selectedIncident.value,
    });
    reportPreview.value = true;
  });
}
function downloadReport(format: "json" | "md") {
  if (!diagnostic.value) return;
  const stamp = diagnostic.value.report.generated_at_utc.replace(/[:.]/g, "-");
  download(
    "macnet-diagnostic-" + stamp + "." + format,
    format === "json"
      ? JSON.stringify(diagnostic.value.report, null, 2)
      : diagnostic.value.markdown,
    format === "json"
      ? "application/json;charset=utf-8"
      : "text/markdown;charset=utf-8",
  );
}
async function copyGuide() {
  await guarded(async () => {
    if (!diagnostic.value) return;
    await navigator.clipboard.writeText(
      diagnostic.value.report.ai_handoff_instructions,
    );
    toast.value = "排查说明已复制；请自行将报告文件附给 AI";
  });
}
async function saveCredential() {
  await guarded(async () => {
    if (!device.value) throw new Error("请先在画布选择设备");
    credential.value.id =
      device.value.credential_ref || crypto.randomUUID().replaceAll("-", "");
    await api("/credentials", credential.value);
    device.value.credential_ref = credential.value.id;
    credential.value = { id: "", password: "", private_key: "", api_token: "" };
    markDirty();
    await save();
    toast.value = "凭据已写入系统钥匙串，未写入拓扑文件";
  });
}
async function saveKnownHosts() {
  await guarded(async () => {
    await api("/known-hosts", { text: knownHosts.value });
    knownHosts.value = "";
    toast.value = "主机公钥记录已保存";
  });
}
async function deleteSite() {
  if (
    !site.value ||
    !confirm("永久删除当前站点及其检测历史？导出的拓扑文件不受影响。")
  )
    return;
  await guarded(async () => {
    await api("/sites/" + site.value!.id, undefined, "DELETE");
    site.value = null;
    await refresh();
  });
}
function live() {
  socket = new WebSocket(
    (location.protocol === "https:" ? "wss://" : "ws://") +
      location.host +
      "/api/live",
  );
  socket.onmessage = (e) => {
    if (JSON.parse(e.data).kind === "refresh") refresh().catch(notify);
  };
  socket.onclose = () => {
    reconnect = setTimeout(live, 5000);
  };
}
function stopLive() {
  clearInterval(timer);
  if (reconnect) clearTimeout(reconnect);
  if (socket) {
    socket.onclose = null;
    socket.close();
  }
}
async function quitApp() {
  await guarded(async () => {
    await api("/shutdown", {});
    stopped.value = true;
    dirty.value = false;
    stopLive();
  });
}
onMounted(async () => {
  try {
    await api("/session");
    await refresh();
    ready.value = true;
    live();
    timer = setInterval(() => refresh().catch(notify), 15000);
  } catch (e) {
    notify(e);
  }
});
onBeforeUnmount(() => {
  stopLive();
});
window.addEventListener("beforeunload", (e) => {
  if (dirty.value) {
    e.preventDefault();
    e.returnValue = "";
  }
});
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="/" aria-label="MacNet Lab 首页"
        ><span class="brand-mark"><Network :size="22" /></span
        ><span>MacNet<span class="brand-sub">LAB / WORKBENCH</span></span></a
      >
      <div class="sidebar-label">工作空间</div>
      <nav>
        <button
          aria-label="拓扑工作台"
          :class="{ active: panel === 'device' }"
          @click="panel = 'device'"
        >
          <Network :size="18" /><span>拓扑工作台</span></button
        ><button
          aria-label="故障黑匣子"
          :class="{ active: panel === 'incidents' }"
          @click="panel = 'incidents'"
        >
          <Activity :size="18" /><span>故障黑匣子</span
          ><b v-if="openCount">{{ openCount }}</b></button
        ><button
          aria-label="诊断导出"
          :class="{ active: panel === 'report' }"
          @click="panel = 'report'"
        >
          <FileText :size="18" /><span>诊断导出</span></button
        ><button
          aria-label="连接设置"
          :class="{ active: panel === 'settings' }"
          @click="panel = 'settings'"
        >
          <Settings :size="18" /><span>连接设置</span>
        </button>
      </nav>
      <div class="sidebar-label">当前站点</div>
      <select
        aria-label="选择站点"
        :value="site?.id || ''"
        @change="selectSite(($event.target as HTMLSelectElement).value)"
      >
        <option value="" disabled>选择站点</option>
        <option v-for="s in state.sites" :key="s.id" :value="s.id">
          {{ s.name }}
        </option></select
      ><button
        aria-label="创建站点"
        class="new-site"
        @click="templateMenu = !templateMenu"
      >
        <Plus :size="15" /><span>创建站点</span>
      </button>
      <div v-if="templateMenu" class="site-menu">
        <button @click="makeSite('ac')">AC / 多 AP 示例</button
        ><button @click="makeSite('home')">家庭实验室示例</button
        ><button @click="makeSite('empty')">空白站点</button>
      </div>
      <div class="sidebar-bottom">
        <span class="local-badge"><ShieldCheck :size="15" /> 本地优先</span>
        <p>拓扑描述环境<br />证据解释问题</p>
        <small
          >v0.1.0 ·
          {{
            state.context.platform === "win32"
              ? "Windows"
              : state.context.platform === "darwin"
                ? "macOS"
                : "跨平台"
          }}</small
        >
      </div>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <div>
          <div class="breadcrumb">
            工作空间 <ChevronRight :size="12" />
            <span class="site-breadcrumb">{{
              site?.name || "未选择站点"
            }}</span>
            <select
              class="compact-site-select"
              aria-label="选择站点"
              :value="site?.id || ''"
              @change="selectSite(($event.target as HTMLSelectElement).value)"
            >
              <option value="" disabled>选择站点</option>
              <option v-for="s in state.sites" :key="s.id" :value="s.id">
                {{ s.name }}
              </option>
            </select>
          </div>
          <h1>网络运维工作台 <span class="beta-label">LOCAL</span></h1>
        </div>
        <div class="header-actions">
          <button
            class="button"
            @click="guarded(refresh)"
            :disabled="busy"
            title="刷新状态"
          >
            <RefreshCw :size="16" /></button
          ><button class="button" @click="editing = !editing">
            <Network :size="16" />{{
              editing ? "结束编辑" : "编辑拓扑"
            }}</button
          ><button
            class="button primary"
            :disabled="!dirty || busy"
            @click="guarded(save)"
          >
            <Save :size="15" />{{ dirty ? "保存修改" : "已保存" }}
          </button>
        </div>
      </header>
      <div v-if="state.context.note" class="platform-notice">
        <Monitor :size="15" />{{ state.context.note }}
      </div>
      <div v-if="state.error" class="platform-notice danger" role="alert">
        采集器异常：{{ state.error }}。请检查数据目录和检测配置。
      </div>
      <div v-if="toast" class="toast" role="alert">
        <span>{{ toast }}</span
        ><button aria-label="关闭提示" @click="toast = ''">
          <X :size="16" />
        </button>
      </div>
      <div class="summary-strip">
        <div>
          <small>拓扑设备</small
          ><strong>{{ site?.devices.length || 0 }}<span>台</span></strong>
        </div>
        <div>
          <small>当前可用接口</small
          ><strong>{{ contextUp.length }}<span>个</span></strong>
        </div>
        <div>
          <small>未恢复事件</small
          ><strong :class="{ danger: openCount }"
            >{{ openCount }}<span>项</span></strong
          >
        </div>
        <div class="monitor-state">
          <span
            class="status-dot"
            :class="state.monitoring ? 'healthy' : 'paused'"
          ></span>
          <div>
            <small>{{
              state.monitoring ? "正在采集已启用检测" : "自动监控已暂停"
            }}</small
            ><span>{{ enabledCount }} 项检测已启用</span>
          </div>
          <button
            class="button"
            :class="{ primary: !state.monitoring }"
            :disabled="busy || !site"
            @click="toggleMonitor"
          >
            <Pause v-if="state.monitoring" :size="14" /><Play
              v-else
              :size="14"
            />{{ state.monitoring ? "暂停" : "开始监控" }}
          </button>
        </div>
      </div>
      <div class="work-area">
        <section class="canvas-column">
          <div class="canvas-toolbar">
            <div>
              <span class="section-tag">TOPOLOGY</span
              ><strong>{{ editing ? "搭建你的网络" : "网络环境地图" }}</strong
              ><span v-if="dirty" class="unsaved">未保存</span>
            </div>
            <div class="canvas-actions">
              <label v-if="editing"
                >连线<select v-model="linkKind" aria-label="连线类型">
                  <option v-for="(label, key) in links" :key="key" :value="key">
                    {{ label }}
                  </option>
                </select></label
              ><button
                class="icon-button"
                title="适应画布"
                @click="fitView({ padding: 0.18, maxZoom: 1 })"
              >
                <Maximize :size="16" />
              </button>
              <button
                class="icon-button"
                title="导出拓扑 JSON"
                @click="exportJSON"
              >
                <Download :size="16" /></button
              ><label class="icon-button" title="导入拓扑 JSON"
                ><Upload :size="16" /><input
                  type="file"
                  accept=".json"
                  @change="importJSON" /></label
              ><button
                class="icon-button"
                title="导出拓扑 PNG"
                @click="exportPNG"
              >
                <Image :size="16" /></button
              ><button
                class="icon-button"
                title="打印 / 保存 PDF"
                @click="printGraph"
              >
                <Printer :size="16" />
              </button>
            </div>
          </div>
          <div class="canvas-wrap" @drop="drop" @dragover.prevent>
            <div v-if="editing" class="palette">
              <span>设备积木</span
              ><button
                v-for="(label, kind) in kinds"
                :key="kind"
                draggable="true"
                @dragstart="
                  ($event as DragEvent).dataTransfer?.setData(
                    'application/macnet',
                    kind,
                  )
                "
                @click="addDevice(kind)"
              >
                <component :is="icons[kind]" :size="16" />{{ label
                }}<Plus :size="12" />
              </button>
              <p>拖入画布或点击添加<br />从接口圆点拖出连线</p>
            </div>
            <VueFlow
              v-model:nodes="nodes"
              v-model:edges="edges"
              :nodes-draggable="editing"
              :nodes-connectable="editing"
              :delete-key-code="null"
              :min-zoom="0.25"
              :max-zoom="2"
              @nodes-initialized="fitView({ padding: 0.18, maxZoom: 1 })"
              @connect="connect"
              @node-click="
                (e) => {
                  selected = e.node.id;
                  panel = 'device';
                  selectedEdge = '';
                }
              "
              @edge-click="
                (e) => {
                  selectedEdge = e.edge.id;
                }
              "
              @node-drag-stop="markDirty"
              fit-view-on-init
              ><template #node-device="props"
                ><DeviceNode v-bind="props" /></template
              ><Background
                pattern-color="#cbd3e0"
                :gap="22"
                :size="1"
              /><Controls :show-interactive="false" />
              <div v-if="!nodes.length" class="canvas-empty">
                <Network :size="38" />
                <h2>从一张网络地图开始</h2>
                <p>创建示例站点，或开启编辑添加你的第一台设备。</p>
                <button class="button primary" @click="makeSite('ac')">
                  创建示例
                </button>
              </div></VueFlow
            >
            <div class="canvas-legend">
              <span v-for="(label, key) in links" :key="key"
                ><i :style="{ background: colors[key] }"></i>{{ label }}</span
              >
            </div>
            <button
              v-if="selectedEdge && editing"
              class="edge-remove button"
              @click="removeEdge"
            >
              <Trash2 :size="14" />删除选中连线
            </button>
          </div>
          <section class="observation">
            <div class="section-heading">
              <div>
                <span class="section-tag">OBSERVATION</span>
                <h2>当前接入位置</h2>
              </div>
              <span class="muted">{{
                state.context.hostname || "等待识别"
              }}</span>
            </div>
            <div class="interface-list">
              <div v-for="i in contextUp" :key="i.id" class="interface-card">
                <component
                  :is="i.kind === 'wifi' ? Radio : Network"
                  :size="17"
                />
                <div>
                  <strong
                    >{{ i.label }} <code>{{ i.id }}</code></strong
                  >
                  <p>
                    {{
                      i.addresses.filter((a) => !a.includes(":")).join(" · ") ||
                      "无 IPv4"
                    }}
                    <span v-if="i.route.gateway"
                      >/ 网关 {{ i.route.gateway }}</span
                    >
                  </p>
                  <p v-if="i.wifi">
                    {{ i.wifi.ssid || "SSID 未提供" }} ·
                    {{ i.wifi.rssi_dbm ?? "—" }} dBm ·
                    {{ i.wifi.bssid || "BSSID 未提供" }}
                  </p>
                  <p
                    v-if="i.wifi?.identity_note || i.wifi?.reason"
                    class="muted"
                  >
                    {{ i.wifi.identity_note || i.wifi.reason }}
                  </p>
                  <p v-if="i.wifi">
                    {{
                      state.ap_associations.find((a) => a.interface === i.id)
                        ?.device_id
                        ? "对应 AP：" +
                          site?.devices.find(
                            (d) =>
                              d.id ===
                              state.ap_associations.find(
                                (a) => a.interface === i.id,
                              )?.device_id,
                          )?.label
                        : "尚未与唯一 AP 清单匹配"
                    }}
                  </p>
                </div>
                <span class="pill">{{
                  i.kind === "wifi" ? "无线" : "有线"
                }}</span>
              </div>
              <p v-if="!contextUp.length" class="muted">
                尚未识别到可用的物理接口。接口不足不会阻止编辑拓扑。
              </p>
            </div>
          </section>
          <section class="history-panel">
            <div class="section-heading">
              <div>
                <span class="section-tag">EVIDENCE</span>
                <h2>最近检测</h2>
              </div>
              <span class="muted">检测只代表记录中的时间与路径</span>
            </div>
            <div v-if="!history.length" class="empty-inline">
              <Clock :size="20" />
              <div>
                <strong>还没有检测记录</strong>
                <p>选择设备，添加检测后运行一次；示例不会自动探测网络。</p>
              </div>
            </div>
            <table v-else>
              <thead>
                <tr>
                  <th>检测项目</th>
                  <th>状态</th>
                  <th>耗时</th>
                  <th>路径</th>
                  <th>记录时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in history.slice(0, 8)" :key="row.id">
                  <!-- Each result retains its measured path. -->
                  <td>
                    <button class="text-button" @click="sampleView = row">
                      {{
                        site?.probes.find((p) => p.id === row.probe)?.label ||
                        row.probe
                      }}
                    </button>
                  </td>
                  <td>
                    <span class="result-label" :class="row.status">{{
                      statusNames[row.status]
                    }}</span>
                  </td>
                  <td class="mono">
                    {{
                      row.latency_ms !== null
                        ? row.latency_ms.toFixed(1) + " ms"
                        : "—"
                    }}
                  </td>
                  <td class="mono">{{ row.detail.interface || "—" }}</td>
                  <td class="muted mono">{{ fmtTime(row.at) }}</td>
                </tr>
              </tbody>
            </table>
          </section>
        </section>
        <aside class="inspector">
          <template v-if="panel === 'device'"
            ><div class="inspector-heading">
              <span>设备与检测</span><span class="section-tag">INSPECTOR</span>
            </div>
            <div v-if="!device" class="inspector-empty">
              <Search :size="30" />
              <h3>选择一台设备</h3>
              <p>查看服务与检测配置，或开启编辑模式搭建网络拓扑。</p>
              <div class="tip">
                <HelpCircle :size="16" /><span
                  >拓扑是你声明的环境。未检测的设备显示未知，不代表离线。</span
                >
              </div>
            </div>
            <div v-else class="inspector-body">
              <div class="selected-device">
                <span class="large-icon"
                  ><component :is="icons[device.kind]" :size="23"
                /></span>
                <div>
                  <h2>{{ device.label }}</h2>
                  <p>{{ kinds[device.kind] }}</p>
                </div>
                <span
                  class="status-dot"
                  :class="deviceStatus(site!, device.id, state.latest)"
                ></span>
              </div>
              <label
                >设备名称<input
                  v-model="device.label"
                  @input="markDirty" /></label
              ><label
                >管理地址 / IP<input
                  v-model="device.host"
                  placeholder="例如 192.0.2.1"
                  @input="markDirty" /></label
              ><label class="check-row"
                ><input
                  type="checkbox"
                  v-model="device.local"
                  @change="markDirty"
                />这是运行工作台的本机电脑</label
              ><label
                >设备上运行的服务<input
                  :value="device.services.join(', ')"
                  placeholder="如 Nikki, Minecraft, 打印共享"
                  @change="
                    device.services = ($event.target as HTMLInputElement).value
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean);
                    markDirty();
                  "
              /></label>
              <details class="details">
                <summary>
                  接口与 AP 标识 <span>{{ device.interfaces.length }}</span>
                </summary>
                <div
                  v-for="port in device.interfaces"
                  :key="port.id"
                  class="port-editor"
                >
                  <strong>{{ port.id }}</strong
                  ><input
                    v-model="port.label"
                    placeholder="接口名称"
                    @input="markDirty"
                  /><select v-model="port.kind" @change="markDirty">
                    <option value="ethernet">有线</option>
                    <option value="wifi">Wi-Fi</option>
                    <option value="usb">USB</option>
                    <option value="logical">逻辑</option></select
                  ><input
                    v-model="port.address"
                    placeholder="IP / 网段（选填）"
                    @input="markDirty"
                  /><input
                    v-if="port.kind === 'wifi'"
                    :value="port.bssids.join(', ')"
                    placeholder="BSSID，多个用逗号分隔"
                    @change="
                      port.bssids = ($event.target as HTMLInputElement).value
                        .split(',')
                        .map((s) => s.trim())
                        .filter(Boolean);
                      markDirty();
                    "
                  />
                </div>
                <button class="text-button" @click="addPort">
                  <Plus :size="14" />添加接口
                </button>
              </details>
              <details class="details">
                <summary>SSH 与设备备注</summary>
                <label
                  >SSH 用户<input
                    v-model="device.ssh_user"
                    @input="markDirty" /></label
                ><label
                  >SSH 端口<input
                    type="number"
                    v-model.number="device.ssh_port"
                    @input="markDirty" /></label
                ><label
                  >备注<textarea
                    v-model="device.notes"
                    rows="3"
                    @input="markDirty"
                  /></label
                ><button
                  class="text-button"
                  @click="
                    panel = 'settings';
                    settingsTab = 'credentials';
                  "
                >
                  配置系统钥匙串凭据 <ArrowUpRight :size="14" />
                </button>
              </details>
              <div class="subheading">
                <h3>检测项目</h3>
                <button class="text-button" @click="editProbe()">
                  <Plus :size="14" />添加
                </button>
              </div>
              <div v-for="p in deviceProbes" :key="p.id" class="probe-card">
                <div>
                  <span
                    class="status-dot"
                    :class="latest(p.id)?.status || 'unknown'"
                  ></span
                  ><strong>{{ p.label }}</strong
                  ><button class="text-button" @click="editProbe(p)">
                    编辑
                  </button>
                </div>
                <p>
                  {{ p.kind }} · {{ p.interface || "系统默认路径" }} ·
                  {{ p.interval }}s
                </p>
                <p v-if="latest(p.id)" class="probe-message">
                  {{ latest(p.id)?.message }}
                </p>
                <footer>
                  <button
                    v-if="latest(p.id)"
                    class="text-button"
                    @click="sampleView = latest(p.id)!"
                  >
                    结果详情</button
                  ><label class="check-row"
                    ><input
                      type="checkbox"
                      v-model="p.enabled"
                      @change="markDirty"
                    />自动检测</label
                  ><button
                    class="text-button"
                    :disabled="busy"
                    @click="runProbe(p)"
                  >
                    <Play :size="12" />运行一次
                  </button>
                </footer>
              </div>
              <p v-if="!deviceProbes.length" class="muted">
                尚无检测。添加后可手动运行，不必开启自动监控。
              </p>
              <button
                v-if="editing"
                class="text-button danger delete-device"
                @click="removeDevice"
              >
                <Trash2 :size="14" />删除设备
              </button>
            </div></template
          >
          <template v-else-if="panel === 'incidents'"
            ><div class="inspector-heading">
              <span>故障黑匣子</span><Activity :size="17" />
            </div>
            <div class="inspector-body">
              <p class="muted">
                连续失败达到阈值后生成事件；连续两次成功确认恢复。位置变化与停机记为中断。
              </p>
              <div v-if="!incidents.length" class="empty-inline">
                暂无故障事件
              </div>
              <button
                v-for="i in incidents"
                :key="i.id"
                class="incident-card"
                @click="guarded(() => openEvidence(i.id))"
              >
                <span
                  class="pill"
                  :class="i.status === 'open' ? 'failed' : ''"
                  >{{
                    i.status === "open"
                      ? "待恢复"
                      : i.status === "resolved"
                        ? "已恢复"
                        : "已中断"
                  }}</span
                ><strong>{{ i.body.probe_label }}</strong>
                <p>{{ i.body.device }} · {{ fmtDate(i.started) }}</p>
                <small>{{ i.body.result.message }}</small
                ><span class="mono">#{{ i.id }}</span>
              </button>
              <h3 class="subheading">接入与采集事件</h3>
              <div
                v-for="event in events.slice(0, 12)"
                :key="event.id"
                class="event-row"
              >
                <Clock :size="13" />
                <div>
                  {{ event.body.message || event.kind
                  }}<small>{{ fmtDate(event.at) }}</small>
                </div>
              </div>
            </div></template
          >
          <template v-else-if="panel === 'report'">
            <div class="inspector-heading">
              <span>诊断导出</span><FileText :size="17" />
            </div>
            <div class="inspector-body report-panel">
              <div class="tip">
                <span
                  >下载问题日记或 JSON，自行交给 AI。无需账号或 API 密钥。</span
                >
              </div>
              <label
                >问题描述<textarea
                  v-model="reportNotes.issue"
                  rows="3"
                  maxlength="4000"
                  placeholder="例如：手机无法打印，但 Mac 能看到 USB 打印机"
                />
              </label>
              <details class="report-background">
                <summary>补充背景（可选）</summary>
                <label
                  >何时发生<input
                    v-model="reportNotes.observed_at"
                    maxlength="200"
                    placeholder="日期、时间与时区；不确定可留空"
                /></label>
                <label
                  >影响范围<textarea
                    v-model="reportNotes.impact"
                    rows="2"
                    maxlength="2000"
                    placeholder="哪些设备、接口或服务受影响？"
                  />
                </label>
                <label
                  >最近改动<textarea
                    v-model="reportNotes.recent_changes"
                    rows="2"
                    maxlength="4000"
                  />
                </label>
                <label
                  >已尝试的操作与结果<textarea
                    v-model="reportNotes.attempts"
                    rows="2"
                    maxlength="4000"
                  />
                </label>
              </details>
              <label
                >重点故障<select v-model="selectedIncident">
                  <option value="">不指定</option>
                  <option v-for="i in incidents" :value="i.id" :key="i.id">
                    {{ i.body.probe_label }} · {{ fmtDate(i.started) }}
                  </option>
                </select></label
              >
              <p class="muted">
                导出此站点全部保留记录；重点故障只作标记，不删前后证据。
              </p>
              <button
                class="button primary full"
                :disabled="busy || !site"
                @click="prepareReport"
              >
                <FileText :size="15" />{{
                  busy ? "正在生成…" : "生成并预览诊断报告"
                }}
              </button>
              <template v-if="diagnostic">
                <p class="muted">
                  {{ fmtDate(diagnostic.report.generated_at) }} 生成 ·
                  {{ diagnostic.report.coverage.counts.samples }} 条检测 ·
                  {{ diagnostic.report.coverage.counts.incidents }} 个故障
                </p>
                <div class="report-actions">
                  <button class="button" @click="downloadReport('md')">
                    下载问题日记 .md
                  </button>
                  <button class="button" @click="downloadReport('json')">
                    下载诊断 JSON
                  </button>
                  <button class="button" @click="reportPreview = true">
                    查看报告
                  </button>
                  <button class="text-button" @click="copyGuide">
                    复制给 AI 的排查说明
                  </button>
                </div>
              </template>
              <p class="muted">
                常见凭据会脱敏；IP、SSID、BSSID、主机名和备注保留。分享前请检查，勿将原始报告公开上传。
              </p>
            </div>
          </template>
          <template v-else
            ><div class="inspector-heading">
              <span>连接设置</span><Settings :size="17" />
            </div>
            <div class="settings-tabs">
              <button
                :class="{ active: settingsTab === 'general' }"
                @click="settingsTab = 'general'"
              >
                常规</button
              ><button
                :class="{ active: settingsTab === 'credentials' }"
                @click="settingsTab = 'credentials'"
              >
                设备凭据</button
              ><button
                :class="{ active: settingsTab === 'hosts' }"
                @click="settingsTab = 'hosts'"
              >
                主机公钥
              </button>
            </div>
            <div class="inspector-body">
              <template v-if="settingsTab === 'general'"
                ><label v-if="site"
                  >站点名称<input
                    v-model="site.name"
                    :disabled="busy"
                    @input="markDirty"
                /></label>
                <div v-if="state.context.capabilities" class="tip">
                  <span
                    >当前平台：{{
                      state.context.platform === "win32"
                        ? "Windows"
                        : state.context.platform === "darwin"
                          ? "macOS"
                          : "开发预览"
                    }}<br />
                    接口绑定：{{
                      state.context.capabilities.ipv4_interface_binding
                    }}<br />
                    Wi-Fi：{{ state.context.capabilities.wifi }} · 打印：{{
                      state.context.capabilities.printing
                    }}<br />
                    绑定接口的 ICMP：{{
                      state.context.capabilities.interface_bound_ping ===
                      "implemented"
                        ? "已实现"
                        : "未支持，请使用 TCP/DNS/HTTP"
                    }}
                  </span>
                </div>
                <p class="muted">
                  诊断报告在本机生成，在「诊断导出」下载后自行分享；无需配置
                  AI。
                </p>
                <button
                  v-if="state.context.platform === 'win32'"
                  class="button"
                  :disabled="busy"
                  @click="quitPrompt = true"
                >
                  <Power :size="15" />退出工作台
                </button>
                <p v-if="state.context.platform === 'win32'" class="muted">
                  关闭网页不会停止程序；退出工作台会停止本机采集。
                </p> </template
              ><template v-else-if="settingsTab === 'credentials'"
                ><div class="tip">
                  当前设备：{{ device?.label || "请先在画布选择设备" }}
                </div>
                <label
                  >SSH 密码<input
                    type="password"
                    v-model="credential.password"
                    autocomplete="new-password" /></label
                ><label
                  >SSH 私钥（密码或私钥二选一）<textarea
                    v-model="credential.private_key"
                    rows="4"
                    placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                  /></label
                ><label
                  >Mihomo API 密钥<input
                    type="password"
                    v-model="credential.api_token"
                    autocomplete="new-password" /></label
                ><button
                  class="button primary full"
                  :disabled="!device || busy"
                  @click="saveCredential"
                >
                  保存到系统钥匙串
                </button>
                <p class="muted">
                  系统钥匙串不可用时会报错，不降级为明文文件。修改后保存会替换该设备整组凭据。
                </p></template
              ><template v-else
                ><p class="muted">
                  从可信渠道核实服务器公钥后，粘贴 OpenSSH known_hosts
                  记录。此操作替换本工具已有记录；请包含仍需信任的全部主机。
                </p>
                <textarea
                  v-model="knownHosts"
                  rows="8"
                  placeholder="hostname ssh-ed25519 AAAA…"
                /><button
                  class="button primary full"
                  :disabled="busy"
                  @click="saveKnownHosts"
                >
                  保存已核实的公钥
                </button></template
              >
              <hr />
              <label
                >历史保留天数（1–30）<input
                  type="number"
                  :value="state.retention_days || 7"
                  min="1"
                  max="30"
                  @change="
                    guarded(async () => {
                      await api('/retention', {
                        days: Number(($event.target as HTMLInputElement).value),
                      });
                      await refresh();
                    })
                  "
              /></label>
              <div class="tip">
                <ShieldCheck :size="17" /><span
                  >工作台仅监听本机。首版不开放公网管理，不自动修改
                  LAN、DHCP、防火墙或路由。</span
                >
              </div>
              <button
                class="text-button danger"
                :disabled="!site || busy"
                @click="deleteSite"
              >
                删除当前站点与历史
              </button>
            </div></template
          >
        </aside>
      </div>
    </div>
    <div
      v-if="probeDraft"
      class="modal-backdrop"
      @click.self="probeDraft = null"
    >
      <section
        class="modal"
        role="dialog"
        aria-modal="true"
        aria-label="检测配置"
      >
        <header>
          <h2>检测配置</h2>
          <button
            class="icon-button"
            aria-label="关闭检测配置"
            @click="probeDraft = null"
          >
            <X :size="19" />
          </button>
        </header>
        <label>名称<input v-model="probeDraft.label" /></label>
        <div class="form-grid">
          <label
            >检测类型<select
              v-model="probeDraft.kind"
              @change="
                if (probeDraft.kind === 'printing') probeDraft.timeout = 15;
              "
            >
              <option
                v-for="(label, key) in {
                  ping: 'ICMP 连通性',
                  tcp: 'TCP 端口',
                  dns: 'DNS 解析',
                  http: 'HTTP / HTTPS',
                  proxy: '显式代理请求',
                  mihomo: 'Mihomo 控制接口',
                  minecraft_java: 'Minecraft Java',
                  minecraft_bedrock: 'Minecraft Bedrock',
                  printing: '本机打印状态',
                  resources: '本机资源',
                  ssh: 'SSH 只读快照',
                }"
                :key="key"
                :value="key"
              >
                {{ label }}
              </option>
            </select></label
          ><label
            >端口<input
              type="number"
              v-model.number="probeDraft.port"
              min="0"
              max="65535"
          /></label>
        </div>
        <label
          >目标地址 / 域名 / 完整 URL<input
            v-model="probeDraft.target"
            placeholder="如 192.0.2.1 或 https://example.com" /></label
        ><label
          >采集源接口<select v-model="probeDraft.interface">
            <option value="">系统默认路径（不承诺指定接口）</option>
            <option
              v-for="i in state.context.interfaces"
              :key="i.id"
              :value="i.id"
            >
              {{ i.label }} · {{ i.id }}
            </option>
          </select></label
        ><label
          >此路径的 DNS 服务器<input
            v-model="probeDraft.dns_server"
            placeholder="绑定接口解析域名时需填写" /></label
        ><label v-if="probeDraft.kind === 'proxy'"
          >显式代理地址<input
            v-model="probeDraft.proxy_url"
            placeholder="socks5h://192.0.2.1:7891"
        /></label>
        <div class="form-grid">
          <label
            >检测间隔 / 秒<input
              type="number"
              v-model.number="probeDraft.interval"
              min="5" /></label
          ><label
            >超时 / 秒<input
              type="number"
              v-model.number="probeDraft.timeout"
              min="1"
              max="30" /></label
          ><label
            >连续失败阈值<input
              type="number"
              v-model.number="probeDraft.failures"
              min="1"
              max="10" /></label
          ><label v-if="['http', 'proxy', 'mihomo'].includes(probeDraft.kind)"
            >预期 HTTP 状态<input
              type="number"
              v-model.number="probeDraft.expected_status"
          /></label>
        </div>
        <label v-if="probeDraft.kind === 'ssh'"
          >只读命令组<select v-model="probeDraft.ssh_preset">
            <option value="system">Linux 系统概况</option>
            <option value="openwrt">OpenWrt / KWRT 日志</option>
            <option value="nikki">Nikki 服务状态</option>
          </select></label
        ><label v-if="probeDraft.kind === 'resources'"
          >服务进程 PID（0 表示只读整机资源）<input
            type="number"
            v-model.number="probeDraft.process_id"
            min="0" /></label
        ><label class="check-row"
          ><input
            type="checkbox"
            v-model="probeDraft.enabled"
          />启用自动检测（还需开始监控）</label
        ><label class="check-row"
          ><input
            type="checkbox"
            v-model="probeDraft.required"
          />此接口必须在线，断开计为异常</label
        ><label class="check-row"
          ><input
            type="checkbox"
            v-model="probeDraft.collect_snapshot"
          />故障时允许通过 SSH 补采只读快照</label
        >
        <footer>
          <button
            class="button danger"
            @click="
              site!.probes = site!.probes.filter(
                (p) => p.id !== probeDraft!.id,
              );
              probeDraft = null;
              markDirty();
            "
          >
            删除检测</button
          ><button class="button primary" @click="keepProbe">应用到草稿</button>
        </footer>
      </section>
    </div>
    <div
      v-if="sampleView"
      class="modal-backdrop"
      @click.self="sampleView = null"
    >
      <section
        class="modal wide"
        role="dialog"
        aria-modal="true"
        aria-label="检测结果详情"
      >
        <header>
          <h2>检测结果详情</h2>
          <button
            class="icon-button"
            aria-label="关闭检测结果"
            @click="sampleView = null"
          >
            <X :size="20" />
          </button>
        </header>
        <p>
          {{ statusNames[sampleView.status] }} · {{ fmtDate(sampleView.at) }}
        </p>
        <pre>{{ JSON.stringify(sampleView, null, 2) }}</pre>
      </section>
    </div>
    <div
      v-if="reportPreview && diagnostic"
      class="modal-backdrop"
      @click.self="reportPreview = false"
    >
      <section
        class="modal wide"
        role="dialog"
        aria-modal="true"
        aria-label="诊断报告预览"
      >
        <header>
          <h2>诊断报告预览</h2>
          <button
            class="icon-button"
            aria-label="关闭报告预览"
            @click="reportPreview = false"
          >
            <X :size="20" />
          </button>
        </header>
        <p>报告仅在本机生成。请检查网络标识和自由文本，再自行决定分享给谁。</p>
        <div class="report-actions">
          <button class="button primary" @click="downloadReport('md')">
            下载问题日记 .md
          </button>
          <button class="button" @click="downloadReport('json')">
            下载诊断 JSON
          </button>
          <button class="button" @click="copyGuide">复制排查说明</button>
        </div>
        <p v-if="diagnostic.markdown.length > 30000" class="muted">
          预览仅显示前 30,000 字符；下载文件包含本次报告全部记录。
        </p>
        <pre>{{ diagnostic.markdown.slice(0, 30000) }}</pre>
      </section>
    </div>
    <div
      v-if="quitPrompt"
      class="modal-backdrop"
      @click.self="!stopped && (quitPrompt = false)"
    >
      <section
        class="modal quit-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="退出工作台"
      >
        <header>
          <h2>{{ stopped ? "工作台已停止" : "退出工作台？" }}</h2>
        </header>
        <p v-if="stopped">
          采集已停止，可以关闭页面。重新打开程序后，已保存的数据仍可使用。
        </p>
        <template v-else>
          <p>
            退出会停止本机工作台和采集，已保存的站点和记录将保留。
          </p>
          <p v-if="dirty">
            有未保存的拓扑修改。可取消并保存，或放弃修改后退出。
          </p>
          <div class="evidence-actions">
            <button class="button" :disabled="busy" @click="quitPrompt = false">
              取消
            </button>
            <button class="button primary" :disabled="busy" @click="quitApp">
              {{ dirty ? "放弃修改并退出" : "确认退出" }}
            </button>
          </div>
        </template>
      </section>
    </div>
    <div v-if="evidence" class="modal-backdrop" @click.self="evidence = null">
      <section
        class="modal wide"
        role="dialog"
        aria-modal="true"
        aria-label="事件证据"
      >
        <header>
          <div>
            <small class="section-tag">INCIDENT / {{ selectedIncident }}</small>
            <h2>现场证据</h2>
          </div>
          <button
            class="icon-button"
            aria-label="关闭事件证据"
            @click="evidence = null"
          >
            <X :size="20" />
          </button>
        </header>
        <div class="evidence-actions">
          <button
            class="button"
            @click="
              guarded(async () => {
                await api(
                  '/sites/' +
                    site!.id +
                    '/incidents/' +
                    selectedIncident +
                    '/snapshot',
                  {},
                );
                await openEvidence(selectedIncident);
              })
            "
          >
            补采本机快照</button
          ><button
            class="button primary"
            @click="
              evidence = null;
              panel = 'report';
            "
          >
            生成完整诊断报告
          </button>
        </div>
        <pre>{{ JSON.stringify(evidence, null, 2) }}</pre>
      </section>
    </div>
  </div>
</template>
