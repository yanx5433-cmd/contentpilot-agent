"""领域工具集：带货内容运营场景的 8 个工具（7 读 + 1 写）.

全部纯函数、无网络依赖 → 天然离线可测。数据来自 data/demo/*.json。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..agent.tools_registry import ToolDecl, ToolRegistry

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "demo"


@lru_cache(maxsize=1)
def _load(name: str) -> Any:
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


# ----------------------------------------------------------------------
# 1. kb_search — 爆款方法论知识库检索（词频打分 + 来源引用）
# ----------------------------------------------------------------------
def kb_search(query: str) -> dict[str, Any]:
    kb = _load("kb_docs")
    terms = [t for t in query.replace("，", " ").replace("？", " ").split() if t]
    if not terms:
        terms = [query]
    scored: list[dict[str, Any]] = []
    for doc in kb:
        text = doc["title"] + " " + doc["text"]
        score = sum(text.count(t) for t in terms)
        if score > 0:
            snippet = doc["text"][:120]
            for t in terms:
                i = doc["text"].find(t)
                if i >= 0:
                    snippet = doc["text"][max(0, i - 20) : i + 100]
                    break
            scored.append({"source": doc["source"], "title": doc["title"], "score": score, "snippet": snippet})
    scored.sort(key=lambda x: -x["score"])
    return {"refs": scored[: get_settings().RAG_TOP_K], "query": query}


# ----------------------------------------------------------------------
# 2. video_stats — 同类目视频指标聚合
# ----------------------------------------------------------------------
def video_stats(keyword: str) -> dict[str, Any]:
    vids = _load("videos")
    kw = keyword[:4]  # 简单词干匹配
    hits = [v for v in vids if kw and (kw in v["title"] or kw in v.get("category", ""))]
    if not hits:
        hits = vids
    n = len(hits)
    return {
        "count": n,
        "avg_views": round(sum(v["views"] for v in hits) / n),
        "avg_finish": round(sum(v["finish_rate"] for v in hits) / n, 3),
        "top_title": max(hits, key=lambda v: v["views"])["title"],
    }


# ----------------------------------------------------------------------
# 3. account_metrics — 账号核心指标
# ----------------------------------------------------------------------
def account_metrics() -> dict[str, Any]:
    return _load("account")


# ----------------------------------------------------------------------
# 4. comment_summary — 评论意图分布（规则分类）
# ----------------------------------------------------------------------
_COMMENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    # 售后诉求优先级最高：提到退货/退款/投诉就是售后问题，先于质量词命中
    ("售后诉求", ("退货", "退款", "换货", "坏了", "投诉")),
    ("购买咨询", ("怎么买", "链接", "多少钱", "价格", "下单", "尺码", "有货")),
    ("质量询问", ("质量", "起球", "掉色", "面料", "会不会", "耐用")),
    ("内容反馈", ("喜欢", "好看", "支持", "加油", "爱了")),
]
_FALLBACK_INTENT = "其他"


def comment_summary() -> dict[str, Any]:
    comments = _load("comments")
    dist: dict[str, int] = {}
    for c in comments:
        label = _FALLBACK_INTENT
        for name, kws in _COMMENT_RULES:
            if any(k in c["text"] for k in kws):
                label = name
                break
        dist[label] = dist.get(label, 0) + 1
    total = len(comments)
    top_name = max(dist, key=dist.get) if dist else _FALLBACK_INTENT  # type: ignore[arg-type]
    risk = "发现售后诉求，建议优先处理" if dist.get("售后诉求", 0) >= 3 else "无显著风险"
    return {
        "total": total,
        "dist": dist,
        "top_intent": {"name": top_name, "ratio": round(dist[top_name] / total, 2) if total else 0},
        "risk_note": risk,
    }


# ----------------------------------------------------------------------
# 5. product_pool — 商品池选品候选
# ----------------------------------------------------------------------
def product_pool(category: str | None = None) -> dict[str, Any]:
    products = _load("products")
    if category:
        products = [p for p in products if category in p["category"]]
    ranked = sorted(products, key=lambda p: (p["return_rate"], -p["commission_rate"]))
    picks = [
        {"title": p["title"], "price": p["price"], "return_rate": p["return_rate"], "commission_rate": p["commission_rate"]}
        for p in ranked[:3]
    ]
    risky = [p["title"] for p in products if p["return_rate"] > 0.15]
    return {"picks": picks, "risky": risky, "total": len(products)}


# ----------------------------------------------------------------------
# 6. compliance_check — P0/P1/P2 三级合规审查（与 ContentOps 同口径）
# ----------------------------------------------------------------------
_P1_WORDS = ("秒杀", "限时", "抢购", "仅此一次")


def compliance_check(text: str) -> dict[str, Any]:
    s = get_settings()
    p0 = [w for w in s.BLOCKED_WORDS if w in text]
    if p0:
        return {
            "level": "P0",
            "hits": p0,
            "verdict": "拦截",
            "rewrite_hint": "把绝对化表述改成可验证的具体描述：用真实数据替代形容词（如「本月退货率最低的 3 款之一」，需有数据支撑）",
        }
    p1 = [w for w in _P1_WORDS if w in text]
    if p1:
        return {"level": "P1", "hits": p1, "verdict": "人工复核", "rewrite_hint": "促销紧迫感表述需真实时限，写明具体截止时间"}
    return {"level": "PASS", "hits": [], "verdict": "通过", "rewrite_hint": ""}


# ----------------------------------------------------------------------
# 7. calendar_slot — 发布时段建议
# ----------------------------------------------------------------------
def calendar_slot(hour: int | None = None) -> dict[str, Any]:
    slots = _load("calendar")
    if hour is None:
        best = max(slots, key=lambda x: x["score"])
        return {"best_hour": best["hour"], "score": best["score"], "note": best["note"], "all": slots}
    hit = next((x for x in slots if x["hour"] == hour), None)
    if hit is None:
        return {"best_hour": None, "note": f"{hour} 点无历史数据，建议避开", "all": slots}
    return {"best_hour": hit["hour"], "score": hit["score"], "note": hit["note"], "all": slots}


# ----------------------------------------------------------------------
# 8. register_publish — 写操作：登记发布记录（需授权，落 JSONL 台账）
# ----------------------------------------------------------------------
def register_publish(title: str, _internal_trace_dir: str | None = None) -> dict[str, Any]:
    """_internal_trace_dir 仅供测试注入，不进工具声明。"""
    from ..agent.models import new_id, now_ms

    d = Path(_internal_trace_dir or (Path(__file__).resolve().parents[2] / "run" / "publish_log"))
    d.mkdir(parents=True, exist_ok=True)
    rec = {"publish_id": new_id("pub"), "ts_ms": now_ms(), "title": title, "operator": "contentpilot-agent"}
    with (d / "publish.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"registered": True, "publish_id": rec["publish_id"], "title": title}


# ----------------------------------------------------------------------
# 注册表组装
# ----------------------------------------------------------------------
def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolDecl("kb_search", "检索爆款方法论知识库，返回带来源的片段", {"query": "检索词"}, ["query"]),
        kb_search,
    )
    reg.register(
        ToolDecl("video_stats", "按关键词聚合同类视频指标（播放/完播）", {"keyword": "关键词"}, ["keyword"]),
        video_stats,
    )
    reg.register(ToolDecl("account_metrics", "账号核心指标快照", {}, []), account_metrics)
    reg.register(ToolDecl("comment_summary", "评论意图分布与风险提示", {}, []), comment_summary)
    reg.register(
        ToolDecl("product_pool", "商品池选品候选（低退货优先）", {"category": "类目过滤，可空"}),  # type: ignore[arg-type]
        product_pool,
    )
    reg.register(
        ToolDecl("compliance_check", "文案 P0/P1/P2 三级合规审查", {"text": "待检文案"}, ["text"]),
        compliance_check,
    )
    reg.register(
        ToolDecl("calendar_slot", "发布时段建议（历史分值表）", {"hour": "0-23，可空"}),  # type: ignore[arg-type]
        calendar_slot,
    )
    reg.register(
        ToolDecl(
            "register_publish",
            "登记发布记录（写操作，追加 JSONL 台账）",
            {"title": "发布标题"},
            ["title"],
            side_effect=True,
        ),
        register_publish,
    )
    return reg
