"""Regression tests for ChatGPT subscription authentication boundaries.

The proxy must never start the interactive device-code flow from an async
worker. Existing and refreshable private credentials remain usable.
"""

from __future__ import annotations

import json
import time

import pytest

from litellm.llms.chatgpt import authenticator as authenticator_module
from litellm.llms.chatgpt.authenticator import Authenticator
from litellm.llms.chatgpt.common_utils import GetAccessTokenError


def _write_auth(tmp_path, **values):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def test_missing_auth_never_starts_device_flow_in_proxy_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(authenticator_module, "can_block_current_thread", lambda: False)

    def unexpected_device_flow():
        raise AssertionError("interactive device flow must not run in the proxy")

    monkeypatch.setattr(Authenticator, "_login_device_code", unexpected_device_flow)

    with pytest.raises(GetAccessTokenError, match="cannot run inside the LiteLLM proxy") as exc:
        Authenticator().get_access_token()

    assert exc.value.status_code == 401
    assert not (tmp_path / "auth.json").exists()


def test_private_valid_auth_is_used_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(tmp_path))
    _write_auth(tmp_path, access_token="private-access-token", expires_at=time.time() + 3600)
    monkeypatch.setattr(authenticator_module, "can_block_current_thread", lambda: False)
    monkeypatch.setattr(
        Authenticator,
        "_login_device_code",
        lambda self: (_ for _ in ()).throw(AssertionError("device flow must not run")),
    )

    assert Authenticator().get_access_token() == "private-access-token"


def test_expired_private_auth_refreshes_before_worker_guard(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(tmp_path))
    _write_auth(
        tmp_path,
        access_token="expired-access-token",
        refresh_token="private-refresh-token",
        expires_at=time.time() - 3600,
    )
    monkeypatch.setattr(authenticator_module, "can_block_current_thread", lambda: False)

    calls = []

    def refresh(self, refresh_token):
        calls.append(refresh_token)
        return {"access_token": "refreshed-private-token"}

    monkeypatch.setattr(Authenticator, "_refresh_tokens", refresh)
    monkeypatch.setattr(
        Authenticator,
        "_login_device_code",
        lambda self: (_ for _ in ()).throw(AssertionError("device flow must not run")),
    )

    assert Authenticator().get_access_token() == "refreshed-private-token"
    assert calls == ["private-refresh-token"]
