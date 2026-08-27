"""Cut the suite off from the developer's `.env` entirely.

`Settings` reads `.env`, and `app.main` resolves settings at import, so any
value configured locally silently leaks into the tests. That is green here and
red in CI, which has no `.env`, and it has already happened twice: once on
`LLM_API_KEY` and once on `NOW_PLAYING_URL`.

Pinning variables one at a time only fixes the ones someone thought of. Turning
the dotenv file off makes the suite run on the same defaults CI sees, so a
setting added later cannot reintroduce the problem.

This runs at import, before any test module imports the app.
"""

from app.config import Settings

Settings.model_config["env_file"] = None
