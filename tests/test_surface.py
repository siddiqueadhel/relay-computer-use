from types import SimpleNamespace

import pytest
from playwright.async_api import Error as BrowserError

from relay.control import SessionControl
from relay.evidence import Journal, Redactor
from relay.policy import Policy, PolicyViolation
from relay.schema import visible
from relay.surface import BrowserSurface, SurfaceError


@pytest.fixture
def surface(tmp_path):
    journal = Journal(tmp_path, Redactor(), mode="test")
    return BrowserSurface("http://127.0.0.1:8765/", Policy(), SessionControl(journal), journal)


async def test_uncommitted_frames_are_not_observed_or_treated_as_destinations(surface):
    surface.page = SimpleNamespace(
        frames=[SimpleNamespace(url=""), SimpleNamespace(url="about:blank")]
    )
    surface._check_destinations()
    assert await surface.observe() == {"frames": []}


@pytest.mark.parametrize(
    "url,code",
    [
        ("https://evil.invalid/", "origin_denied"),
        ("http://127.0.0.1:8765/commit", "route_denied"),
        ("data:text/html,forbidden", "invalid_destination"),
    ],
)
def test_loading_frame_does_not_hide_a_forbidden_committed_frame(surface, url, code):
    surface.page = SimpleNamespace(frames=[SimpleNamespace(url=""), SimpleNamespace(url=url)])
    with pytest.raises(PolicyViolation) as exc:
        surface._check_destinations()
    assert exc.value.code == code


@pytest.mark.parametrize("detached", [True, False])
async def test_detached_frame_is_a_missing_checkpoint_not_an_unrelated_browser_error(
    surface, detached
):
    async def failed_count():
        raise BrowserError("Synthetic browser error during a locator query")

    locator = SimpleNamespace(count=failed_count)
    frame = SimpleNamespace(
        get_by_role=lambda *args, **kwargs: locator,
        is_detached=lambda: detached,
    )
    surface.page = SimpleNamespace(frames=[])
    surface._frame = lambda path: frame
    if detached:
        assert not await surface.check([visible("Expected screen")], {})
    else:
        with pytest.raises(BrowserError):
            await surface.check([visible("Expected screen")], {})


async def test_observation_retries_only_read_only_navigation_races(surface):
    calls = 0

    async def evaluate(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BrowserError(
                "Execution context was destroyed, most likely because of a navigation"
            )
        if calls == 2:
            return None  # New document still loading.
        return {"headings": [], "controls": [], "text": "Ready"}

    frame = SimpleNamespace(
        url="http://127.0.0.1:8765/workspace", parent_frame=None, evaluate=evaluate
    )
    surface.page = SimpleNamespace(frames=[frame])
    result = await surface.observe()
    assert result["frames"][0]["text"] == "Ready"
    assert calls == 3
    assert surface.journal.events[-1]["retries"] == 2


async def test_unrelated_observation_error_is_not_retried(surface):
    calls = 0

    async def evaluate(*args):
        nonlocal calls
        calls += 1
        raise BrowserError("Unrelated browser error")

    frame = SimpleNamespace(
        url="http://127.0.0.1:8765/workspace", parent_frame=None, evaluate=evaluate
    )
    surface.page = SimpleNamespace(frames=[frame])
    with pytest.raises(SurfaceError, match="observation_failed"):
        await surface.observe()
    assert calls == 1
