import type { Device, Sample, Site } from "./types";
import { deviceStatus } from "./graph";

// A successful service check is not proof that a whole device is online.
export function evidenceMetrics(site: Site | null, samples: Sample[]) {
  const devices = site?.devices || [];
  return {
    total: devices.length,
    healthy: devices.filter(
      (d) => deviceStatus(site!, d.id, samples) === "healthy",
    ).length,
    failed: devices.filter(
      (d) => deviceStatus(site!, d.id, samples) === "failed",
    ).length,
    unknown: devices.filter(
      (d) => deviceStatus(site!, d.id, samples) === "unknown",
    ).length,
  };
}

export function deviceEvidence(site: Site, device: Device, samples: Sample[]) {
  const ids = new Set(
    site.probes.filter((p) => p.device_id === device.id).map((p) => p.id),
  );
  const rows = samples
    .filter((s) => ids.has(s.probe))
    .sort((a, b) => b.at - a.at);
  const latency = rows.find((s) => s.latency_ms !== null);
  const resources = rows.find(
    (s) => site.probes.find((p) => p.id === s.probe)?.kind === "resources",
  );
  const percent = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value)
      ? Math.min(100, Math.max(0, value))
      : null;
  return {
    latency: latency?.latency_ms ?? null,
    at: rows[0]?.at ?? null,
    cpu: percent(resources?.detail.cpu_percent),
    memory: percent(resources?.detail.memory_percent),
  };
}

// Presentation only: never infer or create physical connections from device kinds.
export function layeredPositions(devices: Device[]) {
  const tier: Record<string, number> = { gateway: 0, ac: 1, switch: 1, ap: 2 };
  const groups = [0, 1, 2, 3].map((level) =>
    devices.filter((d) => (tier[d.kind] ?? 3) === level),
  );
  const max = Math.max(1, ...groups.map((g) => g.length));
  return groups.flatMap((group, level) =>
    group.map((d, i) => ({
      id: d.id,
      position: {
        x: 60 + level * 340,
        y: 60 + (max - group.length) * 125 + i * 250,
      },
    })),
  );
}
