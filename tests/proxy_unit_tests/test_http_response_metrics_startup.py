import sys
import types
import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HELPER_PATH = Path(__file__).parents[2] / "litellm" / "proxy" / "http_response_metrics_startup.py"
_SPEC = importlib.util.spec_from_file_location("http_response_metrics_startup", _HELPER_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
install_configured_http_response_metrics = _MODULE.install_configured_http_response_metrics


def test_installs_on_final_fastapi_app(monkeypatch):
    class MarkerMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            async def send_with_marker(message):
                if message["type"] == "http.response.start":
                    message["headers"] = [*message.get("headers", []), (b"x-metrics-hook", b"installed")]
                await send(message)

            await self.app(scope, receive, send_with_marker)

    def installer(app):
        app.add_middleware(MarkerMiddleware)
        return True

    monkeypatch.setitem(sys.modules, "routing_audit", types.SimpleNamespace(install_http_response_metrics=installer))
    monkeypatch.setenv("LITELLM_HTTP_RESPONSE_METRICS_INSTALLER", "routing_audit:install_http_response_metrics")
    app = FastAPI()
    app.get("/health")(lambda: {"ok": True})
    install_configured_http_response_metrics(app, types.SimpleNamespace(info=lambda *args: None))
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-metrics-hook"] == "installed"


def test_rejects_unreviewed_installer(monkeypatch):
    monkeypatch.setenv("LITELLM_HTTP_RESPONSE_METRICS_INSTALLER", "arbitrary:call")
    with pytest.raises(ValueError):
        install_configured_http_response_metrics(FastAPI(), types.SimpleNamespace(info=lambda *args: None))


def test_rejects_missing_or_false_installer(monkeypatch):
    monkeypatch.setenv("LITELLM_HTTP_RESPONSE_METRICS_INSTALLER", "routing_audit:install_http_response_metrics")
    monkeypatch.setitem(sys.modules, "routing_audit", types.SimpleNamespace())
    with pytest.raises(TypeError):
        install_configured_http_response_metrics(FastAPI(), types.SimpleNamespace(info=lambda *args: None))

    def false_installer(app):
        return False

    monkeypatch.setitem(sys.modules, "routing_audit", types.SimpleNamespace(install_http_response_metrics=false_installer))
    with pytest.raises(RuntimeError):
        install_configured_http_response_metrics(FastAPI(), types.SimpleNamespace(info=lambda *args: None))


def test_unset_is_a_noop(monkeypatch):
    monkeypatch.delenv("LITELLM_HTTP_RESPONSE_METRICS_INSTALLER", raising=False)
    install_configured_http_response_metrics(FastAPI(), types.SimpleNamespace(info=lambda *args: None))
