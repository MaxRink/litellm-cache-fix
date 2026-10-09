import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchClient } from "@/lib/http/api";
import { recordUiEvent, setPageNavigationEnabled } from "./uiEvents";

describe("recordUiEvent", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setPageNavigationEnabled(false);
  });

  it("sends nothing until the proxy says page navigation is on", () => {
    const post = vi.spyOn(fetchClient, "POST").mockResolvedValue({ data: undefined, response: new Response() });

    recordUiEvent({ page: "teams", action: "view" });

    expect(post).not.toHaveBeenCalled();
  });

  it("posts the event to the proxy telemetry route", () => {
    setPageNavigationEnabled(true);
    const post = vi.spyOn(fetchClient, "POST").mockResolvedValue({ data: undefined, response: new Response() });

    recordUiEvent({ page: "teams", action: "click", target: "tab=members" });

    expect(post).toHaveBeenCalledWith("/telemetry/ui_events", {
      body: { page: "teams", action: "click", target: "tab=members" },
    });
  });

  it("swallows a failed post so telemetry never breaks the page", async () => {
    setPageNavigationEnabled(true);
    vi.spyOn(fetchClient, "POST").mockRejectedValue(new Error("offline"));
    const unhandled = vi.fn();
    process.on("unhandledRejection", unhandled);

    recordUiEvent({ page: "teams", action: "view" });
    await new Promise((resolve) => setTimeout(resolve, 0));

    process.off("unhandledRejection", unhandled);
    expect(unhandled).not.toHaveBeenCalled();
  });
});
