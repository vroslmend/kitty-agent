"""The agent loop.

Built by hand rather than with `create_react_agent`, because the whole point of
this project is the loop itself: the model decides, the tool node executes, the
result goes back, and it either loops or answers.
"""

from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent.prompts import build_system_prompt
from app.agent.state import AgentState
from app.agent.tools import TOOLS, ask_clarification
from app.config import Settings
from app.content import site

# A call and its result are two steps, so this is roughly four rounds of tool
# use before the graph stops itself. The endpoint is public and pays per step;
# without a ceiling a model looping on a failing tool bills until it gives up.
RECURSION_LIMIT = 10


def should_continue(state: AgentState) -> str:
    """Route on whether the model asked for a tool. This is the whole conditional
    edge: tool calls present means execute them, anything else means we are done."""
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


def build_graph(settings: Settings, checkpointer=None):
    """Compile the graph. Raises if the API key is empty, so callers must check
    `settings.agent_ready` first and fall back to napping if it is False.

    Without a checkpointer the graph still answers, it just forgets between
    turns. That is the right shape for tests, which should not need a database
    to prove the loop routes correctly.
    """
    # ask_clarification pauses the run with interrupt(), which has nowhere to
    # persist to without a checkpointer. Offering it anyway would raise the
    # first time a vague question arrived, so it disappears instead.
    tools = TOOLS if checkpointer else [t for t in TOOLS if t is not ask_clarification]

    llm = ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=settings.llm_api_key,
        max_output_tokens=settings.max_tokens_per_request,
    ).bind_tools(tools)
    system_prompt = build_system_prompt(site())

    async def agent(state: AgentState) -> dict:
        # Prepended per call rather than stored in state. Kept in state it would
        # be written into every checkpoint and prepended again on resume.
        messages = [SystemMessage(content=system_prompt), *state["messages"]]
        return {"messages": [await llm.ainvoke(messages)]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)
