"""数据模型：轨迹事件、步骤、任务结果。轨迹格式 contentpilot.trace.v1."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

StepStatus = Literal["pending", "running", "done", "blocked", "failed", "skipped"]
TaskStatus = Literal["done", "blocked", "failed"]


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class Step:
    """计划中的一步：一个工具调用（或内置综合步骤）."""

    id: str
    tool: str
    args: dict[str, Any]
    reason: str                      # 为什么做这一步（可解释性）
    depends_on: list[str] = field(default_factory=list)
    status: StepStatus = "pending"
    result: Any = None
    error: str | None = None
    started_ms: int | None = None
    ended_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TraceEvent:
    """轨迹事件：plan / tool_call / observation / guard / answer."""

    seq: int
    ts_ms: int
    type: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Budget:
    """预算计数器（护栏：超出即熔断，宁可少做也不失控）."""

    max_steps: int
    max_tool_calls: int
    max_llm_calls: int
    steps_used: int = 0
    tool_calls_used: int = 0
    llm_calls_used: int = 0

    def allow_step(self) -> bool:
        return self.steps_used < self.max_steps

    def allow_tool(self) -> bool:
        return self.tool_calls_used < self.max_tool_calls

    def allow_llm(self) -> bool:
        return self.llm_calls_used < self.max_llm_calls

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskResult:
    """一次 Agent 运行的最终交付."""

    task_id: str
    goal: str
    status: TaskStatus
    answer: str
    steps: list[Step]
    events: list[TraceEvent]
    budget: Budget
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "status": self.status,
            "answer": self.answer,
            "steps": [s.to_dict() for s in self.steps],
            "events": [e.to_dict() for e in self.events],
            "budget": self.budget.to_dict(),
            "blockers": self.blockers,
        }
