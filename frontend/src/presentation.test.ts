import { describe, expect, it } from "vitest";
import {
  deviceEvidence,
  evidenceMetrics,
  layeredPositions,
} from "./presentation";
import { newDevice } from "./graph";
import type { Probe, Sample, Site } from "./types";

const device = newDevice("computer", 0, 0);
const probe = {
  id: "resources",
  device_id: device.id,
  kind: "resources",
} as Probe;
const site = {
  devices: [device, newDevice("ap", 0, 0)],
  probes: [probe],
} as Site;
const sample = {
  probe: probe.id,
  at: 100,
  status: "healthy",
  message: "已读取本机资源",
  latency_ms: null,
  detail: { cpu_percent: 17, memory_percent: 45 },
} as Sample;
describe("matrix displays measured evidence", () => {
  it("keeps unmeasured devices unknown instead of inventing healthy counts", () => {
    expect(evidenceMetrics(site, [])).toEqual({
      total: 2,
      healthy: 0,
      failed: 0,
      unknown: 2,
    });
    expect(evidenceMetrics(site, [sample])).toEqual({
      total: 2,
      healthy: 1,
      failed: 0,
      unknown: 1,
    });
    expect(evidenceMetrics(null, [])).toEqual({
      total: 0,
      healthy: 0,
      failed: 0,
      unknown: 0,
    });
  });
  it("does not fabricate latency or resource readings", () => {
    expect(deviceEvidence(site, device, [])).toEqual({
      latency: null,
      at: null,
      cpu: null,
      memory: null,
    });
    expect(deviceEvidence(site, device, [sample])).toEqual({
      latency: null,
      at: 100,
      cpu: 17,
      memory: 45,
    });
  });
  it("takes the latest measured resource result and ignores other devices", () => {
    const old = {
      ...sample,
      at: 20,
      detail: { cpu_percent: 90, memory_percent: 91 },
    };
    expect(deviceEvidence(site, device, [old, sample]).cpu).toBe(17);
    expect(deviceEvidence(site, site.devices[1], [sample]).cpu).toBeNull();
  });
  it("only rearranges positions, leaving topology semantics intact", () => {
    const before = structuredClone(site);
    const positions = layeredPositions(site.devices);
    expect(new Set(positions.map((p) => p.id)).size).toBe(2);
    expect(
      positions.find((p) => p.id === device.id)!.position.x,
    ).toBeGreaterThan(
      positions.find((p) => p.id === site.devices[1].id)!.position.x,
    );
    expect(site).toEqual(before);
  });
});
