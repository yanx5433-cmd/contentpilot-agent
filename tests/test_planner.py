"""规划器测试：意图路由、槽位提取、拓扑排序."""
from __future__ import annotations

from app.agent.executor import ContentPilotAgent
from app.agent.models import Step
from app.agent.planner import make_plan, plan_review_text, plan_topic_research


class TestPlannerRouting:
    def test_review_text_routes(self):
        steps = make_plan("帮我审查一下这条文案：「xx」")
        assert [s.tool for s in steps] == ["compliance_check"]

    def test_topic_research_routes(self):
        steps = make_plan("研究一下「打底裤」的选题")
        assert [s.tool for s in steps] == ["kb_search", "video_stats", "synthesize"]

    def test_weekly_report_routes(self):
        steps = make_plan("给我出一份上周的周报")
        assert steps[0].tool == "account_metrics"
        assert steps[-1].tool == "synthesize"

    def test_product_pick_routes(self):
        steps = make_plan("帮我看看该挂什么商品")
        assert steps[0].tool == "product_pool"

    def test_publish_gate_routes(self):
        steps = make_plan("帮我发布这条视频：「秋冬打底裤实测」")
        assert [s.tool for s in steps] == ["compliance_check", "register_publish"]

    def test_fallback_explore(self):
        steps = make_plan("今天天气怎么样")
        assert [s.tool for s in steps] == ["kb_search", "synthesize"]

    def test_route_priority_review_over_publish(self):
        """「审查文案」与「发布」同时出现：特异性高的文案审查先命中。"""
        steps = make_plan("审查一下这条文案再发布：「测试」")
        assert steps[0].tool == "compliance_check"


class TestSlotExtraction:
    def test_extract_quoted_chinese(self):
        steps = plan_review_text("审查文案：「全网最低打底衫」")
        assert steps[0].args["text"] == "全网最低打底衫"

    def test_extract_quoted_english_quotes(self):
        steps = plan_review_text('check "great product"')
        assert steps[0].args["text"] == "great product"

    def test_no_quote_falls_back_to_goal(self):
        steps = plan_review_text("审查文案：没有引号的内容")
        assert "没有引号" in steps[0].args["text"]


class TestTopology:
    def test_all_templates_valid_dag(self):
        """所有模板产出的计划必须可拓扑排序。"""
        agent = ContentPilotAgent(registry=None)  # type: ignore[arg-type]
        goals = [
            "研究「开衫」选题",
            "出一份周报",
            "看该挂什么商品",
            "发布：「测试标题」",
            "审查文案：「无违禁词内容」",
            "随便聊聊",
        ]
        for g in goals:
            steps = agent._topo_order(make_plan(g))
            assert steps is not None, f"计划成环/悬空：{g}"

    def test_cycle_detected(self):
        a = Step(id="a", tool="kb_search", args={"query": "x"}, reason="r", depends_on=["b"])
        b = Step(id="b", tool="synthesize", args={}, reason="r", depends_on=["a"])
        agent = ContentPilotAgent(registry=None)  # type: ignore[arg-type]
        assert agent._topo_order([a, b]) is None

    def test_dangling_dependency_detected(self):
        a = Step(id="a", tool="kb_search", args={"query": "x"}, reason="r", depends_on=["ghost"])
        agent = ContentPilotAgent(registry=None)  # type: ignore[arg-type]
        assert agent._topo_order([a]) is None

    def test_dependency_wiring(self):
        steps = plan_topic_research("研究「开衫」")
        assert steps[1].depends_on == [steps[0].id]
        assert steps[2].depends_on == [steps[0].id, steps[1].id]
