<script setup lang="ts">
import { Handle, Position } from "@vue-flow/core";
import {
  Router,
  Network,
  Radio,
  Monitor,
  Server,
  Printer,
  Box,
  Shield,
} from "@lucide/vue";
import { kinds, statusNames } from "./graph";
import type { Device, Status } from "./types";
const props = defineProps<{
  data: { device: Device; status: Status; editing: boolean };
}>();
const icons: Record<string, any> = {
  gateway: Router,
  switch: Network,
  ac: Shield,
  ap: Radio,
  mac: Monitor,
  computer: Monitor,
  server: Server,
  printer: Printer,
  device: Box,
};
</script>
<template>
  <div class="device-node" :class="[data.device.kind, data.status]">
    <div class="device-head">
      <span class="node-icon"
        ><component :is="icons[data.device.kind] || Box" :size="18"
      /></span>
      <div class="node-title">
        <small>{{ kinds[data.device.kind] }}</small
        ><strong>{{ data.device.label }}</strong>
      </div>
      <span
        class="status-dot"
        :class="data.status"
        :title="'已配置检测：' + statusNames[data.status]"
      ></span>
    </div>
    <div class="node-address">
      {{
        data.device.host ||
        (data.device.local
          ? "本机 · 系统识别"
          : data.device.kind === "printer" &&
              data.device.interfaces.every((p) => p.kind === "usb")
            ? "USB 外设 · 无需 IP"
            : "未配置管理地址")
      }}
    </div>
    <div
      v-for="port in data.device.interfaces"
      :key="port.id"
      class="node-port"
    >
      <Handle
        type="target"
        :position="Position.Left"
        :id="port.id + ':in'"
        :style="{ top: '50%', left: '-16px' }"
        :connectable="data.editing"
      /><span>{{ port.label || port.id }}</span
      ><small>{{
        port.kind === "ethernet"
          ? "ETH"
          : port.kind === "wifi"
            ? "Wi-Fi"
            : port.kind.toUpperCase()
      }}</small
      ><Handle
        type="source"
        :position="Position.Right"
        :id="port.id + ':out'"
        :style="{ top: '50%', right: '-16px' }"
        :connectable="data.editing"
      />
    </div>
    <div v-if="data.device.services.length" class="node-services">
      <span v-for="s in data.device.services" :key="s">{{ s }}</span>
    </div>
  </div>
</template>
