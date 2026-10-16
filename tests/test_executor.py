"""执行器端到端测试：全场景跑通 + 护栏行为 + 预算熔断 + 轨迹落盘."""
from __future__ import annotations

import pytest

from app.agent.executor import ContentPilotAgent
from app.agent.tools_registry import ToolDecl
from app.agent.trace import read_trace
from app.config import get_settings
from app.tools.domain import build_registry


@pytest.fixture()
def agent(tmp_path):
    return ContentPilotAgent(build_registry(), trace_dir=str(tmp_path / "traces"))


class TestEndToEnd:
    def test_topic_research_done(self, agent):
        r = agent.run("帮我研究一下「打底裤」的选题")
        assert r.status == "done"
        assert "方法论" in r.answer
        assert "数据侧" in r.answer
        assert all(s.status == "done" for s in r.steps)

    def test_weekly_report_done(self, agent):
        r = agent.run("给我出一份上周的账号周报")
        assert r.status == "done"
        assert "账号" in r.answer and "评论" in r.answer and "行动项" in r.answer

    def test_product_pick_done(self, agent):
        r = agent.run("帮我看看该挂什么商品")
        assert r.status == "done"
        assert "推荐优先挂车" in r.answer
        assert "毛呢外套" in r.answer  # 风险品提示

    def test_compliance_review_blocked_by_tool(self, agent):
        r = agent.run("帮我审查一下这条文案：「全网最低价打底衫，最佳选择，立刻见效」")
        assert r.status == "done"
        assert "P0 拦截" in r.answer
        assert "改写建议" in r.answer

    def test_compliance_review_pass(self, agent):
        r = agent.run("帮我审查一下这条文案：「3款秋冬打底衫实测」")
        assert r.status == "done"
        assert "通过" in r.answer

    def test_publish_write_blocked_without_approval(self, agent):
        r = agent.run("帮我发布这条视频：「秋冬打底裤实测」")
        assert r.status == "blocked"
        assert len(r.blockers) == 1
        assert "未获授权" in r.blockers[0]

    def test_publish_write_allowed_when_approved(self, tmp_path):
        get_settings().APPROVED_WRITE_TOOLS = "register_publish"
        try:
            agent = ContentPilotAgent(build_registry(), trace_dir=str(tmp_path / "t2"))
            r = agent.run("帮我发布这条视频：「秋冬打底裤实测」")
            assert r.status == "done"
            assert any(
                e.type == "observation"
                and e.payload.get("tool") == "register_publish"
                and e.payload["result"]["registered"]
                for e in r.events
            )
        finally:
            get_settings().APPROVED_WRITE_TOOLS = ""


class TestGuardrailBehavior:
    def test_input_gate_blocks_non_review(self, agent):
        r = agent.run("帮我想一句第一品牌的口号")
        assert r.status == "blocked"
        assert "输入护栏" in r.answer
        assert r.steps == []

    def test_answer_masks_blocked_words(self, agent):
        """答案层复检：引用违禁词时打码而非放行。"""
        r = agent.run("帮我审查一下这条文案：「最佳选择」")
        assert "最佳" not in r.answer

    def test_blocked_step_does_not_kill_others(self, agent):
        """发布场景：合规检查应完成，写操作被拦截，状态 blocked。"""
        r = agent.run("帮我发布这条视频：「秋冬打底裤实测」")
        statuses = {s.tool: s.status for s in r.steps}
        assert statuses["compliance_check"] == "done"
        assert statuses["register_publish"] == "blocked"

    def test_budget_exhaustion_skips_steps(self, tmp_path):
        agent = ContentPilotAgent(build_registry(), trace_dir=str(tmp_path / "t3"))
        old = agent.settings.MAX_TOOL_CALLS
        agent.settings.MAX_TOOL_CALLS = 0  # 压到 0，验证熔断（测完恢复，防污染全局单例）
        try:
            r = agent.run("研究「开衫」选题")
        finally:
            agent.settings.MAX_TOOL_CALLS = old
        assert any(s.status == "skipped" and "预算耗尽" in (s.error or "") for s in r.steps)


class TestTrace:
    def test_trace_written_and_replayable(self, agent, tmp_path):
        r = agent.run("研究「开衫」选题")
        files = list((tmp_path / "traces").glob("*.jsonl"))
        assert len(files) == 1
        data = read_trace(files[0])
        assert data["schema"] == "contentpilot.trace.v1"
        assert data["task_id"] == r.task_id
        assert data["summary"]["status"] == r.status
        kinds = [e["type"] for e in data["events"]]
        assert kinds[0] == "guard" and "plan" in kinds and "answer" in kinds

    def test_trace_has_full_chain(self, agent, tmp_path):
        agent.run("研究「开衫」选题")
        f = next((tmp_path / "traces").glob("*.jsonl"))
        data = read_trace(f)
        kinds = [e["type"] for e in data["events"]]
        assert "tool_call" in kinds and "observation" in kinds
        assert kinds[-1] == "answer"

    def test_seq_continuous(self, agent, tmp_path):
        """审计底线：seq 必须连续（丢行即可发现）。"""
        agent.run("研究「开衫」选题")
        f = next((tmp_path / "traces").glob("*.jsonl"))
        data = read_trace(f)  # 内部校验 seq，不抛错即通过
        assert data["events"][0]["seq"] == 1


class TestFailureIsolation:
    def test_tool_exception_isolated(self, tmp_path):
        """工具抛异常：该步 failed，依赖它的跳过，其余继续。"""
        reg = build_registry()

        def boom(query: str):
            raise RuntimeError("boom")

        # 直接替换实现（注册表不允许重复注册同名工具）
        decl, _ = reg.get("kb_search")  # type: ignore[misc]
        reg._tools["kb_search"] = (decl, boom)
        agent = ContentPilotAgent(reg, trace_dir=str(tmp_path / "t4"))
        r = agent.run("研究「开衫」选题")
        statuses = {s.tool: s.status for s in r.steps}
        assert statuses["kb_search"] == "failed"
        assert statuses["video_stats"] == "skipped"  # 依赖失败传播
        assert statuses["synthesize"] == "done"      # 综合兜底不受影响
