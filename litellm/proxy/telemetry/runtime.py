import asyncio
import contextlib
import hashlib
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from typing import Final, TypeAlias

from pydantic import ValidationError

from litellm._logging import verbose_proxy_logger
from litellm.llms.custom_httpx.http_handler import (
    get_async_httpx_client,  # pyright: ignore[reportUnknownVariableType]  # legacy params: dict signature
)
from litellm.proxy.telemetry.attempt_logger import TelemetryAttemptLogger
from litellm.proxy.telemetry.settings import EnvPolicy, TelemetrySettings, env_policy
from litellm.proxy.telemetry.store import Database, LocalTableExporter, TelemetryStore
from litellm.telemetry.aggregate import AggregatingSink
from litellm.telemetry.consent import OFF, ConsentGatedSink, TelemetryConsent
from litellm.telemetry.http_exporter import HttpExporter
from litellm.telemetry.records import InstanceInfo
from litellm.telemetry.report import Report
from litellm.telemetry.sink import Exporter, ExportOutcome
from litellm.types.llms.custom_http import httpxSpecialProvider

StoredConsent: TypeAlias = Callable[[], Awaitable[TelemetryConsent | None]]


def deployment_hasher(salt: str) -> Callable[[str], str]:
    return lambda model_id: hashlib.sha256(f"{salt}:{model_id}".encode()).hexdigest()[:16]


class _RememberingExporter:
    def __init__(self, inner: Exporter) -> None:
        self._inner: Final = inner
        self.last_report: Report | None = None

    async def export(self, report: Report) -> ExportOutcome:
        outcome: Final = await self._inner.export(report)
        self.last_report = report if outcome is ExportOutcome.SENT else self.last_report
        return outcome


def _exporter(endpoint: str | None, store: TelemetryStore | None) -> Exporter:
    if endpoint is not None:
        return HttpExporter(
            get_async_httpx_client(httpxSpecialProvider.LoggingCallback, params={"timeout": 10.0}).client, endpoint
        )
    assert store is not None, "start() returns early when there is neither an endpoint nor a database"
    return LocalTableExporter(store)


class TelemetryRuntime:
    """Owns the proxy's telemetry sink, re-reads which groups are on before every window, and flushes each window"""

    def __init__(self) -> None:
        self.sink: ConsentGatedSink | None = None
        self.store: TelemetryStore | None = None
        self.policy: EnvPolicy | None = None
        self.settings: TelemetrySettings = TelemetrySettings.model_construct()
        self.litellm_version: str = ""
        self._exporter: _RememberingExporter | None = None
        self._instance: InstanceInfo | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._pending: Final[set[asyncio.Task[None]]] = set()  # mutable-ok: strong refs keep finalizers alive

    @property
    def last_report(self) -> Report | None:
        return self._exporter.last_report if self._exporter is not None else None

    def spawn(self, coroutine: Coroutine[None, None, None]) -> None:
        task: Final = asyncio.create_task(coroutine)
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def start(
        self,
        *,
        litellm_version: str,
        settings: TelemetrySettings,
        db: Callable[[], Database | None],
        register: Callable[[TelemetryAttemptLogger], None],
    ) -> None:
        self.settings, self.litellm_version = settings, litellm_version
        policy: Final = env_policy(settings)
        if not isinstance(policy, EnvPolicy):
            verbose_proxy_logger.warning("telemetry: %s in LITELLM_TELEMETRY_GROUPS, leaving it off", policy.message())
            return
        self.policy = policy
        if policy.locked_off:
            return
        database: Final = db()
        store: Final = TelemetryStore(database, settings.retention_days) if database is not None else None
        if settings.endpoint is None and store is None:
            return
        self.store = store
        self._exporter = _RememberingExporter(_exporter(settings.endpoint, store))
        register(TelemetryAttemptLogger(lambda: self.sink, self._hash_deployment))
        await self.refresh()
        self._flush_task = asyncio.create_task(self._flush_every(settings.flush_interval_seconds))

    def _hash_deployment(self, model_id: str) -> str:
        instance: Final = self._instance
        return deployment_hasher(instance.instance_id if instance is not None else "")(model_id)

    async def _stored_consent(self) -> TelemetryConsent | None:
        store: Final = self.store
        stored: Final = await store.consent() if store is not None else None
        if stored is None or isinstance(stored, TelemetryConsent):
            return stored
        verbose_proxy_logger.warning("telemetry: ignoring stored settings, %s", stored.message())
        return None

    async def _instance_info(self) -> InstanceInfo:
        known: Final = self._instance
        if known is not None:
            return known
        store: Final = self.store
        instance: Final = InstanceInfo(
            instance_id=await store.instance_id() if store is not None else uuid.uuid4().hex,
            litellm_version=self.litellm_version,
        )
        self._instance = instance
        return instance

    async def refresh(self) -> None:
        """Apply the current groups; only called between windows so every report has a single set of groups"""
        policy: Final = self.policy
        exporter: Final = self._exporter
        if policy is None or exporter is None:
            return
        from prisma.errors import PrismaError

        try:
            consent: Final = policy.effective(await self._stored_consent() if policy.pinned is None else None)
            current: Final = self.sink
            if current is not None and current.consent == consent:
                return
            if consent == OFF:
                self.sink = None
                return
            gated: Final = ConsentGatedSink(AggregatingSink(exporter), consent)
            gated.set_instance(await self._instance_info())
            self.sink = gated
        except (PrismaError, OSError, ValidationError) as e:
            verbose_proxy_logger.debug("telemetry: keeping the current groups, could not read stored settings: %s", e)

    async def _flush_every(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            await self._flush_current()
            await self.refresh()

    async def _flush_current(self) -> None:
        sink: Final = self.sink
        if sink is not None:
            await sink.flush()

    async def stop(self) -> None:
        flush_task: Final = self._flush_task
        if flush_task is not None:
            flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await flush_task
        await asyncio.gather(*self._pending, return_exceptions=True)
        await self._flush_current()
        self.sink = None
        self.store = None
