"""Run and score kitty's golden question set.

Examples:

    python -m evals.run --no-judge
    python -m evals.run --judge --case write-02
    python -m evals.run --category route.search_writing --repetitions 3
"""

import argparse
import asyncio
import json
import re
import sys
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import RECURSION_LIMIT, build_graph
from app.config import get_settings
from app.db import close_pool, use_selector_loop_on_windows
from evals.judge import AnswerJudge
from evals.models import (
    Clarification,
    EvalCase,
    EvalResult,
    EvalSummary,
    Exchange,
    TokenUsage,
    ToolCall,
)
from evals.scoring import invented_links, route_passes, summarize

DEFAULT_DATASET = Path(__file__).with_name("dataset.jsonl")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("results")


def load_cases(path: Path = DEFAULT_DATASET) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            case = EvalCase.model_validate_json(raw)
        except Exception as error:
            raise ValueError(f"{path}:{line_number}: invalid case: {error}") from error
        if case.id in seen:
            raise ValueError(f"{path}:{line_number}: duplicate case id {case.id!r}")
        seen.add(case.id)
        cases.append(case)
    return cases


def select_cases(
    cases: Iterable[EvalCase], *, ids: set[str] | None = None, categories: set[str] | None = None
) -> list[EvalCase]:
    selected = [
        case
        for case in cases
        if (not ids or case.id in ids) and (not categories or case.category in categories)
    ]
    if ids:
        missing = ids - {case.id for case in selected}
        if missing:
            raise ValueError(f"unknown case id(s): {', '.join(sorted(missing))}")
    if not selected:
        raise ValueError("no cases matched the requested filters")
    return selected


def _usage_from_runs(usage_by_run: dict[str, dict]) -> TokenUsage:
    usage = TokenUsage()
    for item in usage_by_run.values():
        usage.input_tokens += int(item.get("input_tokens", 0) or 0)
        usage.output_tokens += int(item.get("output_tokens", 0) or 0)
        usage.total_tokens += int(item.get("total_tokens", 0) or 0)
    return usage


def _judge_answer(result: EvalResult) -> str:
    parts = [result.answer] if result.answer else []
    if result.clarification:
        parts.append(
            f"Question: {result.clarification.text}\n"
            f"Options: {', '.join(result.clarification.options)}"
        )
    return "\n\n".join(parts)


async def evaluate_case(graph, case: EvalCase, repetition: int = 1) -> EvalResult:
    started = time.perf_counter()
    actual_tools: list[str] = []
    earlier_turns: list[Exchange] = []
    tool_calls: list[ToolCall] = []
    answer_chunks: list[str] = []
    usage_by_run: dict[str, dict] = {}
    clarification = None
    error_message = None
    config = {
        "recursion_limit": RECURSION_LIMIT,
        "configurable": {"thread_id": f"eval-{case.id}-{uuid.uuid4()}"},
    }

    try:
        # Only the last turn is graded. The rest are there so the model has
        # something to be terse about, which is what these cases are testing.
        # Its own replies are kept: a tic is only visible against them, and the
        # judge cannot see a repetition it was never shown.
        for earlier in case.context:
            state = await graph.ainvoke({"messages": [HumanMessage(content=earlier)]}, config)
            reply = state["messages"][-1]
            earlier_turns.append(
                Exchange(visitor=earlier, kitty=str(getattr(reply, "text", "") or ""))
            )

        async for event in graph.astream_events(
            {"messages": [HumanMessage(content=case.question)]}, config
        ):
            kind = event["event"]
            if kind == "on_tool_start":
                actual_tools.append(event["name"])
                tool_calls.append(ToolCall(name=event["name"], input=event["data"].get("input")))
            elif kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if text := getattr(chunk, "text", ""):
                    answer_chunks.append(str(text))
                if usage := getattr(chunk, "usage_metadata", None):
                    usage_by_run[str(event.get("run_id", "model"))] = dict(usage)
            elif kind == "on_chat_model_end":
                output = event["data"].get("output")
                if usage := getattr(output, "usage_metadata", None):
                    usage_by_run[str(event.get("run_id", "model"))] = dict(usage)

        state = await graph.aget_state(config)
        if state.interrupts:
            pending = state.interrupts[0].value
            clarification = Clarification(
                text=pending["question"], options=pending.get("options", [])
            )
    except Exception as error:  # noqa: BLE001
        error_message = f"{type(error).__name__}: {error}"

    result = EvalResult(
        id=case.id,
        repetition=repetition,
        category=case.category,
        question=case.question,
        earlier_turns=earlier_turns,
        expected_tools=case.expected_tools,
        actual_tools=actual_tools,
        tool_calls=tool_calls,
        allow_extra_tools=case.allow_extra_tools,
        route_passed=route_passes(case, actual_tools) if error_message is None else False,
        answer=(answer := "".join(answer_chunks).strip()),
        invented_links=invented_links(answer),
        clarification=clarification,
        latency_ms=round((time.perf_counter() - started) * 1000),
        agent_usage=_usage_from_runs(usage_by_run),
        error=error_message,
    )
    return result


def _apply_mechanical_checks(result: EvalResult) -> None:
    """Overrule the judge on the two things it demonstrably gets wrong.

    It passed an empty answer, and it cannot know whether a site path is real.
    """
    if result.judge is None:
        return
    if result.invented_links:
        result.judge.passed = False
        result.judge.violations.append(f"invented site path(s): {', '.join(result.invented_links)}")
    if not result.answer and not result.clarification:
        result.judge.passed = False
        result.judge.violations.append("answered with nothing at all")


