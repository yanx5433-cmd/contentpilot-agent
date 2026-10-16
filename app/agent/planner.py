"""规则规划器：把自然语言目标拆成可执行步骤（确定性、可测试）.

匹配优先级：模板按特异性从高到低排列，命中即用；未命中走探索兜底。
"""
from __future__ import annotations

import re
from typing import Any

from .models import Step, new_id


def _s(tool: str, args: dict[str, Any], reason: str, depends: list[str] | None = None) -> Step:
    return Step(id=new_id("step"), tool=tool, args=args, reason=reason, depends_on=depends or [])


def _extract_quoted(goal: str) -> str | None:
    m = re.search(r"[「『\"“'](.+?)[」』\"”']", goal)
    return m.group(1).strip() if m else None


def plan_review_text(goal: str) -> list[Step]:
    """文案合规体检：审查 → 结论（含改写建议）."""
    text = _extract_quoted(goal) or goal
    return [_s("compliance_check", {"text": text}, "对文案做 P0/P1/P2 三级合规审查")]


def plan_topic_research(goal: str) -> list[Step]:
    """选题研究：知识库爆款结构 → 同类目视频指标 → 综合."""
    topic = _extract_quoted(goal) or goal
    kb = _s("kb_search", {"query": f"{topic} 爆款结构 选题"}, "检索知识库里的同类爆款结构与方法论")
    stats = _s("video_stats", {"keyword": topic}, "拉同类目视频指标，看垂类热度与完播基线", [kb.id])
    synth = _s("synthesize", {}, "综合知识库与数据，给出可执行的选题建议", [kb.id, stats.id])
    return [kb, stats, synth]


def plan_account_report(goal: str) -> list[Step]:
    """账号周报：指标 → 评论诊断 → 综合成周报."""
    metrics = _s("account_metrics", {}, "拉账号核心指标（播放/粉丝/完播/转化）")
    cm = _s("comment_summary", {}, "分析评论意图分布，找高频诉求与风险", [metrics.id])
    synth = _s("synthesize", {"format": "weekly_report"}, "综合数据与评论，输出周报（结论→数据→行动项）", [metrics.id, cm.id])
    return [metrics, cm, synth]


def plan_product_pick(goal: str) -> list[Step]:
    """选品：商品池 → 低退货优先推荐."""
    pool = _s("product_pool", {}, "拉商品池（价格带/佣金/退货率）")
    synth = _s("synthesize", {"format": "product_recommend"}, "按退货风险与佣金给挂车推荐", [pool.id])
    return [pool, synth]


def plan_publish_gate(goal: str) -> list[Step]:
    """发布门禁：文案合规 → （写）登记发布 → 输出门禁结论."""
    text = _extract_quoted(goal) or goal
    check = _s("compliance_check", {"text": text}, "发布前合规门禁：先审查文案")
    gate = _s("register_publish", {"title": text}, "合规通过后登记发布记录（写操作，需授权）", [check.id])
    return [check, gate]


def plan_explore(goal: str) -> list[Step]:
    """兜底计划：先检索再综合，保证任何目标都有合理路径."""
    kb = _s("kb_search", {"query": goal[:60]}, "检索知识库寻找相关方法与素材")
    synth = _s("synthesize", {}, "基于检索结果综合回答", [kb.id])
    return [kb, synth]


# 意图 → 模板（关键词按特异性从高到低排列）
_TEMPLATES: list[tuple[tuple[str, ...], Any]] = [
    (("违禁", "合规", "体检", "审查文案", "审查", "文案", "check"), plan_review_text),
    (("选题", "爆款", "拍什么", "topic", "研究"), plan_topic_research),
    (("周报", "复盘", "总结", "上周", "report"), plan_account_report),
    (("挂车", "选品", "卖什么", "商品", "product"), plan_product_pick),
    (("发布", "登记", "上线", "publish"), plan_publish_gate),
]


def make_plan(goal: str) -> list[Step]:
    """入口：目标 → 步骤序列。规则命中走模板，否则走探索兜底."""
    for keywords, builder in _TEMPLATES:
        if any(k in goal for k in keywords):
            return builder(goal)
    return plan_explore(goal)
