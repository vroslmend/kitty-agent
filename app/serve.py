"""Local development server.

    ./.venv/Scripts/python.exe -m app.serve

Not the same as `python -m uvicorn app.main:app`. Uvicorn creates its event
loop before importing the application, so setting the loop policy inside
`app.main` runs too late and psycopg's async mode then refuses to work on
Windows' default ProactorEventLoop. The symptom is every question answering
"something went wrong on my end" while the server log fills with
"error connecting in 'pool-1'".

This sets the policy first, then hands over to uvicorn. It matters only on
Windows. Vercel runs Linux, imports the app itself, and never sees any of this.
"""

import uvicorn

from app.db import use_selector_loop_on_windows


def main() -> None:
    use_selector_loop_on_windows()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
