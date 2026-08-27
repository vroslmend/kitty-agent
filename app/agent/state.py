"""What the graph carries between nodes."""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # add_messages appends, and it appends the message objects themselves.
    # Gemini 3 attaches a thought signature to every tool call and rejects the
    # following turn with a 4xx if it does not come back untouched. Rebuilding
    # this list, or copying messages into fresh objects to tidy them for the UI,
    # drops the signature and breaks tool calling in a way that looks like a
    # model problem. Read from it freely; never reconstruct it.
    messages: Annotated[list, add_messages]
