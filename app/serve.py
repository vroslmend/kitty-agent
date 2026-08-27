"""Local development server.

    ./.venv/Scripts/python.exe -m app.serve          # or PORT=8123 to move it

Not the same as `python -m uvicorn app.main:app`. Uvicorn creates its event
loop before importing the application, so setting the loop policy inside
`app.main` runs too late and psycopg's async mode then refuses to work on
Windows' default ProactorEventLoop. The symptom is every question answering
"something went wrong on my end" while the server log fills with
"error connecting in 'pool-1'".

This sets the policy first, then hands over to uvicorn. It matters only on
Windows. Vercel runs Linux, imports the app itself, and never sees any of this.
"""

import os
import socket
import sys

import uvicorn

from app.db import use_selector_loop_on_windows


def already_serving(host: str, port: int) -> bool:
    """Whether something already answers on the port.

    Uvicorn sets SO_REUSEADDR, and Windows honours it to the point of letting a
    second process bind a port a live one is already listening on. Neither
    complains, connections go to whichever the kernel picks, and the older
    server keeps answering with whatever code it was started on. That reads as
    a change having no effect, which is a long way from the cause.
    """
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def main() -> None:
    use_selector_loop_on_windows()
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", "8000"))

    if already_serving(host, port):
        print(
            f"something is already serving on {host}:{port}. Stop it, or set PORT.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    uvicorn.run("app.main:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    main()
