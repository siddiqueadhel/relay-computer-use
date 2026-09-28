"""Workbench configuration regressions: no real model credentials, SDK, or browser."""

import builtins
import os
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

from relay.operator import create_console


@pytest.mark.parametrize(
    "provider,direct_key,gateway_key,mode,status,message",
    [
        ("experiential", None, "valid", "discover", 200, None),
        ("openai", "direct-test-key", None, "discover", 200, None),
        (None, "direct-test-key", None, "discover", 200, None),
        ("experiential", "unrelated-direct-key", None, "discover", 422, "EXPLABS_API_KEY"),
        ("openai", None, "valid", "discover", 422, "OPENAI_API_KEY"),
        ("experiential", None, "", "discover", 422, "EXPLABS_API_KEY"),
        ("openai", "   ", None, "discover", 422, "OPENAI_API_KEY"),
        ("experiential", None, "malformed-private-value", "discover", 422, "inference key"),
        ("private-provider-value", "direct-test-key", "valid", "discover", 422, "Unknown"),
        ("bridge", None, None, "discover", 422, "CLI discovery"),
        ("experiential", None, None, "replay", 200, None),
        ("openai", None, None, "replay", 200, None),
        ("private-provider-value", None, None, "replay", 200, None),
    ],
)
async def test_run_endpoint_checks_selected_provider_without_loading_sdk(
    monkeypatch, provider, direct_key, gateway_key, mode, status, message
):
    values = {
        "RELAY_PROVIDER": provider,
        "OPENAI_API_KEY": direct_key,
        "EXPLABS_API_KEY": "xpl_" + "0" * 40 if gateway_key == "valid" else gateway_key,
    }
    for name, value in values.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    imports = builtins.__import__

    def forbid_sdk(name, *args, **kwargs):
        if name == "openai" or name.startswith("openai."):
            raise AssertionError("Configuration preflight must not load an SDK")
        return imports(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_sdk)
    started = []

    def start(inputs, **kwargs):
        started.append({"inputs": inputs, **kwargs})

    manager = SimpleNamespace(
        start=start, current=SimpleNamespace(journal=SimpleNamespace(run_id="test-run"))
    )
    app = create_console(manager)
    inputs = {"member_id": "12345", "account_type": "savings", "nickname": "Fixture"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        request = {"mode": mode, "scenario": "normal", "inputs": inputs}
        # Configuration cannot be probed by a request without the local control token.
        assert (await client.post("/api/run", json=request)).status_code == 403
        response = await client.post(
            "/api/run", json=request, headers={"x-relay-token": app.state.control_token}
        )
    assert response.status_code == status
    if status == 200:
        assert response.json() == {"run_id": "test-run"}
        assert started == [{"inputs": inputs, "mode": mode, "scenario": "normal"}]
    else:
        assert not started
        assert message in response.json()["detail"]
        assert "Replay is available" in response.json()["detail"]
    for value in values.values():
        if value and len(value.strip()) > 15:
            assert value not in response.text


def test_key_free_console_replay_does_not_import_model_modules():
    code = """
import asyncio, sys
from types import SimpleNamespace
import httpx
from relay.operator import create_console
from relay.verification import install_replay_guard

async def check():
    calls = []
    manager = SimpleNamespace(
        start=lambda inputs, **kw: calls.append(kw),
        current=SimpleNamespace(journal=SimpleNamespace(run_id='replay-test')),
    )
    guard = install_replay_guard()
    app = create_console(manager)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
        response = await client.post('/api/run', json={'mode':'replay'}, headers={'x-relay-token':app.state.control_token})
    assert response.status_code == 200
    assert len(calls) == 1
    assert guard['blocked_model_imports'] == guard['blocked_nonlocal_connections'] == 0
    assert not {'openai', 'relay.models', 'relay.discovery'}.intersection(sys.modules)

asyncio.run(check())
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"OPENAI_API_KEY", "EXPLABS_API_KEY"}
    }
    result = subprocess.run(
        [sys.executable, "-c", code], env=environment, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
