export type Status = "healthy" | "failed" | "unknown" | "paused" | "gap";
export type Port = {
  id: string;
  label: string;
  kind: string;
  address: string;
  bssids: string[];
};
export type Device = {
  id: string;
  label: string;
  kind: string;
  host: string;
  interfaces: Port[];
  services: string[];
  position: { x: number; y: number };
  credential_ref: string;
  ssh_port: number;
  ssh_user: string;
  notes: string;
  local: boolean;
};
export type Link = {
  id: string;
  source: string;
  target: string;
  source_interface: string;
  target_interface: string;
  kind: string;
  label: string;
};
export type Probe = {
  id: string;
  device_id: string;
  label: string;
  kind: string;
  target: string;
  port: number;
  interface: string;
  dns_server: string;
  proxy_url: string;
  expected_status: number;
  interval: number;
  timeout: number;
  failures: number;
  enabled: boolean;
  collect_snapshot: boolean;
  required: boolean;
  process_id: number;
  ssh_preset: "system" | "openwrt" | "nikki";
};
export type Site = {
  schema_version: 1;
  id: string;
  name: string;
  revision: number;
  devices: Device[];
  links: Link[];
  probes: Probe[];
};
export type Sample = {
  id?: number;
  probe: string;
  at: number;
  status: Status;
  message: string;
  latency_ms: number | null;
  detail: Record<string, unknown>;
};
export type Incident = {
  id: string;
  site: string;
  probe: string;
  started: number;
  ended: number | null;
  status: string;
  body: { probe_label: string; device: string; result: Sample };
};
export type Context = {
  platform?: string;
  macos_supported?: boolean;
  supported_platform?: boolean;
  capabilities?: Record<string, string>;
  hostname?: string;
  note?: string;
  interfaces: Array<{
    id: string;
    label: string;
    kind: string;
    up: boolean;
    addresses: string[];
    speed_mbps: number | null;
    dns_servers: string[];
    route: Record<string, string>;
    wifi?: {
      ssid: string | null;
      bssid: string | null;
      rssi_dbm: number | null;
      tx_rate_mbps: number | null;
      identity_note?: string;
      available?: boolean;
      reason?: string;
      signal_quality_percent?: number;
    };
  }>;
};
export type State = {
  sites: Array<{ id: string; name: string }>;
  active_site: Site | null;
  monitoring: boolean;
  retention_days?: number;
  context: Context;
  latest: Sample[];
  error: string;
  ap_associations: Array<{
    interface: string;
    device_id: string | null;
    bssid: string;
    ambiguous: boolean;
  }>;
};
