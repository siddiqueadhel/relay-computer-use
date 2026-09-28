import pytest

from relay.models import Decision
from relay.schema import Action, Value, target

pytestmark = pytest.mark.browser


class TestModel:
    __test__ = False
    test_only = True
    provider = "test_only_scripted"
    name = "test-fixture-not-an-LLM"
    calls = 0

    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.observations = []

    async def decide(self, **request):
        self.calls += 1
        self.observations.append(request["observation"])
        return next(self.decisions)


async def test_model_cannot_declare_success_without_ui_proof(manager):
    model = TestModel([Decision(intent="finish", action=None, rationale="Pretend complete")])
    result = await manager.start(
        dict(member_id="12345", account_type="savings", nickname="PrivateName"),
        mode="discover",
        model=model,
    )
    assert result.code == "premature_model_completion"
    assert manager.current.artifact is None
    assert model.calls == 1
    assert "PrivateName" not in str(model.observations)


async def test_model_cannot_record_raw_literals_instead_of_parameters(manager):
    model = TestModel(
        [
            Decision(
                intent="act",
                action=Action(
                    kind="fill",
                    target=target("Member number", "textbox"),
                    value=Value(source="literal", value="12345"),
                ),
                rationale="Literal input",
            )
        ]
    )
    result = await manager.start(
        dict(member_id="12345", account_type="savings", nickname="PrivateName"),
        mode="discover",
        model=model,
    )
    assert result.code == "unbound_model_input"
    assert manager.current.artifact is None


@pytest.mark.parametrize("scenario", ["normal", "slow"])
async def test_scripted_discovery_compiles_real_ui_and_replays_new_inputs(manager, scenario):
    # Integration test only: never counts as genuine LLM discovery evidence.
    from relay.example import example_capability

    model = TestModel(
        [
            Decision(intent="act", action=step.action, rationale="Test-only recorded action")
            for step in example_capability().steps[1:]
        ]
    )
    result = await manager.start(
        dict(member_id="12345", account_type="savings", nickname="PrivateName"),
        mode="discover",
        model=model,
        scenario=scenario,
    )
    assert (result.status, result.code) == ("success", "completed")
    artifact = manager.current.artifact
    assert artifact.provenance.kind == "test_fixture"
    assert len(artifact.steps) == 8
    assert artifact.steps[-1].after[0].target.candidates[0].name == "Review request"
    replay = await manager.start(
        dict(member_id="67890", account_type="money_market", nickname="NewName")
    )
    assert (replay.status, replay.code) == ("success", "completed")
    assert replay.model_calls == 0
    assert replay.outputs["nickname"] == "NewName"


@pytest.mark.parametrize("provider", ["experiential", "openai"])
async def test_console_discovery_provider_reaches_real_ui_and_key_free_replay(
    manager, monkeypatch, provider
):
    """Real console/runner/browser; fake SDK responses, explicitly test-only provenance."""
    import sys
    from types import SimpleNamespace

    import httpx

    from relay.example import example_capability
    from relay.models import OpenAIModel
    from relay.operator import create_console

    for name in ("OPENAI_API_KEY", "EXPLABS_API_KEY", "RELAY_MODEL", "EXPLABS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RELAY_PROVIDER", provider)
    key_name = "EXPLABS_API_KEY" if provider == "experiential" else "OPENAI_API_KEY"
    key = "xpl_" + "0" * 40 if provider == "experiential" else "synthetic-direct-key"
    monkeypatch.setenv(key_name, key)
    monkeypatch.setattr(OpenAIModel, "test_only", True, raising=False)
    decisions = iter(
        Decision(intent="act", action=step.action, rationale="Synthetic SDK fixture action")
        for step in example_capability().steps[1:]
    )
    requests, clients, closed = [], [], []

    class FakeClient:
        def __init__(self, **options):
            clients.append(options)
            self.responses = SimpleNamespace(parse=self.parse)

        async def parse(self, **request):
            requests.append(request)
            return SimpleNamespace(
                id=f"resp_fixture_{len(requests)}",
                model=request["model"],
                usage=None,
                model_extra={},
                output_parsed=next(decisions),
            )

        async def close(self):
            closed.append(True)

    monkeypatch.setitem(
        sys.modules, "openai", SimpleNamespace(AsyncOpenAI=FakeClient, APIError=RuntimeError)
    )
    app = create_console(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        client.headers["x-relay-token"] = app.state.control_token
        response = await client.post(
            "/api/run",
            json={
                "mode": "discover",
                "inputs": dict(member_id="12345", account_type="savings", nickname="PrivateName"),
            },
        )
        assert response.status_code == 200
        result = await manager.task
        assert (result.status, result.code) == ("success", "completed")
        assert len(requests) == result.model_calls == 7
        assert manager.current.artifact.provenance.kind == "test_fixture"
        assert manager.current.artifact.provenance.provider == (
            "experiential_responses" if provider == "experiential" else "openai_responses"
        )
        assert len(clients) == 1 and closed == [True]
        assert clients[0]["api_key"] == key
        assert clients[0]["base_url"] == (
            "https://api.experientiallabs.ai/v1"
            if provider == "experiential"
            else "https://api.openai.com/v1"
        )
        assert "PrivateName" not in str(requests)
        monkeypatch.delenv(key_name)
        response = await client.post(
            "/api/run",
            json={
                "mode": "replay",
                "inputs": dict(member_id="67890", account_type="money_market", nickname="NewName"),
            },
        )
        assert response.status_code == 200
        result = await manager.task
        assert (result.status, result.code) == ("success", "completed")
        assert result.outputs["nickname"] == "NewName"
        assert result.model_calls == 0
        assert len(requests) == 7 and len(clients) == 1
