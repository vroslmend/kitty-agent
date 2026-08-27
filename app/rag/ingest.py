"""Build the vector store from the live essays.

    ./.venv/Scripts/python.exe -m app.rag.ingest

Reads the rendered pages rather than the source. The essays are React
components with the prose inline in JSX, so the HTML the site actually serves
is the only place the text exists as text. It also means new essays need no
change here: they arrive through the same sync that fills app/data/site.json.

Re-run after publishing or editing an essay.
"""

import asyncio
import re
import sys
from html.parser import HTMLParser

import httpx

from app.content import pages
from app.db import close_pool, use_selector_loop_on_windows
from app.rag.store import create_schema, replace_route

# Big enough to hold an argument, small enough that a hit points at a passage
# rather than at half the essay. The overlap stops a paragraph that straddles a
# boundary from being retrievable by neither side.
CHUNK_CHARS = 900
OVERLAP_CHARS = 150

SKIP_TAGS = {"script", "style", "svg", "noscript", "head"}


class Prose(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIP_TAGS:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.depth and data.strip():
            self.parts.append(data.strip())


def extract(html: str) -> str:
    parser = Prose()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts))
    # Everything before the reading-time badge is site chrome: the nav, the
    # wordmark, the date. Left in, "work about writing photos" would match
    # navigational queries that belong to suggest_navigation.
    if marker := re.search(r"\d+\s*min\b", text):
        text = text[marker.end() :].strip()
    return text


def chunk(text: str) -> list[str]:
    if len(text) <= CHUNK_CHARS:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = start + CHUNK_CHARS
        # Prefer a sentence boundary near the end so a chunk does not stop
        # mid-clause, which reads badly when the model quotes it back.
        window = text[start:end]
        if end < len(text) and (cut := window.rfind(". ")) > CHUNK_CHARS // 2:
            end = start + cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - OVERLAP_CHARS
    return [c for c in chunks if c]


async def main() -> int:
    essays = [p for p in pages() if p["route"].startswith("/writing/")]
    if not essays:
        print("no essays in app/data/site.json, run the sync script first", file=sys.stderr)
        return 1

    await create_schema()
    base = "https://ammarhassan.dev"
    total = 0
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for essay in essays:
            response = await client.get(base + essay["route"])
            response.raise_for_status()
            chunks = chunk(extract(response.text))
            if not chunks:
                print(f"  {essay['route']}: no prose found, skipping", file=sys.stderr)
                continue
            written = await replace_route(essay["route"], essay["title"], chunks)
            total += written
            print(f"  {essay['route']}: {written} chunks")

    await close_pool()
    print(f"{total} chunks across {len(essays)} essays")
    return 0


if __name__ == "__main__":
    use_selector_loop_on_windows()
    raise SystemExit(asyncio.run(main()))
