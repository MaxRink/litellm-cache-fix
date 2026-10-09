"use client";

import { useState } from "react";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUrlTab } from "@/hooks/useUrlTab";
import {
  type TelemetryGroup,
  type TelemetrySettings,
  useTelemetrySettings,
  useUpdateTelemetrySettings,
} from "@/app/(dashboard)/hooks/telemetry/useTelemetrySettings";
import { GROUP_COPY, PROXY_GROUPS, UI_GROUPS, canEnable, toggleGroup, type Requires } from "./telemetryGroups";

const TABS = ["proxy", "ui"] as const;

const destinationText = (settings: TelemetrySettings): string => {
  const every = `every ${settings.flush_interval_seconds} seconds`;
  switch (settings.destination) {
    case "https":
      return `Each proxy worker sends one aggregated JSON report ${every} by HTTPS POST to the endpoint in LITELLM_TELEMETRY_ENDPOINT, and once more on shutdown. A failed send is retried with the next window.`;
    case "local_table":
      return `Each proxy worker writes one aggregated report ${every} to the LiteLLM_TelemetryReport table in this proxy's database, and once more on shutdown. Windows with no traffic are skipped. Nothing leaves the proxy: reports are kept for ${settings.retention_days} days and a proxy admin can download them from GET /telemetry/reports to share by hand.`;
    case "none":
      return "This proxy has no database and no LITELLM_TELEMETRY_ENDPOINT, so nothing is collected or sent.";
  }
};

function GroupList({ groups, settings }: { groups: readonly TelemetryGroup[]; settings: TelemetrySettings }) {
  const update = useUpdateTelemetrySettings();
  const requires: Requires = new Map(settings.groups.map((info) => [info.group, info.requires ?? null]));
  const enabled = new Set(settings.groups.filter((info) => info.enabled).map((info) => info.group));
  const [error, setError] = useState<string | null>(null);
  const onToggle = (group: TelemetryGroup, on: boolean) => {
    setError(null);
    update.mutate([...toggleGroup(group, on, enabled, requires)], { onError: (e) => setError(e.message) });
  };
  return (
    <ul className="divide-y rounded-md border">
      {groups.map((group) => {
        const copy = GROUP_COPY[group];
        const parent = requires.get(group) ?? null;
        const available = canEnable(group, enabled, requires);
        const locked = !settings.editable || update.isPending;
        const blocked = !available && !enabled.has(group);
        return (
          <li key={group} className="flex items-start gap-4 p-4">
            <Switch
              aria-label={copy.title}
              checked={enabled.has(group)}
              disabled={locked || blocked}
              onCheckedChange={(on) => onToggle(group, on)}
            />
            <div className="space-y-1">
              <div className="font-medium">{copy.title}</div>
              <p className="text-muted-foreground">{copy.sends}</p>
              <p className="text-muted-foreground">Why: {copy.helps}</p>
              {parent !== null && !available && <p className="text-xs">Needs {GROUP_COPY[parent].title} on.</p>}
            </div>
          </li>
        );
      })}
      {error !== null && <li className="p-4 text-destructive">{error}</li>}
    </ul>
  );
}

function ReportPreview({ settings }: { settings: TelemetrySettings }) {
  return (
    <section className="space-y-2">
      <h3 className="font-medium">
        {settings.report_is_sample ? "Sample report" : "Last report sent from this worker"}
      </h3>
      <p className="text-muted-foreground">
        {settings.report_is_sample
          ? "Made-up traffic run through the real filter, showing what one report would contain with the groups currently on (or with every group, while telemetry is off)."
          : "The exact report this worker sent or stored most recently."}
      </p>
      <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs">
        {JSON.stringify(settings.report, null, 2)}
      </pre>
    </section>
  );
}

export default function TelemetrySettingsPage() {
  const [tab, setTab] = useUrlTab(TABS, "proxy");
  const { data: settings, isLoading, error } = useTelemetrySettings();
  if (isLoading) return <div className="p-6">Loading telemetry settings...</div>;
  if (settings === undefined)
    return <div className="p-6 text-destructive">Could not load telemetry settings: {error?.message}</div>;
  return (
    <div className="max-w-4xl space-y-6 p-6 text-sm">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold">Telemetry</h1>
        <p className="text-muted-foreground">
          Everything is off by default. Each switch adds one group of aggregated counts to the report, and a group needs
          the one above it. Telemetry lets us see a provider failure spike, a cache-hit drop, a latency regression or a
          broken page before a user has to report it. Prompts, responses, keys, user and team ids, and header values are
          never collected. Setting LITELLM_TELEMETRY_DISABLED=true turns all of it off regardless of this page.
        </p>
      </header>
      <Tabs value={tab} onValueChange={(value) => setTab(value as (typeof TABS)[number])}>
        <TabsList variant="line">
          <TabsTrigger value="proxy">Proxy requests</TabsTrigger>
          <TabsTrigger value="ui">Admin UI</TabsTrigger>
        </TabsList>
        <TabsContent value="proxy" className="space-y-4 pt-4">
          <GroupList groups={PROXY_GROUPS} settings={settings} />
        </TabsContent>
        <TabsContent value="ui" className="space-y-4 pt-4">
          <GroupList groups={UI_GROUPS} settings={settings} />
          <p className="text-muted-foreground">
            The browser only sends events while Page navigation is on. They go to this proxy at POST
            /telemetry/ui_events, never to a third party, and are counted into the same report as proxy traffic.
          </p>
        </TabsContent>
      </Tabs>
      <section className="space-y-2">
        <h3 className="font-medium">How and when it is sent</h3>
        <p className="text-muted-foreground">{destinationText(settings)}</p>
        <p className="text-muted-foreground">Changes here reach every worker at its next report window.</p>
      </section>
      <ReportPreview settings={settings} />
    </div>
  );
}
