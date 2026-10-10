"""Privacy and scope checks for the bounded cache-key diagnostic overlay."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).with_name("caching.py")


def _load_helpers():
    tree = ast.parse(SOURCE.read_text())
    wanted = {"_redact_cache_diagnostic_value", "_emit_cache_key_diagnostic"}
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Cache"]
    assert len(nodes) == 1
    methods = [n for n in nodes[0].body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in methods} == wanted
    cache = SimpleNamespace()
    namespace = {
        "Mapping": Mapping,
        "hashlib": SimpleNamespace(sha256=hashlib.sha256),
        "json": json,
        "os": os,
        "time": SimpleNamespace(monotonic=lambda: 10.0),
        "verbose_logger": SimpleNamespace(info=lambda *args: None),
        "Cache": cache,
        "_cache_key_diagnostic_calls": {},
    }
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), "exec"), namespace)
    cache._redact_cache_diagnostic_value = staticmethod(namespace["_redact_cache_diagnostic_value"])
    cache._emit_cache_key_diagnostic = staticmethod(namespace["_emit_cache_key_diagnostic"])
    return cache, namespace


def test_disabled_and_wrong_scope_are_silent(monkeypatch):
    cache, namespace = _load_helpers()
    records = []
    namespace["verbose_logger"].info = lambda *args: records.append(args)
    kwargs = {"litellm_call_id": "call-1", "metadata": {"model_group": "other"}, "messages": []}
    monkeypatch.delenv("LITELLM_CACHE_KEY_DIAGNOSTIC", raising=False)
    cache._emit_cache_key_diagnostic(cache_key="k", kwargs=kwargs)
    monkeypatch.setenv("LITELLM_CACHE_KEY_DIAGNOSTIC", "1")
    cache._emit_cache_key_diagnostic(cache_key="k", kwargs=kwargs)
    assert records == []


def test_same_call_followup_is_bounded_and_other_call_is_silent(monkeypatch):
    cache, namespace = _load_helpers()
    records = []
    namespace["verbose_logger"].info = lambda *args: records.append(args)
    messages = [{"role": "user", "content": "diagnostic fixture"}]
    encoded_messages = json.dumps(messages, sort_keys=True, separators=(",", ":"), default=str).encode()
    real_sha256 = hashlib.sha256

    class Digest:
        def __init__(self, value):
            self.value = value

        def hexdigest(self):
            return self.value

    def sha256(value=b""):
        if value == encoded_messages:
            return Digest("10ee9c833aa5c34b" + "0" * 48)
        return real_sha256(value)

    namespace["hashlib"].sha256 = sha256
    monkeypatch.setenv("LITELLM_CACHE_KEY_DIAGNOSTIC", "1")
    first = {
        "litellm_call_id": "call-accepted",
        "metadata": {"model_group": "ha-local", "user_api_key_alias": "paperless-gpt"},
        "messages": messages,
        "model": "ha-local",
    }
    cache._emit_cache_key_diagnostic(cache_key="first", kwargs=first)
    followup = dict(first)
    followup["model"] = "ha-local-mutated-by-provider"
    cache._emit_cache_key_diagnostic(cache_key="second", kwargs=followup)
    other = dict(followup)
    other["litellm_call_id"] = "call-other"
    other["metadata"] = {"model_group": "ha-local", "user_api_key_alias": "unapproved"}
    cache._emit_cache_key_diagnostic(cache_key="third", kwargs=other)
    for i in range(3):
        cache._emit_cache_key_diagnostic(cache_key=f"followup-{i}", kwargs=followup)
    assert len(records) == 3
    assert all("call_hash" in json.loads(args[1]) for args in records)
    assert all("call-accepted" not in json.dumps(args) for args in records)
    assert all("diagnostic fixture" not in json.dumps(args) for args in records)


def test_exhausted_call_can_reenroll_after_ttl(monkeypatch):
    cache, namespace = _load_helpers()
    records = []
    namespace["verbose_logger"].info = lambda *args: records.append(args)
    messages = [{"role": "user", "content": "ttl fixture"}]
    encoded_messages = json.dumps(messages, sort_keys=True, separators=(",", ":"), default=str).encode()
    real_sha256 = hashlib.sha256

    class Digest:
        def __init__(self, value):
            self.value = value

        def hexdigest(self):
            return self.value

    def sha256(value=b""):
        if value == encoded_messages:
            return Digest("10ee9c833aa5c34b" + "0" * 48)
        return real_sha256(value)

    namespace["hashlib"].sha256 = sha256
    monkeypatch.setenv("LITELLM_CACHE_KEY_DIAGNOSTIC", "1")
    kwargs = {
        "litellm_call_id": "call-ttl",
        "metadata": {"model_group": "ha-local", "user_api_key_alias": "paperless-gpt"},
        "messages": messages,
    }
    for i in range(3):
        cache._emit_cache_key_diagnostic(cache_key=f"before-{i}", kwargs=kwargs)
    assert len(records) == 3
    namespace["time"].monotonic = lambda: 71.0
    cache._emit_cache_key_diagnostic(cache_key="after-ttl", kwargs=kwargs)
    assert len(records) == 4


def test_wrong_base_hash_is_rejected():
    base = SOURCE.with_name("base-d544-1227bd.caching.py")
    expected = "1227bd9292d28462e9db12946238dcc2f5caf20cd40ba9ebd504d27fa25c96e0"
    assert hashlib.sha256(base.read_bytes()).hexdigest() == expected
    wrong = base.read_bytes() + b"\n"
    assert hashlib.sha256(wrong).hexdigest() != expected

    verifier = SOURCE.with_name("verify_base.py")
    spec = __import__("importlib.util").util.spec_from_file_location("verify_base", verifier)
    module = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.verify(base, expected) is None
    try:
        module.verify(base, "0" * 64)
    except RuntimeError:
        pass
    else:
        raise AssertionError("wrong base hash was accepted")

    dockerfile = SOURCE.with_name("Dockerfile").read_text()
    assert "verify_base.py" in dockerfile
    assert "RUN python /tmp/verify_base.py /app/.venv/lib/python3.13/site-packages/litellm/caching/caching.py" in dockerfile
    assert "COPY base-d544-1227bd.caching.py" not in dockerfile
    assert expected in verifier.read_text()


def test_redaction_drops_sensitive_fields_and_keeps_no_raw_values():
    cache, _ = _load_helpers()
    value = {"api_key": "secret-value", "headers": {"authorization": "bearer"}, "safe": "ok"}
    encoded = json.dumps(cache._redact_cache_diagnostic_value(value), sort_keys=True)
    assert "secret-value" not in encoded and "bearer" not in encoded
    assert "safe" in encoded


def test_source_keeps_cache_return_and_gated_hook():
    text = SOURCE.read_text()
    assert 'if os.getenv("LITELLM_CACHE_KEY_DIAGNOSTIC") != "1":' in text
    assert "self._emit_cache_key_diagnostic(cache_key=hashed_cache_key, kwargs=kwargs)" in text
    assert "return hashed_cache_key" in text


def test_get_cache_key_body_matches_base_except_diagnostic_call():
    base_path = SOURCE.with_name("base-d544-1227bd.caching.py")
    base_tree = ast.parse(base_path.read_text())
    overlay_tree = ast.parse(SOURCE.read_text())

    def method(tree, name):
        cache = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Cache")
        return next(n for n in cache.body if isinstance(n, ast.FunctionDef) and n.name == name)

    base_method = method(base_tree, "get_cache_key")
    overlay_method = method(overlay_tree, "get_cache_key")
    overlay_method.body = [
        stmt for stmt in overlay_method.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "_emit_cache_key_diagnostic"
        )
    ]
    assert ast.dump(overlay_method, include_attributes=False) == ast.dump(base_method, include_attributes=False)
