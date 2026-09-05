import json
from types import SimpleNamespace

import pytest

from evals.models import EvalCase, EvalResult, JudgeVerdict
from evals.run import evaluate_case, load_cases, select_cases, skipped_result, write_report
from evals.scoring import route_passes, summarize


def case(**updates) -> EvalCase:
    values = {
        "id": "proj-01",
        "question": "what has he built?",
        "category": "route.list_projects",
        "expected_tools": ["list_projects"],
        "allow_extra_tools": False,
        "must": ["names projects"],
        "must_not": ["invents projects"],
    }
    values.update(updates)
    return EvalCase.model_validate(values)


def result(eval_case: EvalCase, **updates) -> EvalResult:
    values = {
        "id": eval_case.id,
        "category": eval_case.category,
        "question": eval_case.question,
        "page_path": eval_case.page_path,
        "expected_tools": eval_case.expected_tools,
        "actual_tools": eval_case.expected_tools,
        "allow_extra_tools": eval_case.allow_extra_tools,
        "route_passed": True,
    }
    values.update(updates)
    return EvalResult.model_validate(values)


def test_load_cases_reads_jsonl_and_rejects_duplicate_ids(tmp_path) -> None:
    path = tmp_path / "dataset.jsonl"
    payload = case().model_dump_json()
    path.write_text(payload + "\n\n" + payload + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate case id 'proj-01'"):
        load_cases(path)


def test_select_cases_filters_and_reports_unknown_ids() -> None:
    cases = [case(), case(id="write-01", category="route.search_writing")]

    assert [item.id for item in select_cases(cases, categories={"route.search_writing"})] == [
        "write-01"
    ]
    with pytest.raises(ValueError, match="unknown case id.*missing"):
        select_cases(cases, ids={"missing"})


def test_exact_routing_rejects_extra_and_duplicate_calls() -> None:
    eval_case = case()

    assert route_passes(eval_case, ["list_projects"])
    assert not route_passes(eval_case, ["list_projects", "suggest_navigation"])
    assert not route_passes(eval_case, ["list_projects", "list_projects"])


def test_allow_extra_routing_still_requires_every_expected_call() -> None:
    eval_case = case(expected_tools=["list_projects", "suggest_navigation"], allow_extra_tools=True)

    assert route_passes(eval_case, ["search_writing", "suggest_navigation", "list_projects"])
    assert not route_passes(eval_case, ["list_projects"])


class FakeGraph:
    def __init__(self, events, interrupts=()) -> None:
        self.events = events
        self.interrupts = interrupts

    async def astream_events(self, graph_input, config):
        self.graph_input = graph_input
        self.config = config
        for event in self.events:
            yield event

    async def aget_state(self, config):
        return SimpleNamespace(interrupts=self.interrupts)


@pytest.mark.asyncio
async def test_evaluate_case_captures_tools_text_usage_and_question() -> None:
    events = [
        {
            "event": "on_tool_start",
            "name": "list_projects",
            "data": {"input": {"topics": ["python"]}},
        },
        {
            "event": "on_chat_model_stream",
            "run_id": "model-1",
            "data": {"chunk": SimpleNamespace(text="Choose one.", usage_metadata=None)},
        },
        {
            "event": "on_chat_model_end",
            "run_id": "model-1",
            "data": {
                "output": SimpleNamespace(
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 3,
                        "total_tokens": 13,
                    }
                )
            },
        },
    ]
    interrupt = SimpleNamespace(value={"question": "Which project?", "options": ["One", "Two"]})

    graph = FakeGraph(events, [interrupt])
    evaluated = await evaluate_case(graph, case(page_path="/work"))

    assert evaluated.actual_tools == ["list_projects"]
    assert evaluated.page_path == "/work"
    assert graph.graph_input["page_path"] == "/work"
    assert evaluated.question == "what has he built?"
    assert evaluated.route_passed is True
    assert evaluated.tool_calls[0].input == {"topics": ["python"]}
    assert evaluated.answer == "Choose one."
    assert evaluated.agent_usage.total_tokens == 13
    assert evaluated.clarification is not None
    assert evaluated.clarification.options == ["One", "Two"]
    assert evaluated.latency_ms >= 0


@pytest.mark.asyncio
async def test_evaluate_case_records_an_error_and_fails_routing() -> None:
    class BrokenGraph(FakeGraph):
        async def astream_events(self, graph_input, config):
            raise RuntimeError("broken")
            yield  # pragma: no cover

    evaluated = await evaluate_case(BrokenGraph([]), case())

    assert evaluated.route_passed is False
    assert evaluated.error == "RuntimeError: broken"


def test_summary_separates_routing_judging_and_skips() -> None:
    first = case()
    second = case(id="none-01", category="route.none", expected_tools=[])
    verdict = JudgeVerdict(passed=True, must_passed=["greets"], reason="passed")
    results = [
        result(first, judge=verdict),
        result(second, actual_tools=["list_projects"], route_passed=False),
        skipped_result(case(id="gh-05", category="failure_path"), 1, "needs outage"),
    ]

    summary = summarize(results)

    assert summary.total == 3
    assert summary.executed == 2
    assert summary.skipped == 1
    assert summary.routing_accuracy == 0.5
    assert summary.answer_accuracy == 1.0
    assert summary.agent_usage.total_tokens == 0
    assert summary.judge_usage.total_tokens == 0
    assert summary.categories["failure_path"].skipped == 1


def test_write_report_writes_jsonl_and_summary(tmp_path) -> None:
    eval_case = case()
    results = [result(eval_case)]
    summary = summarize(results)

    result_path, summary_path = write_report(results, summary, tmp_path, "model/name")

    assert result_path.name.endswith("-model-name.jsonl")
    assert json.loads(result_path.read_text(encoding="utf-8"))["id"] == "proj-01"
    saved_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert saved_summary["routing_accuracy"] == 1.0
