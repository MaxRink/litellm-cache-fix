from __future__ import annotations
import hashlib
from pathlib import Path

CACHE_BASE = "a8d6b09d6cded7d1b06e8e2d01ee9859a62eba6f2c9894e5d58bbe376210637e"
OTEL_BASE = "c7631f38a2b33ae7983660a4ec3db56cc01039678f53a24bc0870ed1aa6a6641"
OTEL_PATCHED = "28529f5fa51c434c779a583d0dda21b4f5a576773951f058e86d19971f8ed68b"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def patch_cache(path: Path) -> None:
    if sha(path) != CACHE_BASE:
        raise SystemExit(f"unexpected v1.106.4 cache source: {sha(path)}")
    text = path.read_text()
    old_loop = "        for param in kwargs:\n            if param in scope_excluded_params:\n"
    new_loop = "        for param in kwargs:\n            if param == \"parent_otel_span\":\n                continue\n            if param in scope_excluded_params:\n"
    if text.count(old_loop) != 1:
        raise SystemExit("cache ephemeral-parameter anchor missing or ambiguous")
    text = text.replace(old_loop, new_loop, 1)
    old_ns = (
        '        dynamic_cache_control: Final[DynamicCacheControl] = kwargs.get("cache", {})\n'
        '        metadata: Final = kwargs.get("metadata") or {}\n'
        '        namespace: Final = dynamic_cache_control.get("namespace") or metadata.get("redis_namespace") or self.namespace\n'
    )
    new_ns = (
        '        dynamic_cache_control: Final[DynamicCacheControl] = kwargs.get("cache", {})\n'
        '        metadata_sources: Final = tuple(\n'
        '            source for source in (kwargs.get("metadata"), kwargs.get("litellm_metadata"))\n'
        '            if isinstance(source, Mapping)\n'
        '        )\n'
        '        authenticated_namespace: str | None = None\n'
        '        authenticated_request = False\n'
        '        try:\n'
        '            from litellm.proxy._types import UserAPIKeyAuth\n'
        '        except ImportError:\n'
        '            UserAPIKeyAuth = None  # type: ignore[assignment,misc]\n'
        '        for metadata in metadata_sources:\n'
        '            auth_object = metadata.get("user_api_key_auth")\n'
        '            if UserAPIKeyAuth is not None and isinstance(auth_object, UserAPIKeyAuth):\n'
        '                authenticated_request = True\n'
        '                identity_fields = {\n'
        '                    "api_key": getattr(auth_object, "api_key", None),\n'
        '                    "team_id": getattr(auth_object, "team_id", None),\n'
        '                    "project_id": getattr(auth_object, "project_id", None),\n'
        '                    "org_id": getattr(auth_object, "org_id", None),\n'
        '                    "user_id": getattr(auth_object, "user_id", None),\n'
        '                    "end_user_id": getattr(auth_object, "end_user_id", None),\n'
        '                    "user_role": getattr(auth_object, "user_role", None),\n'
        '                }\n'
        '                identity = json.dumps(identity_fields, sort_keys=True, default=str, separators=(",", ":"))\n'
        '                authenticated_namespace = "caller:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]\n'
        '                break\n'
        '        if authenticated_request:\n'
        '            namespace: Final = ":".join(value for value in (self.namespace, authenticated_namespace) if isinstance(value, str) and value)\n'
        '        else:\n'
        '            namespace = (\n'
        '                dynamic_cache_control.get("namespace")\n'
        '                or next((m.get("redis_namespace") for m in metadata_sources if m.get("redis_namespace")), None)\n'
        '                or self.namespace\n'
        '            )\n'
    )
    if text.count(old_ns) != 1:
        raise SystemExit("cache namespace anchor missing or ambiguous")
    path.write_text(text.replace(old_ns, new_ns, 1))
    print(f"cache_forwardport_sha={sha(path)}")

def patch_otel(path: Path) -> None:
    current_sha = sha(path)
    # The fork source may already contain the guarded ended-span fix.  Accept
    # that exact reviewed source rather than trying to apply the patch twice.
    if current_sha == OTEL_PATCHED:
        print(f"otel_forwardport_sha={current_sha}")
        return
    if current_sha != OTEL_BASE:
        raise SystemExit(f"unexpected v1.106.4 OTEL source: {current_sha}")
    text = path.read_text()
    old = "            span.set_attributes(routing_decision_attributes(decision))\n"
    new = "            for key, value in routing_decision_attributes(decision).items():\n                self.safe_set_attribute(span=span, key=key, value=value)\n"
    if text.count(old) != 1:
        raise SystemExit("OTEL routing attribute anchor missing or ambiguous")
    path.write_text(text.replace(old, new, 1))
    print(f"otel_forwardport_sha={sha(path)}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--otel", type=Path, required=True)
    a = p.parse_args()
    patch_cache(a.cache)
    patch_otel(a.otel)
