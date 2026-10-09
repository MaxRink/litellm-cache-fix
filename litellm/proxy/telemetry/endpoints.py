from collections.abc import Mapping
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from litellm._logging import verbose_proxy_logger
from litellm.proxy._types import CommonProxyErrors, LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.telemetry.runtime import TelemetryRuntime
from litellm.proxy.telemetry.store import StoredReport, TelemetryStore
from litellm.telemetry.consent import OFF, REQUIRES, TelemetryConsent, parse_consent
from litellm.telemetry.records import TelemetryGroup, UIAction, UIEvent
from litellm.telemetry.report import report_to_json
from litellm.telemetry.sample import sample_report
from litellm.telemetry.sink import TelemetrySink

router: Final = APIRouter()


class TelemetryReportsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reports: tuple[StoredReport, ...]
    next_after: float | None
    next_after_id: str | None


class UIEventBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    action: UIAction
    target: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_=:-]{0,127}$")


def telemetry_store() -> TelemetryStore | None:
    from litellm.proxy.proxy_server import prisma_client, telemetry_runtime

    known: Final = telemetry_runtime.store
    if known is not None or prisma_client is None:
        return known
    return TelemetryStore(
        getattr(prisma_client.db, "writer", prisma_client.db),  # pyright: ignore[reportArgumentType]  # PrismaWrapper forwards raw queries via __getattr__
        telemetry_runtime.settings.retention_days,
    )


def telemetry_sink() -> TelemetrySink | None:
    from litellm.proxy.proxy_server import telemetry_runtime

    return telemetry_runtime.sink


@router.post("/telemetry/ui_events", tags=["Telemetry"], status_code=204)
async def record_ui_event(
    body: UIEventBody,
    _user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    sink: Annotated[TelemetrySink | None, Depends(telemetry_sink)],
) -> None:
    """One Admin UI navigation event (route segment, action, allowlisted target), folded into the same telemetry
    report as proxy traffic. Dropped unless the page_navigation group is on"""
    if sink is not None:
        sink.record_ui_event(UIEvent(page=body.page, action=body.action, target=body.target))


