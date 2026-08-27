"""Drive the graph from a terminal, before there is an API in front of it.

    ./.venv/Scripts/python.exe -m app.agent "what time is it for him?"

Pass the same thread twice to check that it remembers:

    ./.venv/Scripts/python.exe -m app.agent --thread t1 "which use terraform?"
    ./.venv/Scripts/python.exe -m app.agent --thread t1 "what stack is it on?"

Prints each step as it happens, so a wrong tool choice or a loop that will not
terminate is visible rather than buried in a final answer.
"""

import argparse
import asyncio
import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import RECURSION_LIMIT, build_graph
from app.config import get_settings
from app.db import close_pool, get_checkpointer, use_selector_loop_on_windows


def describe(message) -> str | None:
    if isinstance(message, AIMessage):
        if message.tool_calls:
            calls = ", ".join(
                f"{c['name']}({', '.join(f'{k}={v!r}' for k, v in c['args'].items())})"
                for c in message.tool_calls
            )
            return f"  agent -> calls {calls}"
        # .text, not .content. Under Gemini 3 the content is a list of blocks
        # carrying the thought signature, so printing it raw dumps the plumbing.
        # .text is a str subclass and flattens both shapes.
        return f"  agent -> answers\n\n{message.text}\n"
    if isinstance(message, ToolMessage):
        return f"  tool  <- {message.name}: {message.content}"
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.agent")
    parser.add_argument("question", nargs="+")
    parser.add_argument("--thread", help="reuse a thread id to continue a conversation")
    args = parser.parse_args()
    question = " ".join(args.question).strip()

    settings = get_settings()
    if not settings.agent_ready:
        print("LLM_API_KEY is empty, so there is no agent to drive.", file=sys.stderr)
        return 1

    checkpointer = await get_checkpointer() if settings.database_url else None
    if args.thread and checkpointer is None:
        print("--thread needs DATABASE_URL, there is nowhere to remember.", file=sys.stderr)
        return 1

    graph = build_graph(settings, checkpointer=checkpointer)
    thread_id = args.thread or "cli"
    config = {"recursion_limit": RECURSION_LIMIT, "configurable": {"thread_id": thread_id}}

    print(f"\n  you   -> {question}   [thread {thread_id}]\n")
    state = {"messages": [HumanMessage(content=question)]}
    # Default stream mode is "updates", so each step carries only what the node
    # just added. No need to track how much has already been printed.
    async for step in graph.astream(state, config):
        for payload in step.values():
            for message in payload.get("messages", []):
                if line := describe(message):
                    print(line)

    await close_pool()
    return 0


if __name__ == "__main__":
    use_selector_loop_on_windows()
    raise SystemExit(asyncio.run(main()))
