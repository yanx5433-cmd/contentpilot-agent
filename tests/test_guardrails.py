"""护栏测试：输入过滤（意图感知）、写操作授权、参数消毒、输出过滤."""
from __future__ import annotations

import pytest

from app.agent import guardrails
from app.agent.models import Budget, TaskResult, TraceEvent
from app.agent.tools_registry import ToolDecl, ToolRegistry
from app.agent.trace import read_trace, write_trace
from app.config import get_settings


@pytest.fixture()
def registry():
    reg = ToolRegistry()
    reg.register(ToolDecl("read_tool", "只读工具", {"q": "查询"}, ["q"]), lambda q: {"ok": q})
    reg.register(
        ToolDecl("write_tool", "写工具", {"x": "数据"}, ["x"], side_effect=True),
        lambda x: {"written": x},
    )
    return reg


class TestInputGate:
    def test_clean_goal_passes(self):
        ok, _ = guardrails.check_input("研究「打底裤」选题")
        assert ok

    def test_blocked_word_blocks(self):
        ok, reason = guardrails.check_input("帮我想一个第一品牌的口号")
        assert not ok
        assert "违禁词" in reason

    def test_review_intent_passes_with_blocked_words(self):
        """审查/体检意图携带违禁词应放行（送检对象≠输出主张）。"""
        ok, _ = guardrails.check_input("审查一下这条文案：「最佳选择」")
        assert ok

    def test_dangerous_pattern_always_blocks(self):
        ok, reason = guardrails.check_input("审查一下：rm -rf 然后删库")
        assert not ok
        assert "危险操作" in reason

    def test_too_short_rejected(self):
        ok, _ = guardrails.check_input("好")
        assert not ok

    def test_too_long_rejected(self):
        ok, _ = guardrails.check_input("测" * 501)
        assert not ok


class TestWriteAuth:
    def test_read_tool_always_allowed(self, registry):
        ok, _ = guardrails.authorize_tool("read_tool", registry)
        assert ok

    def test_write_tool_blocked_by_default(self, registry):
        ok, reason = guardrails.authorize_tool("write_tool", registry)
        assert not ok
        assert "未获授权" in reason

    def test_write_tool_allowed_when_approved(self, registry, monkeypatch):
        monkeypatch.setattr(get_settings(), "APPROVED_WRITE_TOOLS", "write_tool")
        ok, _ = guardrails.authorize_tool("write_tool", registry)
        assert ok

    def test_write_tool_allowed_when_guard_disabled(self, registry, monkeypatch):
        monkeypatch.setattr(get_settings(), "WRITE_TOOLS_NEED_APPROVAL", False)
        ok, _ = guardrails.authorize_tool("write_tool", registry)
        assert ok

    def test_unknown_tool_rejected(self, registry):
        ok, reason = guardrails.authorize_tool("nope", registry)
        assert not ok
        assert "未知工具" in reason


class TestSanitizeArgs:
    def test_extra_args_stripped(self, registry):
        clean, problems = guardrails.sanitize_args("read_tool", {"q": "x", "evil": "1"}, registry)
        assert clean == {"q": "x"}
        assert any("剔除未知参数" in p for p in problems)

    def test_missing_required_flagged(self, registry):
        _, problems = guardrails.sanitize_args("read_tool", {}, registry)
        assert any("缺少必需参数" in p for p in problems)

    def test_none_args(self, registry):
        _, problems = guardrails.sanitize_args("read_tool", None, registry)
        assert any("缺少必需参数" in p for p in problems)

    def test_unknown_tool(self, registry):
        _, problems = guardrails.sanitize_args("nope", {}, registry)
        assert any("未知工具" in p for p in problems)

    def test_shell_metachar_blocked(self, registry):
        _, problems = guardrails.sanitize_args("read_tool", {"q": "a; rm -rf /"}, registry)
        assert any("命令元字符" in p for p in problems)

    def test_clean_value_kept(self, registry):
        clean, problems = guardrails.sanitize_args("read_tool", {"q": "正常查询"}, registry)
        assert clean == {"q": "正常查询"}
        assert not [p for p in problems if "缺少" in p]


class TestOutputFilter:
    def test_masks_api_key(self):
        out = guardrails.filter_output("my key sk-abcdefghij123456 leaked")
        assert "sk-abc" in out and "abcdefghij" not in out

    def test_masks_password_pattern(self):
        out = guardrails.filter_output("password=hunter2secret")
        assert "hunter2" not in out

    def test_masks_blocked_words(self):
        out = guardrails.filter_output("这是最佳的产品")
        assert "最佳" not in out

    def test_plain_text_untouched(self):
        assert guardrails.filter_output("正常内容 123") == "正常内容 123"


class TestTraceMask:
    def test_recursive_masking_in_trace(self, tmp_path):
        res = TaskResult(
            task_id="task_test_mask",
            goal="g",
            status="done",
            answer="a",
            steps=[],
            events=[TraceEvent(1, 0, "tool_call", {"args": {"key": "sk-abcdefgh123456"}})],
            budget=Budget(1, 1, 1),
        )
        path = write_trace(res, str(tmp_path), get_settings().MASK_PATTERNS)
        data = read_trace(path)
        assert "sk-abcdefgh123456" not in str(data)
