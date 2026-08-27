"""Pin the environment the suite runs against.

`Settings` reads `.env`, and `app.main` resolves settings at import time, so
without this the result depends on whatever the developer happens to have
configured locally: green in CI, which has no `.env`, and red the moment someone
pastes a real key in. Environment variables outrank the dotenv file, so setting
them here decides it before any test module imports the app.

Nothing in the suite calls the model. An empty key is the documented baseline:
`/chat` answers with the napping fallback rather than failing.
"""

import os

os.environ["LLM_API_KEY"] = ""
os.environ["RATE_LIMIT_PER_MINUTE"] = "10"
