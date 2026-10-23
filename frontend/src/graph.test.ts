import { describe, it, expect } from "vitest";
import { reactive, toRaw } from "vue";
import { deviceStatus, newDevice } from "./graph";
import type { Site, Probe, Sample } from "./types";

const probe = (id: string) => ({ id, device_id: "mac" }) as Probe;
const site = { probes: [probe("one"), probe("two")] } as Site;
const row = (probe: string, status: Sample["status"]) =>
  ({ probe, status }) as Sample;
describe("device status uses complete evidence", () => {
  it("does not turn a missing result into healthy", () => {
    expect(deviceStatus(site, "mac", [row("one", "healthy")])).toBe("unknown");
  });
  it("prioritizes failure and requires all successful results", () => {
    expect(
      deviceStatus(site, "mac", [row("one", "healthy"), row("two", "failed")]),
    ).toBe("failed");
    expect(
      deviceStatus(site, "mac", [row("one", "healthy"), row("two", "healthy")]),
    ).toBe("healthy");
    expect(deviceStatus(site, "mac", [])).toBe("unknown");
  });
  it("does not give an unmonitored node a healthy badge", () => {
    expect(deviceStatus(site, "other", [])).toBe("unknown");
  });
});
describe("topology drafts", () => {
  it("provides three physical interfaces on one Mac node", () => {
    expect(newDevice("mac", 2, 3).interfaces.map((p) => p.kind)).toEqual([
      "ethernet",
      "wifi",
      "usb",
    ]);
  });
  it("can edit reactive probes without mutating the saved draft", () => {
    const original = reactive({ id: "probe", target: "192.0.2.1" });
    const draft = structuredClone(toRaw(original));
    draft.target = "192.0.2.2";
    expect(original.target).toBe("192.0.2.1");
  });
});

it("creates a platform-neutral operations computer with all physical port types", () => {
  const device = newDevice("computer", 0, 0);
  expect(device.kind).toBe("computer");
  expect(device.interfaces.map((i) => i.kind)).toEqual([
    "ethernet",
    "wifi",
    "usb",
  ]);
});
