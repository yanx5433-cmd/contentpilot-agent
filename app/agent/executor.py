"""Agent 执行器：规划 → 依赖排序执行 → 护栏 → 观察综合 → 轨迹落盘.

设计要点：
- 规划与执行分离：planner 只出计划，executor 负责推进与熔断；
- 依赖排序：拓扑序执行（Kahn），环依赖直接 fail-fast；
- 护栏先行：输入过滤 → 每步授权 + 参数消毒 → 预算熔断 → 输出过滤；
- 失败不炸全局：单步 failed 记录原因，下游步骤跳过，其余继续；
- synthesize 是内置终点步骤：把观察拼成结构化中文答复（规则模式零 LLM 依赖）。
"""
from __future__ import annotations

from typing import Any

from ..config import get_settings
from . import guardrails
from .models import Budget, Step, TaskResult, TaskStatus, TraceEvent, new_id, now_ms
from .planner import make_plan
from .tools_registry import ToolRegistry
from .trace import write_trace


class ContentPilotAgent:
    def __init__(self, registry: ToolRegistry, trace_dir: str | None = None) -> None:
        self.registry = registry
        self.settings = get_settings()
        self.trace_dir = trace_dir or self.settings.TRACE_DIR

    # ------------------------------------------------------------------
    def _emit(self, events: list[TraceEvent], etype: str, payload: dict[str, Any]) -> None:
        events.append(TraceEvent(seq=len(events) + 1, ts_ms=now_ms(), type=etype, payload=payload))

    # ------------------------------------------------------------------
    def _topo_order(self, steps: list[Step]) -> list[Step] | None:
        """Kahn 拓扑排序；返回 None 表示存在环/悬空依赖（无效计划）。"""
        by_id = {s.id: s for s in steps}
        indeg = {s.id: 0 for s in steps}
        children: dict[str, list[str]] = {s.id: [] for s in steps}
        for s in steps:
            for dep in s.depends_on:
                if dep not in by_id:
                    return None
                indeg[s.id] += 1
                children[dep].append(s.id)
        ready = [sid for sid, d in indeg.items() if d == 0]
        order: list[Step] = []
        while ready:
            sid = ready.pop(0)
            order.append(by_id[sid])
            for ch in children[sid]:
                indeg[ch] -= 1
                if indeg[ch] == 0:
                    ready.append(ch)
        return order if len(order) == len(steps) else None

    # ------------------------------------------------------------------
    def _resolve_args(self, step: Step, steps: list[Step]) -> dict[str, Any]:
        """把模板里的 $ref.field 占位符替换成上游步骤的观察值."""
        by_id = {s.id: s for s in steps}
        out: dict[str, Any] = {}
        for k, v in step.args.items():
            if isinstance(v, str) and v.startswith("$") and "." in v:
                ref, field_name = v[1:].split(".", 1)
                up = by_id.get(ref)
                obs = (up.result or {}) if up else {}
                out[k] = obs.get(field_name, v)
            else:
                out[k] = v
        return out

    # ------------------------------------------------------------------
    def _synthesize(self, steps: list[Step], goal: str) -> str:
        """规则模式综合器：按工具观察拼结论（每个分支都有测试覆盖）."""
        fmt = ""
        for s in steps:
            if s.tool == "synthesize" and isinstance(s.args, dict):
                fmt = s.args.get("format", "")
        lines: list[str] = [f"结论（目标：{goal}）"]

        for s in steps:
            if s.tool == "compliance_check" and isinstance(s.result, dict):
                lvl = s.result.get("level")
                hits = s.result.get("hits", [])
                if lvl == "P0":
                    lines.append(f"- 文案合规：P0 拦截（命中 {len(hits)} 处违禁词），不能发布")
                    rewrite = s.result.get("rewrite_hint")
                    if rewrite:
                        lines.append(f"- 改写建议：{rewrite}")
                elif lvl == "P1":
                    lines.append(f"- 文案合规：P1 人工复核（{'、'.join(hits[:5])}），可改写后发")
                else:
                    lines.append("- 文案合规：通过，无 P0/P1 风险")

            if s.tool == "kb_search" and isinstance(s.result, dict):
                refs = s.result.get("refs", [])
                if refs:
                    lines.append(f"- 方法论：命中 {len(refs)} 条素材，重点参考「{refs[0]['title']}」（{refs[0]['source']}）")
                    snippet = refs[0].get("snippet", "").strip()
                    if snippet:
                        lines.append(f"  · 要点：{snippet[:80]}")

            if s.tool == "video_stats" and isinstance(s.result, dict):
                lines.append(
                    f"- 数据侧：同类视频 {s.result.get('count', 0)} 条，"
                    f"平均完播 {s.result.get('avg_finish', 0):.0%}，平均播放 {s.result.get('avg_views', 0):,.0f}；"
                    f"历史最高播放：「{s.result.get('top_title', '-')}」"
                )

            if s.tool == "account_metrics" and isinstance(s.result, dict):
                lines.append(
                    f"- 账号：粉丝 {s.result.get('followers', 0):,}，近 7 日播放 {s.result.get('views_7d', 0):,}，"
                    f"平均完播 {s.result.get('avg_finish', 0):.0%}，30 天 GMV {s.result.get('gmv_30d', 0):,}"
                )

            if s.tool == "comment_summary" and isinstance(s.result, dict):
                top = s.result.get("top_intent", {})
                lines.append(
                    f"- 评论：共 {s.result.get('total', 0)} 条，最高频意图「{top.get('name', '-')}」占 "
                    f"{top.get('ratio', 0):.0%}；{s.result.get('risk_note', '无显著风险')}"
                )

            if s.tool == "product_pool" and isinstance(s.result, dict):
                picks = s.result.get("picks", [])
                if picks:
                    names = "、".join(
                        f"{p['title']}（退货 {p['return_rate']:.0%}/佣金 {p['commission_rate']:.0%}）" for p in picks[:2]
                    )
                    lines.append(f"- 选品：推荐优先挂车 {names}")
                risky = s.result.get("risky", [])
                if risky:
                    lines.append(f"- 风险品：{'、'.join(risky)} 退货率超 15%，暂不挂车")

            if s.tool == "calendar_slot" and isinstance(s.result, dict):
                lines.append(f"- 时段：建议 {s.result.get('best_hour', '?')} 点档发布（{s.result.get('note', '')}）")

            if s.status == "blocked":
                lines.append(f"- ⚠ 步骤「{s.tool}」被护栏拦截：{s.error}")

        if fmt == "weekly_report":
            lines.append("行动项：① 处理评论高风险项 ② 按 19 点档排期 ③ 沿用命中象限的选题结构。")
        elif fmt == "product_recommend":
            lines.append("行动项：把推荐商品挂到下一个选题的带货位，上架后回流销售数据做复盘。")
        else:
            lines.append("下一步建议：把本结论带回工作台执行；写操作已按最小权限处理。")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def run(self, goal: str) -> TaskResult:
        s = self.settings
        task_id = new_id("task")
        events: list[TraceEvent] = []
        budget = Budget(s.MAX_STEPS, s.MAX_TOOL_CALLS, s.MAX_LLM_CALLS)

        # 护栏 1：输入过滤
        ok, reason = guardrails.check_input(goal)
        if not ok:
            self._emit(events, "guard", {"gate": "input", "allowed": False, "reason": reason})
            answer = guardrails.filter_output(f"任务被输入护栏拦截：{reason}")
            self._emit(events, "answer", {"text": answer})
            res = TaskResult(task_id, goal, "blocked", answer, [], events, budget, blockers=[reason])
            write_trace(res, self.trace_dir, s.MASK_PATTERNS)
            return res
        self._emit(events, "guard", {"gate": "input", "allowed": True})

        # 规划
        steps = make_plan(goal)
        budget.steps_used = len(steps)
        self._emit(events, "plan", {"steps": [{"tool": st.tool, "reason": st.reason} for st in steps]})

        order = self._topo_order(steps)
        if order is None:
            reason = "计划存在环依赖或悬空依赖，拒绝执行（fail-fast）"
            self._emit(events, "guard", {"gate": "topology", "allowed": False, "reason": reason})
            res = TaskResult(task_id, goal, "failed", reason, steps, events, budget, blockers=[reason])
            write_trace(res, self.trace_dir, s.MASK_PATTERNS)
            return res

        # 执行
        for step in order:
            # 预算熔断
            if not budget.allow_tool():
                step.status = "skipped"
                step.error = "预算耗尽（工具调用次数），后续步骤跳过"
                self._emit(events, "guard", {"gate": "budget", "tool": step.tool, "skipped": True})
                continue

            # 内置终点步骤 synthesize 永远执行：即使上游全挂，也要输出「哪里失败、为什么」
            if step.tool == "synthesize":
                step.status = "done"
                continue

            # 依赖失败传播：上游 failed 则本步 skipped
            bad = [d for d in step.depends_on if any(
                st.id == d and st.status == "failed" for st in steps
            )]
            if bad:
                step.status = "skipped"
                step.error = f"上游步骤失败（{len(bad)} 个），跳过"
                self._emit(events, "guard", {"gate": "dependency", "tool": step.tool, "skipped": True})
                continue

            # 护栏 2：写操作授权
            allowed, why = guardrails.authorize_tool(step.tool, self.registry)
            if not allowed:
                step.status = "blocked"
                step.error = why
                self._emit(events, "guard", {"gate": "write_auth", "tool": step.tool, "allowed": False, "reason": why})
                continue

            # 护栏 3：参数消毒
            resolved = self._resolve_args(step, steps)
            clean, problems = guardrails.sanitize_args(step.tool, resolved, self.registry)
            if any("缺少必需参数" in p or "命令元字符" in p for p in problems):
                step.status = "failed"
                step.error = "；".join(problems)
                self._emit(events, "guard", {"gate": "args", "tool": step.tool, "problems": problems})
                continue
            clean = {k: v for k, v in clean.items() if not any(
                isinstance(v, str) and ch in v for ch in s.UNSAFE_ARG_CHARS
            )} or clean

            # 执行工具
            _, fn = self.registry.get(step.tool)  # type: ignore[misc]
            step.started_ms = now_ms()
            self._emit(events, "tool_call", {"step": step.id, "tool": step.tool, "args": clean})
            try:
                obs = fn(**clean)
                budget.tool_calls_used += 1
                step.result = obs
                step.status = "done"
                self._emit(events, "observation", {"step": step.id, "tool": step.tool, "result": obs})
            except Exception as exc:  # noqa: BLE001 — 工具异常不炸全局
                step.status = "failed"
                step.error = f"{type(exc).__name__}: {exc}"
                self._emit(events, "observation", {"step": step.id, "tool": step.tool, "error": step.error})
            finally:
                step.ended_ms = now_ms()

        # 状态判定：blocked > failed > done
        status: TaskStatus = "done"
        if any(st.status == "blocked" for st in steps):
            status = "blocked"
        elif steps and all(st.status == "skipped" for st in steps):
            status = "failed"

        answer_raw = self._synthesize(steps, goal)
        answer = guardrails.filter_output(answer_raw)
        self._emit(events, "answer", {"text": answer})

        res = TaskResult(
            task_id=task_id,
            goal=goal,
            status=status,
            answer=answer,
            steps=steps,
            events=events,
            budget=budget,
            blockers=[st.error for st in steps if st.status == "blocked" and st.error],
        )
        write_trace(res, self.trace_dir, s.MASK_PATTERNS)
        return res
