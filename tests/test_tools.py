"""工具集测试：8 个领域工具的确定性输出."""
from __future__ import annotations

import json

from app.tools import domain


class TestKbSearch:
    def test_hits_relevant_doc(self):
        out = domain.kb_search("打底裤 爆款结构")
        assert out["refs"], "应有命中"
        assert out["refs"][0]["source"].startswith("kb/")

    def test_top_k_limit(self):
        out = domain.kb_search("选题 选题 选题 完播 评论 钩子")
        assert len(out["refs"]) <= 3

    def test_snippet_present(self):
        out = domain.kb_search("钩子")
        assert "snippet" in out["refs"][0]


class TestVideoStats:
    def test_category_filter(self):
        out = domain.video_stats("打底裤")
        assert out["count"] >= 1
        assert 0 < out["avg_finish"] <= 1

    def test_fallback_all_videos(self):
        out = domain.video_stats("不存在的词xyz")
        assert out["count"] == 8  # 回退到全量演示数据


class TestAccountMetrics:
    def test_snapshot_shape(self):
        m = domain.account_metrics()
        assert m["followers"] > 0
        assert 0 < m["avg_finish"] <= 1


class TestCommentSummary:
    def test_intent_distribution(self):
        s = domain.comment_summary()
        assert s["total"] == 15
        assert sum(s["dist"].values()) == s["total"]

    def test_risk_note_on_aftersales(self):
        s = domain.comment_summary()
        assert s["dist"].get("售后诉求", 0) >= 3
        assert "售后" in s["risk_note"]


class TestProductPool:
    def test_sorted_by_low_return(self):
        out = domain.product_pool()
        rates = [p["return_rate"] for p in out["picks"]]
        assert rates == sorted(rates)
        assert len(out["picks"]) == 3

    def test_risky_flagged(self):
        out = domain.product_pool()
        assert "毛呢外套" in out["risky"]

    def test_category_filter(self):
        out = domain.product_pool("鞋靴")
        assert out["total"] == 1


class TestComplianceCheck:
    def test_p0_hit(self):
        out = domain.compliance_check("全网最低价，最佳选择")
        assert out["level"] == "P0"
        assert out["verdict"] == "拦截"
        assert out["rewrite_hint"]

    def test_p1_hit(self):
        out = domain.compliance_check("限时抢购，仅此一次")
        assert out["level"] == "P1"
        assert out["verdict"] == "人工复核"

    def test_pass(self):
        out = domain.compliance_check("3 款秋冬打底衫实测横评")
        assert out["level"] == "PASS"


class TestCalendarSlot:
    def test_best_hour(self):
        out = domain.calendar_slot()
        assert out["best_hour"] == 19

    def test_known_hour(self):
        out = domain.calendar_slot(12)
        assert out["score"] == 0.36

    def test_unknown_hour(self):
        out = domain.calendar_slot(3)
        assert out["best_hour"] is None
        assert "无历史数据" in out["note"]


class TestRegisterPublish:
    def test_appends_jsonl(self, tmp_path):
        log = tmp_path / "pub"
        r1 = domain.register_publish("标题A", _internal_trace_dir=str(log))
        r2 = domain.register_publish("标题B", _internal_trace_dir=str(log))
        lines = (log / "publish.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        rec = json.loads(lines[0])
        assert rec["operator"] == "contentpilot-agent"
        assert r1["publish_id"] != r2["publish_id"]


class TestRegistryIntegrity:
    def test_all_tools_registered(self):
        reg = domain.build_registry()
        assert set(reg.names()) == {
            "kb_search", "video_stats", "account_metrics", "comment_summary",
            "product_pool", "compliance_check", "calendar_slot", "register_publish",
        }

    def test_only_one_write_tool(self):
        reg = domain.build_registry()
        assert reg.write_tools() == ["register_publish"]

    def test_declaration_matches_signature(self):
        """注册表在 register 时已校验签名一致性——能构建即通过。"""
        domain.build_registry()
