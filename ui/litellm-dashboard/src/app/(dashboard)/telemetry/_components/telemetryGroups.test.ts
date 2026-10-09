import { describe, expect, it } from "vitest";
import type { TelemetryGroup } from "@/app/(dashboard)/hooks/telemetry/useTelemetrySettings";
import { canEnable, toggleGroup, type Requires } from "./telemetryGroups";

const REQUIRES: Requires = new Map<TelemetryGroup, TelemetryGroup | null>([
  ["heartbeat", null],
  ["request_success", "heartbeat"],
  ["token_info", "request_success"],
  ["request_taxonomy", "token_info"],
  ["event_details", "request_taxonomy"],
  ["instance_configuration", "heartbeat"],
  ["page_navigation", "heartbeat"],
]);

const ALL = new Set<TelemetryGroup>(REQUIRES.keys());

describe("toggleGroup", () => {
  it("turning heartbeat off turns every other group off", () => {
    expect(toggleGroup("heartbeat", false, ALL, REQUIRES)).toEqual(new Set());
  });

  it("turning a middle group off keeps its parents and siblings and drops its descendants", () => {
    expect(toggleGroup("token_info", false, ALL, REQUIRES)).toEqual(
      new Set(["heartbeat", "request_success", "instance_configuration", "page_navigation"]),
    );
  });

  it("a group cannot be turned on before the group it needs", () => {
    const heartbeatOnly = new Set<TelemetryGroup>(["heartbeat"]);
    expect(canEnable("token_info", heartbeatOnly, REQUIRES)).toBe(false);
    expect(toggleGroup("token_info", true, heartbeatOnly, REQUIRES)).toBe(heartbeatOnly);
    expect(toggleGroup("request_success", true, heartbeatOnly, REQUIRES)).toEqual(
      new Set(["heartbeat", "request_success"]),
    );
  });
});
