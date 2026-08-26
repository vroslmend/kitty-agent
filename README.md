# kitty

[![CI](https://github.com/vroslmend/kitty-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/vroslmend/kitty-agent/actions/workflows/ci.yml)

The on-site agent for [ammarhassan.dev](https://ammarhassan.dev). A LangGraph
tool-calling agent behind a FastAPI server, streaming its steps to a chat widget
in the portfolio.

It is an agent rather than a retrieval chatbot on purpose. Retrieval is one tool
among several, not the architecture.

**Status: phase 0.** The service boots, speaks SSE, and reports its own health.
There is no graph behind `/chat` yet, so every request returns the napping
fallback.

## Architecture

```
┌────────────────────────────┐        ┌─────────────────────────────┐
│ portfolio-v2               │  HTTP  │ kitty-agent (this repo)     │
│ Next.js, static, Vercel    │  SSE   │ Python · FastAPI · LangGraph│
│                            │ ─────▶ │ container host              │
│ components/kitty-chat.tsx  │ ◀───── │ + Postgres (pgvector)       │
└────────────────────────────┘ stream └─────────────────────────────┘
```

The backend is a separate repo and a separate deploy because it is a
long-running process and the portfolio is a static site. This mirrors
`cloud-visitor-counter`, which is also consumed client side.

## Run it

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
cp .env.example .env
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

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

## Configuration

Everything is read once at boot through `pydantic-settings`. See `.env.example`.

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | Reported by `/health`. |
| `ALLOWED_ORIGINS` | Comma separated CORS origins. |
| `LLM_API_KEY` | Empty until the agent exists. Empty means `/chat` returns the napping fallback rather than an error. |
| `MAX_TOKENS_PER_REQUEST` | Cost ceiling. Declared now, enforced in a later phase. |
| `RATE_LIMIT_PER_MINUTE` | Abuse ceiling. Same. |

## The `/chat` protocol

`POST /chat` with `{"message": str, "thread_id": str | None}` returns
`text/event-stream`. Each frame is one JSON object:

| `type` | Payload | Meaning |
|---|---|---|
| `step` | `label` | The agent started doing something. Renders as a chip. |
| `token` | `text` | A piece of the answer. |
| `done` | `thread_id` | Finished. Send this `thread_id` back to continue the conversation. |
| `error` | `message` | Something failed. |

This shape is final. Phase 4 changes what produces the events, not the events
themselves, so the widget can be written against it now.

## Deploy

Any container host that builds a Dockerfile. Railway and Render both do this
from a connected repo with no extra configuration.

1. Create the service and point it at this repo.
2. Set the environment variables above. `ALLOWED_ORIGINS` must include the
   portfolio's production origin.
3. The host injects `PORT`; the container already binds it.
4. Point the health check at `/health`.

Then set `NEXT_PUBLIC_KITTY_API_URL` in the portfolio to the deployed URL. Unset
means the widget stays hidden, the same convention the visitor counter and
now-playing widget use.

## Phases

- [x] **0. Scaffold.** FastAPI, config, SSE shape, Dockerfile, deploy.
- [ ] **1. Bare LangGraph loop.** StateGraph, agent node, one dummy tool, conditional edge.
- [ ] **2. Real tools.** `get_now_playing`, `list_projects`, `suggest_navigation`.
- [ ] **3. RAG as a tool.** `search_writing` over the essays and project copy.
- [ ] **4. Streaming and the UI.** `astream_events` into the widget.
- [ ] **5. Memory and clarify.** Checkpointer, `thread_id`, one interrupt path.
- [ ] **6. Evals and tracing.** Golden set, tool-choice accuracy, LLM as judge.
- [ ] **7. Polish and ship.**

Evals are not optional. They are the difference between this and a wrapper.
