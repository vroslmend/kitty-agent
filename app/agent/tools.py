"""The tools the model can call.

A tool's docstring is not documentation, it is the contract the model reads to
decide whether to call it. Vague docstrings are the usual cause of an agent
picking the wrong tool, so each one says what it answers, and says which
neighbouring tool to use instead where two of them look similar.

Tools that reach the network return a plain sentence on failure rather than
raising. The model can relay "GitHub is not answering" to a visitor; it cannot
do anything useful with a traceback.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from langchain_core.tools import tool
from langgraph.types import interrupt

from app.config import get_settings
from app.content import pages, projects, site
from app.rag.store import search

# Short on purpose. These run inside a serverless invocation with a wall-clock
# budget, and a slow upstream must not spend it all before the model can answer.
TIMEOUT = httpx.Timeout(8.0, connect=4.0)

GITHUB_API = "https://api.github.com"
AMMAR_TIMEZONE = ZoneInfo("Asia/Karachi")


def _current_year() -> int:
    return datetime.now(AMMAR_TIMEZONE).year


def _project_topic(topic: str) -> str:
    cleaned = topic.lower().strip()
    if cleaned in {"this year", "current year"}:
        return str(_current_year())
    return topic.strip()


def _matches(project: dict, topic: str) -> bool:
    haystack = " ".join(
        [
            project["name"],
            project["slug"],
            project["tagline"],
            project["description"],
            project["year"],
            *project["stack"],
        ]
    ).lower()
    return topic.lower().strip() in haystack


def _render(project: dict) -> str:
    stack = ", ".join(project["stack"])
    links = " ".join(f"{k}: {v}" for k, v in project["links"].items())
    lines = [
        f"{project['name']} ({project['year']}) - {project['tagline']}",
        f"  {project['description']}",
        f"  stack: {stack}",
    ]
    if links:
        lines.append(f"  {links}")
    return "\n".join(lines)


@tool
def list_projects(topics: list[str] | None = None) -> str:
    """Look up the projects Ammar has built, optionally filtered by topics.

    Each topic is matched against project names, taglines, descriptions, tech
    stacks and years. Pass every relevant alternative in one call, even for a
    single topic: ["python"], ["terraform"], or ["realtime", "multiplayer"].
    A project matching any topic is returned. Leave the list out to get the
    projects he features. For what he built "this year", pass ["this year"];
    the tool resolves it to his local calendar year.

    Use this for anything about what he has built or what a named project is.
    A calendar period such as "this year" means projects here, not recent
    GitHub activity. Use get_github_activity only for what he is working on
    right now or has pushed lately, and search_writing for his essays.
    """
    all_projects = projects()
    cleaned_topics = [_project_topic(topic) for topic in topics or [] if topic.strip()]
    if cleaned_topics:
        found = [p for p in all_projects if any(_matches(p, topic) for topic in cleaned_topics)]
        if not found:
            names = ", ".join(p["name"] for p in all_projects)
            rendered = ", ".join(repr(topic) for topic in cleaned_topics)
            return f"No project matches any of {rendered}. The projects are: {names}."
        rendered = ", ".join(repr(topic) for topic in cleaned_topics)
        header = f"{len(found)} project(s) matching any of {rendered}:"
    else:
        found = [p for p in all_projects if p["featured"]]
        header = f"His featured projects ({len(all_projects)} in total):"
    return header + "\n\n" + "\n\n".join(_render(p) for p in found)


@tool
def suggest_navigation(topic: str) -> str:
    """Find where something lives on the site and return a path to link to.

    Use this when a visitor asks where something is or asks to be taken
    somewhere: the photos, the writing, a particular essay, the resume, his
    GitHub or LinkedIn.

    This points at a destination, it does not answer the question. If they
    asked what he has written about, use search_writing instead; if they asked
    to be taken to the writing, use this.
    """
    query = topic.lower().strip()
    links = site()["links"]

    destinations: list[tuple[str, str, list[str]]] = [
        ("/", "the home page", ["home", "start", "index", "main", "landing"]),
        ("/about", "about him", ["about", "bio", "who", "background", "himself"]),
        ("/work", "his work and projects", ["work", "projects", "portfolio", "built"]),
        ("/writing", "his writing", ["writing", "essays", "blog", "posts", "articles"]),
        ("/photos", "his photos", ["photo", "photos", "photography", "pictures"]),
        (links["resume"], "his resume", ["resume", "cv", "curriculum"]),
        (links["github"], "his GitHub", ["github", "code", "repos", "repositories"]),
        (links["linkedin"], "his LinkedIn", ["linkedin"]),
    ]
    for page in pages():
        if page["route"].startswith("/writing/"):
            slug = page["route"].rsplit("/", 1)[-1]
            keywords = [slug, *slug.split("-"), *page["title"].lower().split()]
            destinations.append((page["route"], f"the essay {page['title']!r}", keywords))

    for path, label, keywords in destinations:
        if any(k in query for k in keywords):
            return f"{label}: {path}"

    routes = ", ".join(path for path, _, _ in destinations)
    return f"Nothing on the site matches {topic!r}. Available destinations: {routes}."


@tool
async def get_now_playing() -> str:
    """Check what Ammar is listening to on Spotify.

    Answers what is playing right now, and if nothing is, what he played most
    recently. It has no further history than that one track, so it cannot say
    what he was listening to at some past moment.

    Use this only for music. His essay about building this feature is a
    different thing, and that is search_writing.
    """
    url = get_settings().now_playing_url
    if not url:
        return "The now-playing feed is not configured, so I cannot check."
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        return "The now-playing feed is not responding, so I cannot check right now."

    title, artist = data.get("title"), data.get("artist")
    if not title:
        return "Nothing is playing, and there is no recent track to report."
    # isPlaying false with a title means the feed fell back to the last track.
    # Reporting that as live would be a small lie the visitor cannot check.
    if data.get("isPlaying"):
        return f"Playing right now: {title} by {artist}."
    return f"Nothing is playing right now. The last track was {title} by {artist}."


@tool
async def get_github_activity(limit: int = 5) -> str:
    """Check what Ammar has been pushing to GitHub recently.

    Returns his most recently updated public repositories, newest first, with
    when each was last pushed to. Use this for what he is working on now, or
    lately, or whether he is still active.

    Use list_projects instead for what he has built in general or built during
    a calendar period such as "this year". This one sees only recent pushes,
    not his whole history, and not private work.
    """
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    url = f"{GITHUB_API}/users/{settings.github_username}/repos"
    params = {"sort": "pushed", "direction": "desc", "per_page": max(1, min(limit, 10))}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code in (403, 429):
                return "GitHub is rate limiting me, so I cannot check his recent activity."
            response.raise_for_status()
            repos = response.json()
    except httpx.HTTPError:
        return "GitHub is not responding, so I cannot check his recent activity right now."

    if not repos:
        return "GitHub returned no public repositories."
    lines = [
        f"{r['name']} - pushed {r['pushed_at'][:10]}"
        + (f" - {r['description']}" if r.get("description") else "")
        for r in repos
    ]
    return "Most recently pushed public repositories:\n" + "\n".join(lines)


@tool
async def search_writing(query: str) -> str:
    """Search what Ammar has written in his essays.

    Use this for his opinions, his reasoning, or how he thinks about something,
    and to find whether he has written on a topic at all. Returns passages with
    the route each came from, so the answer can point at the full piece.

    Use list_projects instead for what he built rather than what he wrote about
    it, and suggest_navigation if they only want a link to the writing rather
    than an answer drawn from it.
    """
    if not get_settings().database_url:
        return "The writing index is not configured, so I cannot search the essays."
    try:
        rows = await search(query, limit=4)
    except Exception:
        # Anything from the database or the embedding call. A visitor is better
        # served by one honest sentence than by the agent failing mid-answer.
        return "I could not search the writing just now."

    if not rows:
        return f"Nothing in his writing matches {query!r}."
    passages = [f"From {r['title']!r} ({r['route']}):\n{r['content']}" for r in rows]
    return "\n\n".join(passages)


@tool
def ask_clarification(question: str, options: list[str]) -> str:
    """Ask the visitor which of several things they meant, and wait for them.

    Use this when a question could reasonably point at more than one project,
    essay or page, and picking wrong would send them somewhere useless. Pass
    one short question and the candidates you are choosing between, named as
    the visitor would recognise them. Their answer comes back as the result.

    Do not use it to be polite about a question you can answer, and do not
    guess and then ask. Call it on its own: the other tools in the same turn
    run a second time when the visitor replies.
    """
    return interrupt({"question": question, "options": options})


TOOLS = [
    search_writing,
    list_projects,
    suggest_navigation,
    get_now_playing,
    get_github_activity,
    ask_clarification,
]
