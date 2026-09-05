"""What a graph run turns into on the wire.

The events are the contract the widget is written against, so this covers the
shapes rather than the plumbing: a pause becomes a question, a tool becomes a
chip, and a failure becomes one plain sentence instead of a traceback.
"""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

import app.agent.graph as graph_module
import app.agent.stream as stream_module
from app.agent.stream import BROKEN, BUSY, EMPTY, run
from app.config import Settings
from tests.fakes import FailingModel, ResourceExhausted, ScriptedModel, clarification_call

FAKE_KEY = "not-a-real-key-nothing-here-calls-the-api"


def settings() -> Settings:
    # A url only has to be truthy: get_checkpointer is swapped out below, so
    # nothing here opens a connection.
    return Settings(llm_api_key=FAKE_KEY, database_url="postgresql://nowhere/nothing")


@pytest.fixture
def scripted(monkeypatch):
    """Install a model and an in-memory checkpointer, and clear the graph cache.

    get_graph keeps one compiled graph per process, so without the reset the
    second test in the file would run against the first test's model.
    """
    saver = InMemorySaver()
    monkeypatch.setattr(stream_module, "_graph", None)
    monkeypatch.setattr(stream_module, "_graph_key", None)

    async def checkpointer():
        return saver

    monkeypatch.setattr(stream_module, "get_checkpointer", checkpointer)

    def install(model):
        monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda **kwargs: model)
        return model

    return install


async def collect(message: str, thread_id: str, page_path: str | None = None) -> list[dict]:
    return [
        event.model_dump()
        async for event in run(message, thread_id, settings(), page_path=page_path)
    ]


async def test_a_pause_becomes_a_question_event(scripted) -> None:
    scripted(ScriptedModel(clarification_call("which one?", ["CUI Central", "Imaginify"])))

    events = await collect("the ai thing", "s1")

    assert {
        "type": "question",
        "text": "which one?",
        "options": ["CUI Central", "Imaginify"],
    } in events


async def test_the_clarification_tool_does_not_get_a_step_chip(scripted) -> None:
    # The question is the output. A chip announcing it, then the question,
    # reads as a stutter.
    scripted(ScriptedModel(clarification_call("which one?", ["a", "b"])))

    events = await collect("the ai thing", "s2")

    assert not [e for e in events if e["type"] == "step"]


async def test_a_reply_on_a_paused_thread_resumes_it(scripted) -> None:
    model = scripted(
        ScriptedModel(
            clarification_call("which one?", ["CUI Central", "Imaginify"]),
            AIMessage(content="CUI Central is a campus chatbot."),
        )
    )
    await collect("the ai thing", "s3")

    events = await collect("CUI Central", "s3")

    assert not [e for e in events if e["type"] == "question"]
    # Resumed, not restarted: the reply came back as the paused tool's result,
    # and the model was asked once more rather than handed a second question.
    assert len(model.seen) == 2
    last_turn = model.seen[-1]
    assert last_turn[-1].type == "tool"
    assert last_turn[-1].content == "CUI Central"
    assert not [m for m in last_turn if m.type == "human" and m.content == "CUI Central"]


async def test_a_normal_tool_still_gets_its_chip(scripted) -> None:
    scripted(
        ScriptedModel(
            AIMessage(
                content="",
                tool_calls=[{"name": "list_projects", "args": {}, "id": "p1"}],
            ),
            AIMessage(content="here they are"),
        )
    )

    events = await collect("what has he built", "s4")

    assert [e for e in events if e["type"] == "step"] == [
        {"type": "step", "label": "looking through the projects"}
    ]


async def test_a_known_page_is_added_to_the_system_context(scripted) -> None:
    model = scripted(ScriptedModel(AIMessage(content="the current essay")))

    await collect("what is this essay?", "page-thread", "/writing/visitor-counter")

    system_message = model.seen[0][0]
    assert "/writing/visitor-counter" in system_message.content
    assert "Trusted current-page context" in system_message.content


async def test_a_new_normal_thread_never_reads_saved_state(scripted, monkeypatch) -> None:
    scripted(ScriptedModel(AIMessage(content="hello")))
    graph = await stream_module.get_graph(settings())

    class GraphWithoutStateReads:
        def astream_events(self, *args, **kwargs):
            return graph.astream_events(*args, **kwargs)

        async def aget_state(self, config):
            raise AssertionError("a new normal turn should not read saved state")

    async def get_graph(config):
        return GraphWithoutStateReads()

    monkeypatch.setattr(stream_module, "get_graph", get_graph)

    events = [
        event.model_dump()
        async for event in run(
            "hello",
            "new-thread",
            settings(),
            check_for_resume=False,
        )
    ]

    assert events == [{"type": "token", "text": EMPTY}]


async def test_the_providers_rate_limit_reads_as_busy(scripted) -> None:
    scripted(FailingModel(ResourceExhausted("429 quota exceeded")))

    events = await collect("hello", "s5")

    assert events == [{"type": "token", "text": BUSY}]


async def test_anything_else_reads_as_broken(scripted) -> None:
    scripted(FailingModel(ValueError("something unexpected")))

    events = await collect("hello", "s6")

    assert events == [{"type": "token", "text": BROKEN}]
