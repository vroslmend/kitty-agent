"""Typed inputs and outputs for the evaluation harness."""

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    id: str
    question: str
    category: str
    expected_tools: list[str] = Field(default_factory=list)
    allow_extra_tools: bool = False
    must: list[str] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)
    notes: str = ""


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class Clarification(BaseModel):
    text: str
    options: list[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    name: str
    input: dict[str, object] | str | None = None


class JudgeVerdict(BaseModel):
    passed: bool
    must_passed: list[str] = Field(default_factory=list)
    must_failed: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    reason: str


class EvalResult(BaseModel):
    id: str
    repetition: int = 1
    category: str
    question: str
    expected_tools: list[str]
    actual_tools: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    allow_extra_tools: bool
    route_passed: bool | None = None
    answer: str = ""
    clarification: Clarification | None = None
    latency_ms: int = 0
    agent_usage: TokenUsage = Field(default_factory=TokenUsage)
    error: str | None = None
    skipped_reason: str | None = None
    judge: JudgeVerdict | None = None
    judge_usage: TokenUsage = Field(default_factory=TokenUsage)
    judge_error: str | None = None


class CategorySummary(BaseModel):
    executed: int = 0
    skipped: int = 0
    routing_passed: int = 0
    routing_accuracy: float | None = None
    judged: int = 0
    answer_passed: int = 0
    answer_accuracy: float | None = None


class EvalSummary(BaseModel):
    total: int
    executed: int
    skipped: int
    routing_passed: int
    routing_accuracy: float | None
    judged: int
    answer_passed: int
    answer_accuracy: float | None
    agent_usage: TokenUsage
    judge_usage: TokenUsage
    categories: dict[str, CategorySummary]
