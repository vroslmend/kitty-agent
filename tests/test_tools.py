"""What each tool returns, including when the network is against it.

The network tools are exercised through a mock transport rather than by calling
Spotify and GitHub. What matters here is that a failing upstream produces a
sentence the model can relay, not a traceback: that is golden case gh-05, and
it is the whole reason get_github_activity is in the tool set.
"""

import httpx
import pytest

import app.agent.tools as tool_module
from app.agent.tools import (
    TOOLS,
    get_github_activity,
    get_now_playing,
    list_projects,
    suggest_navigation,
)


def mock_transport(monkeypatch, handler) -> None:
    """Point httpx.AsyncClient at a handler instead of the internet."""

    # Capture the real class first. Referring to httpx.AsyncClient inside the
    # factory would resolve to the factory itself once the patch is in place.
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_every_tool_has_a_description() -> None:
    # The description is the contract the model routes on. An empty one is a
    # silent bug: the tool still works and the model stops choosing it.
    for t in TOOLS:
        assert t.description and t.description.strip(), f"{t.name} has no description"


def test_list_projects_defaults_to_the_featured_ones() -> None:
    result = list_projects.invoke({})
    assert "CUI Central" in result
    # Not featured, so it must not appear in the unfiltered answer.
    assert "Lead Tracker" not in result


def test_list_projects_filters_on_stack() -> None:
    result = list_projects.invoke({"topics": ["terraform"]})
    assert "Cloud Visitor Counter" in result
    assert "Check!" not in result


def test_list_projects_filters_on_year() -> None:
    result = list_projects.invoke({"topics": ["2023"]})
    assert "Lead Tracker" in result


def test_list_projects_resolves_this_year_in_ammars_timezone(monkeypatch) -> None:
    monkeypatch.setattr(tool_module, "_current_year", lambda: 2026)

    result = list_projects.invoke({"topics": ["this year"]})

    assert "Cloud Visitor Counter" in result
    assert "Lead Tracker" not in result


def test_list_projects_matches_related_topics_in_one_call() -> None:
    result = list_projects.invoke({"topics": ["realtime", "multiplayer"]})

    assert "Check!" in result


def test_list_projects_says_so_when_nothing_matches() -> None:
    result = list_projects.invoke({"topics": ["kubernetes"]})
    assert "No project matches" in result
    # It still lists what does exist, so the model can offer something.
    assert "CUI Central" in result


def test_suggest_navigation_finds_a_static_page() -> None:
    assert "/photos" in suggest_navigation.invoke({"topic": "where are the photos"})


def test_suggest_navigation_finds_an_essay_by_words_in_its_title() -> None:
    assert "/writing/visitor-counter" in suggest_navigation.invoke({"topic": "visitor counter"})


def test_suggest_navigation_returns_external_links() -> None:
    assert "github.com" in suggest_navigation.invoke({"topic": "his github"})


def test_suggest_navigation_admits_when_it_has_nothing() -> None:
    result = suggest_navigation.invoke({"topic": "his kubernetes cluster"})
    assert "Nothing on the site matches" in result


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"isPlaying": True, "title": "Song", "artist": "Band"}, "Playing right now: Song"),
        # isPlaying false with a title is the feed's recently-played fallback.
        # Reporting it as live would be a lie the visitor cannot check.
        ({"isPlaying": False, "title": "Song", "artist": "Band"}, "The last track was Song"),
        ({"isPlaying": False}, "Nothing is playing, and there is no recent track"),
    ],
)
async def test_now_playing_distinguishes_live_from_last_played(
    monkeypatch, payload, expected
) -> None:
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    assert expected in await get_now_playing.ainvoke({})


async def test_now_playing_reports_an_unreachable_feed(monkeypatch) -> None:
    def refuse(request):
        raise httpx.ConnectError("no route to host")

    mock_transport(monkeypatch, refuse)
    result = await get_now_playing.ainvoke({})
    assert "not responding" in result


async def test_github_activity_lists_recent_pushes(monkeypatch) -> None:
    repos = [{"name": "kitty-agent", "pushed_at": "2026-08-27T09:00:00Z", "description": "d"}]
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json=repos))
    result = await get_github_activity.ainvoke({})
    assert "kitty-agent" in result
    assert "2026-08-27" in result


async def test_github_activity_reports_rate_limiting(monkeypatch) -> None:
    # Unauthenticated GitHub is 60 requests an hour shared across every visitor,
    # so this is the failure most likely to actually happen in production.
    mock_transport(monkeypatch, lambda request: httpx.Response(403, json={}))
    assert "rate limiting" in await get_github_activity.ainvoke({})


async def test_github_activity_reports_an_outage(monkeypatch) -> None:
    mock_transport(monkeypatch, lambda request: httpx.Response(500, json={}))
    result = await get_github_activity.ainvoke({})
    assert "not responding" in result
