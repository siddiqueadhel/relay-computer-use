import httpx
import pytest

from relay.bank import create_bank


@pytest.mark.parametrize(
    "member,expected", [("12345", "Search results"), ("99999", "Member not found")]
)
async def test_fixture_serves_browser_forms_without_business_api(member, expected):
    app = create_bank()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")
        assert 'name="workspace"' in response.text
        assert "northstar" in client.cookies
        response = await client.post("/search", data={"member": member})
        assert f"<h1>{expected}</h1>" in response.text
        assert (await client.get("/api/members")).status_code == 404


async def test_session_restoration_preserves_member_and_review_escapes_input():
    app = create_bank()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.get("/?scenario=session_expired")
        await client.post("/search", data={"member": "12345"})
        assert "Staff session expired" in (await client.get("/subaccount")).text
        assert "Prepare sub-account" in (await client.post("/restore")).text
        result = await client.post(
            "/review", data={"account_type": "savings", "nickname": "<script>alert(1)</script>"}
        )
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result.text
        assert "<td data-private>12345</td>" in result.text
        assert "ready_for_review" in result.text
        assert len(app.state.sessions) == 1
        assert next(iter(app.state.sessions.values())).commits == 0


async def test_harbor_variant_changes_markup_without_changing_business_contract():
    app = create_bank()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert "Harbor Mutual" in (await client.get("/?variant=harbor")).text
        first = (await client.get("/workspace")).text
        second = (await client.get("/workspace")).text
        assert first != second  # Transient control IDs; labels remain associated.
        assert 'id="member-query"' not in first
        await client.post("/search", data={"member": "24680"})
        form = (await client.get("/subaccount")).text
        assert form.index("<th><span>Account name") < form.index("<th><span>Account type")
        assert "legacy-wrapper" in form
