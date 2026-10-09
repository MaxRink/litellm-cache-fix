import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { ReactNode } from "react";
import { fetchClient } from "@/lib/http/api";
import { recordUiEvent, setPageNavigationEnabled } from "@/lib/telemetry/uiEvents";
import { type TelemetrySettings, useUpdateTelemetrySettings } from "./useTelemetrySettings";

const settingsWith = (pageNavigation: boolean): TelemetrySettings =>
  ({
    groups: [
      { group: "heartbeat", enabled: true, requires: null },
      { group: "page_navigation", enabled: pageNavigation, requires: "heartbeat" },
    ],
  }) as unknown as TelemetrySettings;

const saveGroups = async (saved: TelemetrySettings): Promise<void> => {
  vi.spyOn(fetchClient, "PUT").mockResolvedValue({ data: saved, response: new Response() });
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useUpdateTelemetrySettings(), { wrapper });
  await act(() => result.current.mutateAsync(["heartbeat"]));
};

describe("useUpdateTelemetrySettings", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setPageNavigationEnabled(false);
  });

  it("stops sending UI events as soon as page navigation is saved off", async () => {
    setPageNavigationEnabled(true);
    await saveGroups(settingsWith(false));
    const post = vi.spyOn(fetchClient, "POST").mockResolvedValue({ data: undefined, response: new Response() });

    recordUiEvent({ page: "telemetry", action: "click", target: "tab=ui" });

    expect(post).not.toHaveBeenCalled();
  });

  it("starts sending UI events as soon as page navigation is saved on", async () => {
    await saveGroups(settingsWith(true));
    const post = vi.spyOn(fetchClient, "POST").mockResolvedValue({ data: undefined, response: new Response() });

    recordUiEvent({ page: "telemetry", action: "click", target: "tab=ui" });

    expect(post).toHaveBeenCalledOnce();
  });
});
