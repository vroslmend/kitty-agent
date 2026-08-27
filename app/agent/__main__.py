"""Drive the graph from a terminal, before there is an API in front of it.

    ./.venv/Scripts/python.exe -m app.agent "what time is it for him?"

Prints each step as it happens, so a wrong tool choice or a loop that will not
terminate is visible rather than buried in a final answer.
"""

import asyncio
import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import RECURSION_LIMIT, build_graph
from app.config import get_settings


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
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print('usage: python -m app.agent "your question"', file=sys.stderr)
        return 2

    settings = get_settings()
    if not settings.agent_ready:
        print("LLM_API_KEY is empty, so there is no agent to drive.", file=sys.stderr)
        return 1

    graph = build_graph(settings)
    print(f"\n  you   -> {question}\n")

    state = {"messages": [HumanMessage(content=question)]}
    # Default stream mode is "updates", so each step carries only what the node
    # just added. No need to track how much has already been printed.
    async for step in graph.astream(state, {"recursion_limit": RECURSION_LIMIT}):
        for payload in step.values():
            for message in payload.get("messages", []):
                if line := describe(message):
                    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
