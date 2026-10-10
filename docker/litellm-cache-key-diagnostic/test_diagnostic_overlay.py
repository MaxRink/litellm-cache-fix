"""Privacy and scope checks for the bounded cache-key diagnostic overlay."""
from __future__ import annotations

import ast
import hashlib
import json
import os
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
        "hashlib": hashlib,
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