@router.get("/telemetry/reports", tags=["Telemetry"], response_model=TelemetryReportsResponse)
async def export_telemetry_reports(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    store: Annotated[TelemetryStore | None, Depends(telemetry_store)],
    after: Annotated[float, Query(description="window_end of the last report already exported")] = 0.0,
    after_id: Annotated[str, Query(description="id of the last report already exported")] = "",
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> TelemetryReportsResponse:
    """Stored telemetry reports, oldest first, for installs that keep telemetry local instead of sending it.
    Page with ``after=next_after&after_id=next_after_id`` until ``next_after`` is null"""
    if user_api_key_dict.user_role not in (LitellmUserRoles.PROXY_ADMIN, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY):
        raise HTTPException(status_code=403, detail="Only proxy admin roles can export telemetry reports")
    if store is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    reports: Final = await store.reports_after(after, after_id, limit)
    if len(reports) < limit:
        return TelemetryReportsResponse(reports=reports, next_after=None, next_after_id=None)
    return TelemetryReportsResponse(reports=reports, next_after=reports[-1].window_end, next_after_id=reports[-1].id)


_EVERYTHING: Final = TelemetryConsent(frozenset(TelemetryGroup))
_REPORT_JSON: Final = TypeAdapter(Mapping[str, JsonValue])


class TelemetryGroupInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    group: TelemetryGroup
    requires: TelemetryGroup | None
    enabled: bool


class TelemetrySettingsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    groups: tuple[TelemetryGroupInfo, ...]
    stored_groups: tuple[TelemetryGroup, ...] | None
    vetoed: bool
    set_by_environment: bool
    environment_variables: tuple[str, ...]
    editable: bool
    destination: Literal["https", "local_table", "none"]
    flush_interval_seconds: float
    retention_days: int
    report: Mapping[str, JsonValue] | None
    report_is_sample: bool


class TelemetrySettingsUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    groups: tuple[str, ...]


def telemetry_runtime_dependency() -> TelemetryRuntime:
    from litellm.proxy.proxy_server import telemetry_runtime

    return telemetry_runtime


def _destination(runtime: TelemetryRuntime) -> Literal["https", "local_table", "none"]:
    if runtime.settings.endpoint is not None:
        return "https"
    return "local_table" if runtime.store is not None else "none"


async def _settings_response(runtime: TelemetryRuntime, stored: TelemetryConsent | None) -> TelemetrySettingsResponse:
    policy: Final = runtime.policy
    effective: Final = policy.effective(stored) if policy is not None else OFF
    last: Final = runtime.last_report
    preview: Final = (
        last
        if last is not None
        else await sample_report(
            effective if effective != OFF else _EVERYTHING, litellm_version=runtime.litellm_version
        )
    )
    return TelemetrySettingsResponse(
        groups=tuple(
            TelemetryGroupInfo(group=group, requires=REQUIRES[group], enabled=group in effective.groups)
            for group in TelemetryGroup
        ),
        stored_groups=tuple(sorted(stored.groups, key=tuple(TelemetryGroup).index)) if stored is not None else None,
        vetoed=policy is None or policy.vetoed,
        set_by_environment=policy is None or policy.vetoed or policy.pinned is not None,
        environment_variables=policy.set_variables if policy is not None else (),
        editable=policy is not None and not policy.vetoed and policy.pinned is None and runtime.store is not None,
        destination=_destination(runtime),
        flush_interval_seconds=runtime.settings.flush_interval_seconds,
        retention_days=runtime.settings.retention_days,
        report=_REPORT_JSON.validate_python(report_to_json(preview)) if preview is not None else None,
        report_is_sample=last is None,
    )


async def _stored(runtime: TelemetryRuntime) -> TelemetryConsent | None:
    store: Final = runtime.store
    stored: Final = await store.consent() if store is not None else None
    return stored if isinstance(stored, TelemetryConsent) else None


@router.get("/telemetry/settings", tags=["Telemetry"], response_model=TelemetrySettingsResponse)
async def get_telemetry_settings(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    runtime: Annotated[TelemetryRuntime, Depends(telemetry_runtime_dependency)],
) -> TelemetrySettingsResponse:
    """Which telemetry groups are on, whether env vars control them, where reports go and a last or sample report"""
    if user_api_key_dict.user_role not in (LitellmUserRoles.PROXY_ADMIN, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY):
        raise HTTPException(status_code=403, detail="Only proxy admin roles can view telemetry settings")
    return await _settings_response(runtime, await _stored(runtime))


@router.put("/telemetry/settings", tags=["Telemetry"], response_model=TelemetrySettingsResponse)
async def update_telemetry_settings(
    update: TelemetrySettingsUpdate,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    runtime: Annotated[TelemetryRuntime, Depends(telemetry_runtime_dependency)],
) -> TelemetrySettingsResponse:
    """Store the telemetry groups for every worker, applied from the next report window"""
    if user_api_key_dict.user_role != LitellmUserRoles.PROXY_ADMIN:
        raise HTTPException(status_code=403, detail="Only the proxy admin can change telemetry settings")
    policy: Final = runtime.policy
    if policy is None or policy.vetoed or policy.pinned is not None:
        raise HTTPException(status_code=409, detail="Telemetry is set by LITELLM_TELEMETRY_* environment variables")
    store: Final = runtime.store
    if store is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    consent: Final = parse_consent(update.groups)
    if not isinstance(consent, TelemetryConsent):
        raise HTTPException(status_code=400, detail=consent.message())
    await store.save_consent(consent)
    verbose_proxy_logger.info(
        "telemetry: %s set groups to %s", user_api_key_dict.user_id, sorted(g.value for g in consent.groups)
    )
    return await _settings_response(runtime, consent)


class UIEventsEnabledResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool


def telemetry_consent() -> TelemetryConsent:
    from litellm.proxy.proxy_server import telemetry_runtime

    sink: Final = telemetry_runtime.sink
    return sink.consent if sink is not None else OFF


@router.get("/telemetry/ui_events/enabled", tags=["Telemetry"], response_model=UIEventsEnabledResponse)
async def ui_events_enabled(
    _user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    consent: Annotated[TelemetryConsent, Depends(telemetry_consent)],
) -> UIEventsEnabledResponse:
    """Whether the Admin UI should send page navigation events in the current report window"""
    return UIEventsEnabledResponse(enabled=consent.allows(TelemetryGroup.PAGE_NAVIGATION))
