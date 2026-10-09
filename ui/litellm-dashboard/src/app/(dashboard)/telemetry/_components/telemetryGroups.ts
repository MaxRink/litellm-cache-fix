import type { TelemetryGroup } from "@/app/(dashboard)/hooks/telemetry/useTelemetrySettings";

export interface GroupCopy {
  readonly title: string;
  readonly sends: string;
  readonly helps: string;
}

export const PROXY_GROUPS: readonly TelemetryGroup[] = [
  "heartbeat",
  "request_success",
  "token_info",
  "request_taxonomy",
  "event_details",
  "instance_configuration",
];

export const UI_GROUPS: readonly TelemetryGroup[] = ["page_navigation"];

export const GROUP_COPY: Readonly<Record<TelemetryGroup, GroupCopy>> = {
  heartbeat: {
    title: "Heartbeat",
    sends: "A random instance id, the LiteLLM version, the report window start and end, and which groups are on.",
    helps: "Tells us which versions are running, so we know who a bug fix or a deprecation affects.",
  },
  request_success: {
    title: "Request success",
    sends:
      "Per endpoint (e.g. /chat/completions): request count, LiteLLM and provider status class (2xx/4xx/5xx), stream yes/no, LiteLLM cache hit, whether the Rust gateway handled it, provider attempts, and latency histograms for total time, time to response headers and time to first token.",
    helps: "Lets us catch error-rate and latency regressions in a release, and compare the Rust gateway with Python.",
  },
  token_info: {
    title: "Token info",
    sends:
      "Input, output, cache read and cache write token sums per row, and provider prompt-cache hit yes/no. Never per request.",
    helps: "Shows when a change breaks provider prompt caching or token counting.",
  },
  request_taxonomy: {
    title: "Request taxonomy",
    sends:
      "The provider (e.g. anthropic) and a salted hash of the deployment id on each row, plus one row per provider attempt.",
    helps: "Turns 'errors went up' into 'errors went up for one provider', and shows retries and fallbacks.",
  },
  event_details: {
    title: "Event details",
    sends:
      "Message block counts and block types (text, image, tool_use, ...), allowlisted request header names (never values), and provider time to first token per attempt.",
    helps: "Shows which request shapes and client tools fail, so we can test the ones people actually send.",
  },
  instance_configuration: {
    title: "Instance configuration",
    sends: "Names of allowlisted config keys that are set. Never their values.",
    helps: "Shows which features are configured, so we know what an upgrade must keep working.",
  },
  page_navigation: {
    title: "Page navigation",
    sends:
      "Admin UI page views and tab switches as route names (e.g. models-and-endpoints, tab=health). No ids, names or text you type.",
    helps: "Shows which pages and tabs people use, so we can focus UI work on them.",
  },
};

export type Requires = ReadonlyMap<TelemetryGroup, TelemetryGroup | null>;

const dependents = (group: TelemetryGroup, requires: Requires): readonly TelemetryGroup[] =>
  [...requires.entries()]
    .filter(([, parent]) => parent === group)
    .flatMap(([child]) => [child, ...dependents(child, requires)]);

export const canEnable = (group: TelemetryGroup, enabled: ReadonlySet<TelemetryGroup>, requires: Requires): boolean => {
  const parent = requires.get(group) ?? null;
  return parent === null || enabled.has(parent);
};

/** Turning a group off also turns off every group that depends on it; turning one on needs its parent on */
export const toggleGroup = (
  group: TelemetryGroup,
  on: boolean,
  enabled: ReadonlySet<TelemetryGroup>,
  requires: Requires,
): ReadonlySet<TelemetryGroup> => {
  if (on) return canEnable(group, enabled, requires) ? new Set([...enabled, group]) : enabled;
  const removed = new Set([group, ...dependents(group, requires)]);
  return new Set([...enabled].filter((g) => !removed.has(g)));
};
