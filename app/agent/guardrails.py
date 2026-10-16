"""护栏层：任务级输入过滤、写操作授权、工具参数消毒、输出合规过滤.

五道闸门（全部可独立单测）：
1. check_input      — 任务目标过滤（危险模式 P0 拦截 + 意图感知的违禁词过滤）
2. authorize_tool   — 写操作必须命中已授权清单；未授权 → blocked（而非报错崩溃）
3. sanitize_args    — 参数消毒：未知参数剔除、必需参数缺失拦截、命令元字符拦截
4. filter_output    — 答案层敏感串打码 + 违禁词复检（防自家输出二次传播）
"""
from __future__ import annotations

import re
from typing import Any

from ..config import get_settings
from .tools_registry import ToolRegistry

_MASK_RES: tuple[re.Pattern[str], ...] | None = None


def _masks() -> tuple[re.Pattern[str], ...]:
    global _MASK_RES
    if _MASK_RES is None:
        _MASK_RES = tuple(re.compile(p) for p in get_settings().MASK_PATTERNS)
    return _MASK_RES


def check_input(goal: str) -> tuple[bool, str]:
    """任务级输入过滤。返回 (ok, 原因).

    两层语义：
    - 危险模式（rm -rf / 删库…）：无论意图，一律拦截；
    - 违禁词：意图感知——「审查/体检」类目标里的违禁词是送检对象而非输出主张，
      放行进入合规工具处理（医生本人不能被疫苗误伤）。
    """
    s = get_settings()
    low = goal.lower()
    for pat in s.BLOCKED_GOAL_PATTERNS:
        if pat.lower() in low:
            return False, f"目标含危险操作「{pat}」，已拦截（P0）"
    is_review = any(k in goal for k in s.REVIEW_INTENT)
    if not is_review:
        for w in s.BLOCKED_WORDS:
            if w.lower() in low:
                return False, f"目标含违禁词「{w}」，已拦截（P0 合规）"
    if len(goal.strip()) < 2:
        return False, "目标过短，无法规划"
    if len(goal) > 500:
        return False, "目标过长（>500 字），请拆分任务"
    return True, ""


def authorize_tool(tool_name: str, registry: ToolRegistry) -> tuple[bool, str]:
    """写操作授权检查。返回 (allowed, 原因)."""
    s = get_settings()
    got = registry.get(tool_name)
    if got is None:
        return False, f"未知工具：{tool_name}"
    decl = got[0]
    if not decl.side_effect:
        return True, ""
    if not s.WRITE_TOOLS_NEED_APPROVAL:
        return True, ""
    approved = {t.strip() for t in s.APPROVED_WRITE_TOOLS.split(",") if t.strip()}
    if tool_name in approved:
        return True, ""
    return False, f"写操作「{tool_name}」未获授权（最小权限护栏），已挂起等待人工确认"


def sanitize_args(
    tool_name: str, args: dict[str, Any] | None, registry: ToolRegistry
) -> tuple[dict[str, Any], list[str]]:
    """参数消毒：剔除未知参数、校验必需参数、拦截命令元字符。返回 (干净参数, 问题列表)."""
    problems: list[str] = []
    got = registry.get(tool_name)
    if got is None:
        return {}, [f"未知工具：{tool_name}"]
    decl = got[0]
    args = dict(args or {})
    clean: dict[str, Any] = {}
    for k, v in args.items():
        if k not in decl.params:
            problems.append(f"剔除未知参数 {k!r}")
            continue
        if isinstance(v, str) and any(ch in v for ch in get_settings().UNSAFE_ARG_CHARS):
            problems.append(f"参数 {k!r} 含命令元字符，已拦截")
            continue
        clean[k] = v
    for req in decl.required:
        if req not in clean or clean[req] in (None, ""):
            problems.append(f"缺少必需参数 {req!r}")
    return clean, problems


def filter_output(text: str) -> str:
    """输出层：敏感串打码 + 违禁词复检（替换为方块，防二次传播）。"""
    s = get_settings()
    out = text
    for pat in _masks():
        out = pat.sub(lambda m: m.group(0)[:6] + "****", out)
    for w in s.BLOCKED_WORDS:
        out = out.replace(w, "□" * len(w))
    return out
