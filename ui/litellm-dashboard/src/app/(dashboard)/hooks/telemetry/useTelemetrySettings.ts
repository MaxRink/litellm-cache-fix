import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createQueryKeys } from "../common/queryKeysFactory";
import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";
import { fetchClient } from "@/lib/http/api";
import { setPageNavigationEnabled } from "@/lib/telemetry/uiEvents";
import type { components } from "@/lib/http/schema";
import { all_admin_roles } from "@/utils/roles";

export type TelemetrySettings = components["schemas"]["TelemetrySettingsResponse"];
export type TelemetryGroup = components["schemas"]["TelemetryGroup"];

export const telemetrySettingsKeys = createQueryKeys("telemetrySettings");

const fetchTelemetrySettings = async (): Promise<TelemetrySettings> => {
  const { data, error } = await fetchClient.GET("/telemetry/settings");
  if (data === undefined) throw new Error(JSON.stringify(error));
  return data;
};

export const useTelemetrySettings = () => {
  const { accessToken, userRole } = useAuthorized();
  const options = {
    queryKey: telemetrySettingsKeys.detail("current"),
    queryFn: fetchTelemetrySettings,
    enabled: Boolean(accessToken) && all_admin_roles.includes(userRole || ""),
    staleTime: 60_000,
  };
  return useQuery<TelemetrySettings>(options);
};

export const useUpdateTelemetrySettings = () => {
  const queryClient = useQueryClient();
  return useMutation<TelemetrySettings, Error, readonly TelemetryGroup[]>({
    mutationFn: async (groups) => {
      const { data, error } = await fetchClient.PUT("/telemetry/settings", { body: { groups: [...groups] } });
      if (data === undefined) throw new Error(JSON.stringify(error));
      return data;
    },
    onSuccess: (settings) => {
      queryClient.setQueryData(telemetrySettingsKeys.detail("current"), settings);
      setPageNavigationEnabled(settings.groups.some(({ group, enabled }) => group === "page_navigation" && enabled));
    },
  });
};
