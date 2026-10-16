"""评测框架：场景用例 → 断言 Agent 行为 → 产出指标与报告.

设计原则（大厂 evals 惯例）：
- 用例是数据（JSONL），评测器是代码：新增场景不改评测器；
- 指标可复算：trajectory/answer 断言全部确定性，无 LLM-as-judge 的随机性；
- 每个用例绑定维度（routing / guardrail / quality / robustness），
  报告按维度给分，短板一目了然。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.agent import ContentPilotAgent
from app.tools.domain import build_registry


# ----------------------------------------------------------------------
# 用例加载
# ----------------------------------------------------------------------
def load_cases(cases_dir: str | Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for f in sorted(Path(cases_dir).glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        # 文件级 dimension 作为默认值，单用例可覆盖
        default_dim = data.get("dimension", "quality")
        for c in data["cases"]:
            c.setdefault("dimension", default_dim)
        cases.extend(data["cases"])
    return cases


# ----------------------------------------------------------------------
# 断言器：每种 check 一个纯函数（输入实际输出，输出是否通过+说明）
# ----------------------------------------------------------------------
def _check_status(result, expect: dict[str, Any]) -> tuple[bool, str]:
    want = expect.get("status")
    if want and result.status != want:
        return False, f"status 期望 {want}，实际 {result.status}"
    return True, ""


def _check_tools_called(result, expect: dict[str, Any]) -> tuple[bool, str]:
    want = expect.get("tools_called")
    if want:
        called = [s.tool for s in result.steps if s.status == "done"]
        missing = [t for t in want if t not in called]
        if missing:
            return False, f"应有 {want}，实际完成 {called}（缺 {missing}）"
    return True, ""


def _check_answer_contains(result, expect: dict[str, Any]) -> tuple[bool, str]:
    for kw in expect.get("answer_contains", []):
        if kw not in result.answer:
            return False, f"答案缺少关键词「{kw}」"
    return True, ""


def _check_answer_not_contains(result, expect: dict[str, Any]) -> tuple[bool, str]:
    for kw in expect.get("answer_not_contains", []):
        if kw in result.answer:
            return False, f"答案不应出现「{kw}」"
    return True, ""


def _check_trace_complete(result, expect: dict[str, Any]) -> tuple[bool, str]:
    """轨迹必须含完整链：guard → answer 必有；进入规划后则 plan 也必有。"""
    kinds = [e.type for e in result.events]
    for need in ("guard", "answer"):
        if need not in kinds:
            return False, f"轨迹缺 {need} 事件"
    # 有工具步骤却没 plan 事件，说明轨迹断了
    if result.steps and "plan" not in kinds:
        return False, "轨迹缺 plan 事件（有步骤但未记录规划）"
    return True, ""


def _check_budget_respected(result, expect: dict[str, Any]) -> tuple[bool, str]:
    b = result.budget
    if b.tool_calls_used > b.max_tool_calls:
        return False, f"工具调用 {b.tool_calls_used} 超预算 {b.max_tool_calls}"
    return True, ""


CHECKS: dict[str, Callable[..., tuple[bool, str]]] = {
    "status": _check_status,
    "tools_called": _check_tools_called,
    "answer_contains": _check_answer_contains,
    "answer_not_contains": _check_answer_not_contains,
    "trace_complete": _check_trace_complete,
    "budget_respected": _check_budget_respected,
}


# ----------------------------------------------------------------------
# 评测器
# ----------------------------------------------------------------------
@dataclass
class CaseOutcome:
    case_id: str
    dimension: str
    goal: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    latency_ms: int = 0
    tool_calls: int = 0


def run_eval(agent: ContentPilotAgent, cases: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes: list[CaseOutcome] = []
    for c in cases:
        t0 = time.perf_counter()
        result = agent.run(c["goal"])
        ms = int((time.perf_counter() - t0) * 1000)
        failures: list[str] = []
        for name, expect in c["expect"].items():
            if name in CHECKS:
                ok, why = CHECKS[name](result, {name: expect} if not isinstance(expect, dict) or name != "status" else expect)
                if not ok:
                    failures.append(why)
        outcomes.append(
            CaseOutcome(
                case_id=c["id"],
                dimension=c.get("dimension", "quality"),
                goal=c["goal"],
                passed=not failures,
                failures=failures,
                latency_ms=ms,
                tool_calls=result.budget.tool_calls_used,
            )
        )

    by_dim: dict[str, dict[str, int]] = {}
    for o in outcomes:
        d = by_dim.setdefault(o.dimension, {"total": 0, "passed": 0})
        d["total"] += 1
        if o.passed:
            d["passed"] += 1
    total = len(outcomes)
    passed = sum(1 for o in outcomes if o.passed)

    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "avg_latency_ms": round(sum(o.latency_ms for o in outcomes) / total) if total else 0,
            "by_dimension": {
                k: {**v, "rate": round(v["passed"] / v["total"], 4)} for k, v in sorted(by_dim.items())
            },
        },
        "cases": [
            {
                "id": o.case_id,
                "dimension": o.dimension,
                "goal": o.goal,
                "passed": o.passed,
                "failures": o.failures,
                "latency_ms": o.latency_ms,
                "tool_calls": o.tool_calls,
            }
            for o in outcomes
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# ContentPilot Agent 评测报告",
        "",
        f"- 用例数：{s['total']}　通过：{s['passed']}　**通过率 {s['pass_rate']:.1%}**",
        f"- 平均时延：{s['avg_latency_ms']} ms（全部离线确定性执行）",
        "",
        "## 分维度得分",
        "",
        "| 维度 | 通过/总数 | 通过率 |",
        "|---|---|---|",
    ]
    dim_names = {"routing": "意图路由", "guardrail": "护栏行为", "quality": "结果质量", "robustness": "异常鲁棒"}
    for k, v in s["by_dimension"].items():
        lines.append(f"| {dim_names.get(k, k)} | {v['passed']}/{v['total']} | {v['rate']:.1%} |")
    lines += ["", "## 用例明细", ""]
    failed = [c for c in report["cases"] if not c["passed"]]
    if failed:
        lines += ["### 失败用例", ""]
        for c in failed:
            lines.append(f"- **{c['id']}** {c['goal']}")
            for f in c["failures"]:
                lines.append(f"  - {f}")
        lines.append("")
    lines += ["### 全部用例", "", "| 用例 | 维度 | 结果 | 时延 | 工具调用 |", "|---|---|---|---|---|"]
    for c in report["cases"]:
        mark = "✅" if c["passed"] else "❌"
        lines.append(f"| {c['id']} | {c['dimension']} | {mark} | {c['latency_ms']}ms | {c['tool_calls']} |")
    return "\n".join(lines) + "\n"
