import { fetchClient } from "@/lib/http/api";
import type { components } from "@/lib/http/schema";

export type UiEvent = components["schemas"]["UIEventBody"];

let pageNavigationEnabled = false;

export const setPageNavigationEnabled = (enabled: boolean): void => {
  pageNavigationEnabled = enabled;
};

export const refreshPageNavigationEnabled = async (): Promise<void> => {
  const { data } = await fetchClient.GET("/telemetry/ui_events/enabled");
  setPageNavigationEnabled(data?.enabled ?? false);
};

/**
 * Fire-and-forget Admin UI telemetry, sent only while the proxy's Page navigation group is on. Callers only pass
 * route segments and values from code, never user data, and the proxy re-validates the shape.
 */
export const recordUiEvent = (event: UiEvent): void => {
  if (!pageNavigationEnabled) return;
  fetchClient.POST("/telemetry/ui_events", { body: event }).catch(() => undefined);
};
