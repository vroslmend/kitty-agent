"""Mechanical routing scores and aggregate reporting."""

import re
from collections import Counter

from app.content import content, pages, site
from evals.models import CategorySummary, EvalCase, EvalResult, EvalSummary, TokenUsage

# A path in an answer, whether it came out as markdown or bare.
_PATH = re.compile(r"\]\((/[^\s)]*)\)|(?<![\w/([])(/[a-z0-9][a-z0-9/-]*)")


def known_routes() -> set[str]:
    routes = {"/"} | {page["route"] for page in pages()}
    routes |= {
        project["links"]["live"] for project in content()["projects"] if "live" in project["links"]
    }
    routes |= {value for value in site()["links"].values() if value.startswith("/")}
    return routes


def invented_links(answer: str) -> list[str]:
    """Site paths in an answer that are not real routes.

    A judge cannot check this and kept passing it. The widget renders a path as
    a working link, so a guessed one is a visitor clicking into a dead page.
    """
    known = known_routes()
    found = {match[0] or match[1] for match in _PATH.findall(answer)}
    return sorted(
        path for path in found if path and path.rstrip("/") not in {r.rstrip("/") for r in known}
    )


def route_passes(case: EvalCase, actual_tools: list[str]) -> bool:
    """Compare tool calls as multisets, so duplicate calls remain visible failures."""
    expected = Counter(case.expected_tools)
    actual = Counter(actual_tools)
    if case.allow_extra_tools:
        return all(actual[name] >= count for name, count in expected.items())
    return actual == expected


def summarize(results: list[EvalResult]) -> EvalSummary:
    categories: dict[str, CategorySummary] = {}
    for result in results:
        category = categories.setdefault(result.category, CategorySummary())
        if result.skipped_reason:
            category.skipped += 1
            continue

        category.executed += 1
        if result.route_passed:
            category.routing_passed += 1
        if result.judge:
            category.judged += 1
            if result.judge.passed:
                category.answer_passed += 1

    for category in categories.values():
        if category.executed:
            category.routing_accuracy = category.routing_passed / category.executed
        if category.judged:
            category.answer_accuracy = category.answer_passed / category.judged

    executed = sum(category.executed for category in categories.values())
    skipped = sum(category.skipped for category in categories.values())
    routing_passed = sum(category.routing_passed for category in categories.values())
    judged = sum(category.judged for category in categories.values())
    answer_passed = sum(category.answer_passed for category in categories.values())
    agent_usage = TokenUsage(
        input_tokens=sum(result.agent_usage.input_tokens for result in results),
        output_tokens=sum(result.agent_usage.output_tokens for result in results),
        total_tokens=sum(result.agent_usage.total_tokens for result in results),
    )
    judge_usage = TokenUsage(
        input_tokens=sum(result.judge_usage.input_tokens for result in results),
        output_tokens=sum(result.judge_usage.output_tokens for result in results),
        total_tokens=sum(result.judge_usage.total_tokens for result in results),
    )
    return EvalSummary(
        total=len(results),
        executed=executed,
        skipped=skipped,
        routing_passed=routing_passed,
        routing_accuracy=routing_passed / executed if executed else None,
        judged=judged,
        answer_passed=answer_passed,
        answer_accuracy=answer_passed / judged if judged else None,
        agent_usage=agent_usage,
        judge_usage=judge_usage,
        categories=categories,
    )
