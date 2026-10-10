"""Metadata-only LiteLLM deployment-attempt audit callback."""

import json
import re

from litellm.integrations.custom_logger import CustomLogger


UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CALLERS = {"paperless-gpt", "karakeep", "ha1", "ha2", "linkwarden", "nextcloud", "trek", "paperless-native"}
CALLER_ALIASES = {"trek-20261009": "trek"}
REQUESTED = {"paperless-routine", "trek-vision-free", "ha-gemini-free", "public-free", "public-auto", "public-adaptive", "ha-local", "quality", "claude-very-complex", "opencode-free", "nvidia-free", "gemini-free-25-pro", "gemini-free-25-flash", "gemini-free-25-flash-lite", "gemini-free-38", "gemini-free-37", "gemini-free-36", "gemini-free-35", "gemini-free-31-lite", "opencode-space-bunny-free", "opencode-big-pickle-free", "opencode-longcat-free", "opencode-step-free", "opencode-exo-free", "opencode-mimo-v25-free", "opencode-ling31-free", "opencode-ling30-free", "opencode-nemotron-ultra-free", "opencode-nemotron-lightning-free", "opencode-muse-spark-free"}
DEPLOYMENTS = {"auto_router/complexity_router", "auto_router/adaptive_router", "gemini/gemini-2.5-pro", "gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash-lite", "gemini/gemini-3.8-flash", "gemini/gemini-3.5-flash", "gemini/gemini-3.5-flash-lite", "gemini/gemini-3.7-flash", "gemini/gemini-3.6-flash", "gemini/gemini-3.1-flash-lite", "ollama_chat/qwen3:4b", "anthropic/claude-haiku-5-5", "anthropic/claude-opus-5-5", "anthropic/claude-sonnet-4-6", "openai/mimo-v2.6-flash-free", "openai/space-bunny-free", "openai/big-pickle", "openai/longcat-2.5-preview-free", "openai/step-5-preview-free", "openai/exo-free", "openai/mimo-v2.5-free", "openai/ling-3.1-flash-free", "openai/ling-3.0-flash-fin-free", "openai/nemotron-3-ultra-free", "openai/nemotron-3.5-lightning-free", "openai/muse-spark-1.3-contributor-free", "openai/nvidia/nemotron-3-super-120b-a12b"}
PROVIDERS = {"auto_router", "gemini", "ollama", "anthropic", "openai"}
ERRORS = {"RateLimitError", "TimeoutError", "ServiceUnavailableError", "InternalServerError", "AuthenticationError", "BadRequestError", "ContextWindowExceededError"}


def _enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else "unknown"


def _caller(value):
    return _enum(CALLER_ALIASES.get(value, value) if isinstance(value, str) else value, CALLERS)


def _id(value):
    return value if isinstance(value, str) and UUID.fullmatch(value) else "unknown"


def _record(outcome, request_data, exception=None, fallback_depth=None):
    data = request_data if isinstance(request_data, dict) else {}
    standard = data.get("standard_logging_object") if isinstance(data.get("standard_logging_object"), dict) else {}
    view = {**data, **standard}
    metadata = view.get("metadata") if isinstance(view.get("metadata"), dict) else {}
    view = {**metadata, **view}
    params = view.get("litellm_params") if isinstance(view.get("litellm_params"), dict) else {}
    deployment = params.get("model") or view.get("model_id") or view.get("model")
    provider = params.get("custom_llm_provider") or ("auto_router" if deployment in {"auto_router/complexity_router", "auto_router/adaptive_router"} else "ollama" if isinstance(deployment, str) and deployment.startswith("ollama_") else "gemini" if isinstance(deployment, str) and deployment.startswith("gemini/") else "anthropic" if isinstance(deployment, str) and deployment.startswith("anthropic/") else "openai" if isinstance(deployment, str) and deployment.startswith("openai/") else None)
    row = {
        "event": "litellm_route_attempt",
        "request_id": _id(view.get("litellm_call_id") or view.get("request_id")),
        "requested_model": _enum(view.get("routing_requested_model") or view.get("model_group") or view.get("requested_model") or view.get("model"), REQUESTED),
        "deployment_model": _enum(deployment, DEPLOYMENTS),
        "provider": _enum(provider, PROVIDERS),
        "caller": _caller(view.get("user_api_key_alias") or view.get("user")),
        "outcome": outcome,
        "level": "info" if outcome == "success" else "warn",
        "exception_class": type(exception).__name__ if exception is not None and type(exception).__name__ in ERRORS else "unknown" if exception is not None else "none",
        "fallback_depth": fallback_depth if isinstance(fallback_depth, int) and not isinstance(fallback_depth, bool) and fallback_depth >= 0 else None,
    }
    print(json.dumps(row, sort_keys=True, separators=(",", ":")), flush=True)


class RouteAudit(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if isinstance(data, dict):
            # Replaying a streamed tool/function response can repeat an
            # external side effect.  Exact caching remains available for
            # ordinary non-streaming chat and embedding requests.
            role = user_api_key_dict.get("user_role") if isinstance(user_api_key_dict, dict) else getattr(user_api_key_dict, "user_role", None)
            caller_alias = user_api_key_dict.get("key_alias") if isinstance(user_api_key_dict, dict) else getattr(user_api_key_dict, "key_alias", None)
            caller_alias = _caller(caller_alias)
            # App keys are currently provisioned with proxy_admin for their
            # native integration permissions. Trust only the authenticated
            # alias, never request metadata, when distinguishing them from a
            # human admin session.
            human_admin = role == "proxy_admin" and caller_alias not in CALLERS
            if human_admin or caller_alias in {"ha1", "ha2"} or data.get("stream") or any(data.get(name) for name in ("tools", "tool_choice", "functions")):
                cache_control = data.get("cache") if isinstance(data.get("cache"), dict) else {}
                cache_control["no-cache"] = True
                cache_control["no-store"] = True
                data["cache"] = cache_control
        if isinstance(data, dict) and data.get("model") in REQUESTED:
            metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            metadata["routing_requested_model"] = data["model"]
            data["metadata"] = metadata
        return data

    async def async_pre_call_deployment_hook(self, kwargs, call_type):
        return kwargs

    async def async_post_call_success_deployment_hook(self, request_data, response, call_type):
        _record("success", request_data)

    async def async_post_call_failure_deployment_hook(self, request_data, exception, call_type, fallback_depth=None):
        _record("failure", request_data, exception, fallback_depth)


route_audit = RouteAudit()
