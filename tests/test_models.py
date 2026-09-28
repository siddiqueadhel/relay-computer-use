"""Provider diagnostics with a fake SDK: no credentials, network, or paid requests."""

import sys
from types import SimpleNamespace

import pytest

from relay.models import Decision, ExperientialModel, ModelError, OpenAIModel, create_model
from relay.profile import contract


@pytest.mark.parametrize(
    "status,provider_code,expected",
    [
        (429, "insufficient_quota", "model_quota_exhausted"),
        (429, "credit_balance_exhausted", "model_quota_exhausted"),
        (429, "project_spend_limit_exceeded", "model_quota_exhausted"),
        (429, "rate_limit_exceeded", "model_rate_limited"),
        (429, "slow_down", "model_rate_limited"),
        (429, None, "model_api_limited"),
        (429, "free_limit_reached", "model_quota_exhausted"),
        (429, "card_required", "model_account_action_required"),
        (429, "model_requires_payment", "model_account_action_required"),
        (401, "invalid_key", "model_authentication_failed"),
        (400, "unsupported_capability", "model_request_rejected"),
        (401, "invalid_api_key", "model_authentication_failed"),
        (403, None, "model_permission_denied"),
        (400, "private error body", "model_request_rejected"),
        (503, None, "model_unavailable"),
        (None, None, "model_unavailable"),
    ],
)
async def test_provider_diagnostics_are_allowlisted(monkeypatch, status, provider_code, expected):
    class FakeAPIError(Exception):
        status_code = status
        code = provider_code

    calls = []

    async def parse(**request):
        calls.append(request)
        raise FakeAPIError("private error body: credential, request and personal data")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(APIError=FakeAPIError))
    model = OpenAIModel.__new__(OpenAIModel)
    model.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    model.name, model.calls, model.receipts = "test-model", 0, []
    with pytest.raises(ModelError) as captured:
        await model.decide(
            goal="Prepare a request", contract=contract(), observation={}, history=[]
        )
    assert captured.value.code == expected
    assert captured.value.details["http_status"] == status
    assert "private error body" not in str(captured.value.details)
    assert len(calls) == model.calls == 1
    assert model.receipts == []
    assert calls[0]["store"] is False


def test_gateway_uses_its_own_key_endpoint_and_default(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules, "openai", SimpleNamespace(AsyncOpenAI=lambda **kw: calls.append(kw))
    )
    key = "xpl_" + "0" * 40
    monkeypatch.setenv("EXPLABS_API_KEY", key)
    monkeypatch.setenv("OPENAI_API_KEY", "direct-key-never-forward")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid/v1")
    monkeypatch.setenv("RELAY_MODEL", "gpt-4.1-mini")
    monkeypatch.delenv("EXPLABS_MODEL", raising=False)
    model = create_model("experiential")
    assert model.name == "gpt-5.6-luna"
    assert model.provider == "experiential_responses"
    assert calls[0]["api_key"] == key
    assert calls[0]["base_url"] == "https://api.experientiallabs.ai/v1"
    assert calls[0]["max_retries"] == 0
    assert calls[0]["organization"] == calls[0]["project"] == ""


def test_gateway_does_not_fall_back_to_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "direct-key-never-forward")
    monkeypatch.delenv("EXPLABS_API_KEY", raising=False)
    with pytest.raises(ValueError, match="EXPLABS_API_KEY"):
        ExperientialModel()
    monkeypatch.setenv("EXPLABS_API_KEY", "direct-key-never-forward")
    with pytest.raises(ValueError, match="inference key"):
        ExperientialModel()


@pytest.mark.parametrize("ignored", [False, True])
async def test_gateway_preserves_decision_contract_and_reports_route(ignored):
    calls = []
    decision = Decision(intent="intervene", action=None, rationale="Unknown screen")

    async def parse(**request):
        calls.append(request)
        return SimpleNamespace(
            id="resp_test",
            model="gpt-5.6-luna",
            usage=None,
            output_parsed=decision,
            model_extra={
                "provider": "openai",
                "x-experiential-ignored-parameters": ["reasoning"] if ignored else [],
            },
        )

    model = ExperientialModel.__new__(ExperientialModel)
    model.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    model.name, model.calls, model.receipts = "gpt-5.6-luna", 0, []
    if ignored:
        with pytest.raises(ModelError, match="model_parameter_not_honored"):
            await model.decide(
                goal="Synthetic goal", contract=contract(), observation={}, history=[]
            )
        assert not model.receipts
    else:
        assert (
            await model.decide(
                goal="Synthetic goal", contract=contract(), observation={}, history=[]
            )
            == decision
        )
        assert model.receipts[0]["serving_provider"] == "openai"
        assert model.receipts[0]["adapter"] == "experiential_responses"
    assert calls[0]["reasoning"] == {"effort": "none"}
    assert calls[0]["text_format"] is Decision
    assert calls[0]["store"] is False
    assert calls[0]["max_output_tokens"] == 1200


def test_provider_factory_reads_environment_and_rejects_unknown(monkeypatch):
    monkeypatch.setenv("RELAY_PROVIDER", "bridge")
    assert create_model().provider == "external_llm_bridge"
    with pytest.raises(ValueError, match="Unknown discovery provider"):
        create_model("arbitrary-url")
