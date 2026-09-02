<p align="center">
  <img src="assets/kitty-mark.svg" width="144" alt="kitty, a small line-art cat">
</p>

<h1 align="center">kitty</h1>

<div align="center">
  <p>The on-site agent for <a href="https://ammarhassan.dev">ammarhassan.dev</a>.</p>

  <p>A LangGraph tool-calling agent behind a FastAPI server,<br>streaming its steps to the kitty widget in the portfolio.</p>

  <p>Retrieval is one of its tools, not the shape of the program.</p>

  <p><a href="https://github.com/vroslmend/kitty-agent/actions/workflows/ci.yml"><img src="https://github.com/vroslmend/kitty-agent/actions/workflows/ci.yml/badge.svg" alt="CI"></a></p>
</div>

## Architecture

```mermaid
flowchart LR
    subgraph pf["portfolio-v2 · Next.js on Vercel"]
        widget["kitty widget"]
    end

    subgraph ka["kitty-agent · Python on Vercel"]
        api["FastAPI"]
        loop["LangGraph loop"]
        store[("Neon Postgres<br/>checkpoints · pgvector")]
        api --> loop
        loop --> store
    end

    widget -->|"POST /chat"| api
    api -.->|"SSE: step, token, question, done"| widget
```

Two repositories and two deployments. The portfolio is a Next.js frontend and
this repository is a Python service; the HTTP contract is their only coupling.

Both deploy to Vercel as separate projects. This service runs as a single
Python function, while conversation memory lives in Postgres rather than
depending on a warm process.

## The loop

A ReAct loop, built by hand rather than with the prebuilt helper. The agent
node decides whether to answer or call a tool. If it called one, the results
are appended to the message list and it runs again with them in hand.

```mermaid
flowchart TD
    start([START]) --> agent["agent<br/>LLM bound to the tools"]
    agent -->|"no tool calls"| finish([END])
    agent -->|"tool calls present"| tools["tools<br/>ToolNode"]
    tools -->|"results appended"| agent
```

Retrieval is one of those tools. It is not the shape of the program.

Drive it directly, without the API in front:

```bash
./.venv/Scripts/python.exe -m app.agent "which of his projects use terraform?"
```

It prints each decision as it happens, so a wrong tool choice is visible rather
than buried in the final answer.

## Tools

A tool's docstring is the contract the model reads to decide whether to call
it, so each one also names the neighbouring tool to use instead. The near-miss
pairs are what routing actually gets wrong: asking where his GitHub is wants a
link, not a list of his recent commits.

| Tool | Answers |
|---|---|
| `list_projects` | What he has built, filtered by stack, year or keyword. |
| `suggest_navigation` | Where something lives on the site, as a path to link to. |
| `get_now_playing` | What he is listening to, or last listened to. |
| `get_github_activity` | What he has pushed recently. |
| `search_writing` | His essays, over pgvector. |
| `ask_clarification` | Nothing. It stops the run and asks the visitor which one they meant. |

The two that reach the network return a sentence on failure rather than
raising. The model can relay that GitHub is rate limiting to a visitor; it can
do nothing useful with a traceback.

`list_projects` and `suggest_navigation` read `app/data/site.json`, which is
generated from the portfolio rather than written twice:

```bash
node scripts/sync_site_content.mjs
```

Re-run it when the portfolio's projects or writing change.

## Evals

`evals/dataset.jsonl` contains 58 golden questions covering tool-free answers,
routing near misses, clarification, prompt injection, unsupported claims,
upstream failure, voice, and multi-turn conversation.

The runner scores tool routing mechanically and can judge `must` / `must_not`
answer criteria separately:

```bash
python -m evals.run --no-judge
python -m evals.run --judge
```

See `evals/README.md` for filters, reports, scoring, and failure-path setup.

