"""Early installation of explicitly configured proxy response metrics."""

import importlib
import os
from typing import Any


_REVIEWED_INSTALLERS = frozenset(
    {
        "quota_guard:install_http_response_metrics",
        "routing_audit:install_http_response_metrics",
    }
)


def install_configured_http_response_metrics(fastapi_app: Any, logger: Any) -> None:
    """Attach the reviewed response middleware to LiteLLM's final app."""
    hook_spec = os.environ.get("LITELLM_HTTP_RESPONSE_METRICS_INSTALLER", "").strip()
    if not hook_spec:
        return
    if hook_spec not in _REVIEWED_INSTALLERS:
        raise ValueError(
            "LITELLM_HTTP_RESPONSE_METRICS_INSTALLER must name the reviewed "
            "quota_guard or routing_audit installer"
        )
    module_name, function_name = hook_spec.split(":", 1)
    installer = getattr(importlib.import_module(module_name), function_name, None)
    if not callable(installer):
        raise TypeError(f"Configured metrics installer is not callable: {hook_spec}")
    if installer(fastapi_app) is not True:
        raise RuntimeError(f"Configured metrics installer did not attach middleware: {hook_spec}")
    logger.info("Installed HTTP response metrics middleware using %s", hook_spec)