def skipped_result(case: EvalCase, repetition: int, reason: str) -> EvalResult:
    return EvalResult(
        id=case.id,
        repetition=repetition,
        category=case.category,
        question=case.question,
        expected_tools=case.expected_tools,
        allow_extra_tools=case.allow_extra_tools,
        skipped_reason=reason,
    )


def write_report(
    results: list[EvalResult], summary: EvalSummary, output_dir: Path, model: str
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    model_slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", model).strip("-") or "model"
    result_path = output_dir / f"{stamp}-{model_slug}.jsonl"
    summary_path = output_dir / f"{stamp}-{model_slug}.summary.json"
    result_path.write_text(
        "".join(result.model_dump_json() + "\n" for result in results), encoding="utf-8"
    )
    summary_path.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    return result_path, summary_path


def print_summary(summary: EvalSummary) -> None:
    print("\nResults")
    print(f"  executed: {summary.executed}/{summary.total} ({summary.skipped} skipped)")
    if summary.routing_accuracy is not None:
        print(
            f"  routing:  {summary.routing_passed}/{summary.executed} "
            f"({summary.routing_accuracy:.1%})"
        )
    if summary.answer_accuracy is not None:
        print(
            f"  answers:  {summary.answer_passed}/{summary.judged} ({summary.answer_accuracy:.1%})"
        )
    print(f"  tokens:   {summary.agent_usage.total_tokens} agent")
    if summary.judged:
        print(f"            {summary.judge_usage.total_tokens} judge")
    print("\nBy category")
    for name, category in sorted(summary.categories.items()):
        route = (
            f"{category.routing_passed}/{category.executed} ({category.routing_accuracy:.1%})"
            if category.routing_accuracy is not None
            else "not run"
        )
        judge = (
            f", answers {category.answer_passed}/{category.judged} ({category.answer_accuracy:.1%})"
            if category.answer_accuracy is not None
            else ""
        )
        skipped = f", {category.skipped} skipped" if category.skipped else ""
        print(f"  {name:<28} routing {route}{judge}{skipped}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.run")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--category", action="append", dest="categories")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--model", help="override LLM_MODEL for the agent")
    parser.add_argument(
        "--delay",
        type=float,
        help="seconds between cases (default: 8 without judging, 12 with judging)",
    )
    judge_group = parser.add_mutually_exclusive_group()
    judge_group.add_argument("--judge", action="store_true", help="run the answer judge")
    judge_group.add_argument(
        "--no-judge", action="store_true", help="skip the answer judge (default)"
    )
    parser.add_argument("--judge-model", help="override the model used by the answer judge")
    parser.add_argument(
        "--include-failure-path",
        action="store_true",
        help="run cases that require GitHub to be deliberately unavailable",
    )
    return parser


async def async_main(args: argparse.Namespace) -> int:
    if args.repetitions < 1:
        print("--repetitions must be at least 1", file=sys.stderr)
        return 2
    if args.delay is not None and args.delay < 0:
        print("--delay cannot be negative", file=sys.stderr)
        return 2
    if args.judge_model and not args.judge:
        print("--judge-model requires --judge", file=sys.stderr)
        return 2

    try:
        cases = select_cases(
            load_cases(args.dataset),
            ids=set(args.case_ids or []),
            categories=set(args.categories or []),
        )
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2

    settings = get_settings()
    if args.model:
        settings = settings.model_copy(update={"llm_model": args.model})
    if not settings.agent_ready:
        print("LLM_API_KEY is empty, so the eval cannot run.", file=sys.stderr)
        return 1
    if any("search_writing" in case.expected_tools for case in cases) and not settings.database_url:
        print("DATABASE_URL is empty, so writing-search cases cannot run.", file=sys.stderr)
        return 1

    graph = build_graph(settings, checkpointer=InMemorySaver())
    judge = AnswerJudge(settings, args.judge_model) if args.judge else None
    delay = args.delay if args.delay is not None else (12.0 if judge else 8.0)
    results: list[EvalResult] = []
    runs = [(repetition, case) for repetition in range(1, args.repetitions + 1) for case in cases]
    try:
        for position, (repetition, case) in enumerate(runs, 1):
            label = f"{case.id} [{repetition}/{args.repetitions}]"
            if case.category == "failure_path" and not args.include_failure_path:
                print(f"skip {label}: requires GitHub failure setup")
                results.append(
                    skipped_result(
                        case,
                        repetition,
                        "requires GitHub to be deliberately unavailable or rate limited",
                    )
                )
                continue

            print(f"run  {label} ({position}/{len(runs)})")
            result = await evaluate_case(graph, case, repetition)
            if judge and not result.error:
                try:
                    result.judge, result.judge_usage = await judge.judge(
                        case, _judge_answer(result), result.earlier_turns
                    )
                except Exception as error:  # noqa: BLE001
                    result.judge_error = f"{type(error).__name__}: {error}"
                _apply_mechanical_checks(result)
            results.append(result)
            if delay and position < len(runs):
                await asyncio.sleep(delay)
    finally:
        await close_pool()

    summary = summarize(results)
    result_path, summary_path = write_report(results, summary, args.output_dir, settings.llm_model)
    print_summary(summary)
    print(f"\nRaw results: {result_path}")
    print(f"Summary:     {summary_path}")
    return 1 if any(result.error or result.judge_error for result in results) else 0


def main() -> int:
    return asyncio.run(async_main(build_parser().parse_args()))


if __name__ == "__main__":
    use_selector_loop_on_windows()
    raise SystemExit(main())
