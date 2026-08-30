"""A stand-in for the chat model.

The suite must never call an API, but the interrupt path only exists in the
gap between two model turns, so the tests need something that plays a scripted
sequence of replies. `bind_tools` returns self because the graph binds tools to
whatever it is given and then invokes it.
"""

from langchain_core.messages import AIMessage


class ScriptedModel:
    def __init__(self, *replies: AIMessage) -> None:
        self.replies = list(replies)
        self.seen: list[list] = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        self.seen.append(messages)
        return self.replies.pop(0) if self.replies else AIMessage(content="nothing scripted")


def clarification_call(question: str, options: list[str]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "ask_clarification",
                "args": {"question": question, "options": options},
                "id": "clarify_1",
            }
        ],
    )


class FailingModel:
    """Raises instead of answering, to exercise the stream's error branches."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        raise self.error


class ResourceExhausted(Exception):
    """Named to match what the provider raises, since that is all we can match on."""