## Run it

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
cp .env.example .env
./.venv/Scripts/python.exe -m app.db setup              # once, creates the tables
./.venv/Scripts/python.exe -m app.rag.ingest            # once, builds the index
./.venv/Scripts/python.exe -m app.serve
```

Use `app.serve` rather than calling uvicorn directly. Uvicorn creates its event
loop before importing the application, and psycopg's async mode will not run on
Windows' default loop, so the policy has to be set before uvicorn starts. The
symptom otherwise is every question answering "something went wrong on my end".
Linux is unaffected, and Vercel imports the app itself.

`app.serve` also refuses to start when the port is busy. Windows honours
`SO_REUSEADDR` far enough to let a second server bind a port a live one is
already listening on, and then connections go to whichever the kernel picks. Set
`PORT` to run more than one.

Then:

```bash
curl localhost:8000/health
curl -N -X POST localhost:8000/chat -H 'Content-Type: application/json' -d '{"message":"hello"}'
```

`-N` matters on the second one. Without it curl buffers and the stream looks
like a single blob.

## Tests

```bash
./.venv/Scripts/python.exe -m pytest
```

Nothing in the suite calls a model or the network. The tests deliberately do
not read `.env`, so they run on the same defaults CI sees.

## Configuration

Everything is read once at boot through `pydantic-settings`. See `.env.example`.

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | Reported by `/health`. |
| `ALLOWED_ORIGINS` | Comma separated CORS origins. |
| `LLM_API_KEY` | Empty means `/chat` returns the napping fallback rather than an error. |
| `LLM_MODEL` | Default `gemini-3.5-flash-lite`. |
| `DATABASE_URL` | Neon, pooled. Checkpoints, rate limits, and pgvector. |
| `NOW_PLAYING_URL` | The portfolio's Spotify proxy, so the refresh token lives in one place. |
| `GITHUB_USERNAME` / `GITHUB_TOKEN` | The token is optional and needs no scopes. Without it GitHub allows 60 requests an hour shared across every visitor. |
| `SITE_BASE_URL` | The portfolio's origin. |
| `MAX_TOKENS_PER_REQUEST` | Cost ceiling, applied as the model's output cap. |
| `RATE_LIMIT_PER_MINUTE` | Requests per client per minute on `/chat`. Enforced. Over it returns 429. |

## The `/chat` protocol

`POST /chat` with `{"message": str, "thread_id": str | None}` returns
`text/event-stream`. Each frame is one JSON object:

| `type` | Payload | Meaning |
|---|---|---|
| `step` | `label` | The agent started a lookup. Renders as the current status. |
| `token` | `text` | A piece of the answer. |
| `question` | `text`, `options` | The agent stopped to ask which one. Reply on the same thread. |
| `done` | `thread_id` | Finished. Send this `thread_id` back to continue the conversation. |
| `error` | `message` | Something failed. |

Over the rate limit, `/chat` returns `429` with a JSON body rather than a
stream, and a `Retry-After` header. `/health` is not rate limited, or the
platform's own probes would consume the allowance.

The limit is counted twice: once in process, and once in Postgres. In process
alone is wrong on serverless, where the real allowance would be the limit
multiplied by however many instances happen to be warm. The shared count is a
single statement holding a per-client advisory lock, so instances racing on the
same client cannot each read the same under-limit count and both admit a
request. If the database is unreachable the in-process window still applies:
degraded to per instance, never absent.

A turn ends on either an answer or a `question`, and `done` follows both. When
it ends on a question the run is paused rather than finished: it is sitting in
the checkpointer mid tool call, and the next `POST /chat` on that `thread_id`
is the reply. There is no resume flag and no second endpoint, because the
server can see from the saved state that the thread is waiting. Whatever the
visitor sends is handed back as the paused tool's result and the run carries on
from where it stopped.

This shape is the contract. What produces the events can change without making
the portfolio widget learn a new protocol.

## Deploy

Vercel, as its own project pointed at this repository. Vercel detects
`app/main.py` automatically, so no build command is needed. `vercel.json` caps
the function duration and keeps development files out of the bundle.

1. Import the repo at [vercel.com/new](https://vercel.com/new) with no
   environment variables. An empty `LLM_API_KEY` means the service comes up in
   the napping fallback and cannot call a model, so a first deploy proves the
   hosting without exposing anything.
2. Attach Neon from the project's Storage tab. It writes `DATABASE_URL` in.
3. Add `LLM_API_KEY`, and set `ALLOWED_ORIGINS` to the portfolio's origin.
4. With the production `DATABASE_URL` available locally, initialize Postgres:

   ```bash
   python -m app.db setup
   python -m app.rag.ingest
   ```

The Dockerfile is kept for local runs and portability. It is not what Vercel
builds, and the service is deliberately host agnostic: it binds `PORT` and
keeps durable state in Postgres, so a container host is a fallback rather than
a rewrite.

Then set `NEXT_PUBLIC_KITTY_API_URL` in the portfolio to the deployed URL. When
it is unset, the widget stays hidden.

## Credits

The “Cat” icon used in the mark is by [inmyheart](https://thenounproject.com/icon/match/cat-8273692/), from [Noun Project](https://thenounproject.com/browse/icons/term/cat/) (CC BY 3.0).
