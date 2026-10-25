<script setup lang="ts">
import { computed } from "vue";
import { useVueFlow } from "@vue-flow/core";
const { nodes, viewport, dimensions, setCenter } = useVueFlow();
const bounds = computed(() => {
  const points = nodes.value;
  const x = Math.min(0, ...points.map((n) => n.position.x)) - 60;
  const y = Math.min(0, ...points.map((n) => n.position.y)) - 60;
  const width =
    Math.max(
      600,
      ...points.map((n) => n.position.x + (n.dimensions.width || 240)),
    ) -
    x +
    60;
  const height =
    Math.max(
      350,
      ...points.map((n) => n.position.y + (n.dimensions.height || 160)),
    ) -
    y +
    60;
  return { x, y, width, height };
});
const view = computed(() => ({
  x: -viewport.value.x / viewport.value.zoom,
  y: -viewport.value.y / viewport.value.zoom,
  width: dimensions.value.width / viewport.value.zoom,
  height: dimensions.value.height / viewport.value.zoom,
}));
function jump(event: MouseEvent) {
  const svg = event.currentTarget as SVGSVGElement;
  const point = svg.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  const transform = svg.getScreenCTM();
  if (!transform) return;
  const world = point.matrixTransform(transform.inverse());
  setCenter(world.x, world.y, { duration: 180 });
}
</script>
<template>
  <div class="matrix-map" v-if="nodes.length">
    <span>MINI-MAP</span>
    <svg
      :viewBox="`${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`"
      @click="jump"
      role="img"
      aria-label="拓扑缩略图，点击定位"
    >
      <rect
        v-for="n in nodes"
        :key="n.id"
        :x="n.position.x"
        :y="n.position.y"
        :width="n.dimensions.width || 240"
        :height="n.dimensions.height || 160"
        :class="n.data.status"
        rx="14"
      />
      <rect
        class="map-viewport"
        :x="view.x"
        :y="view.y"
        :width="view.width"
        :height="view.height"
      />
    </svg>
  </div>
</template>
