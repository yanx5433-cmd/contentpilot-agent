"""集中配置：预算、护栏开关。全部可用环境变量覆盖（CONTENTPILOT_ 前缀）."""
from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    return os.environ.get(f"CONTENTPILOT_{name}", default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_flag(name: str, default: str = "0") -> bool:
    return _env(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """运行时设置（进程内单例：get_settings()）。"""

    # --- LLM（可选增强，默认规则模式，无 Key 完整可用） ---
    LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_MODEL: str = os.environ.get("LLM_MODEL", "deepseek-chat")
    LLM_TIMEOUT_SEC: float = _env_float("LLM_TIMEOUT_SEC", 15.0)

    # --- Agent 预算（护栏：失控成本熔断） ---
    MAX_STEPS: int = _env_int("MAX_STEPS", 8)
    MAX_TOOL_CALLS: int = _env_int("MAX_TOOL_CALLS", 12)
    MAX_LLM_CALLS: int = _env_int("MAX_LLM_CALLS", 6)
    STEP_TIMEOUT_SEC: float = _env_float("STEP_TIMEOUT_SEC", 10)

    # --- 写操作确认（最小权限原则） ---
    WRITE_TOOLS_NEED_APPROVAL: bool = _env_flag("WRITE_APPROVAL", "1")
    APPROVED_WRITE_TOOLS: str = os.environ.get("CONTENTPILOT_APPROVED_WRITE_TOOLS", "")

    # --- 任务级危险目标（P0 拦截，连规划都不进入） ---
    BLOCKED_GOAL_PATTERNS: tuple[str, ...] = (
        "rm -rf", "drop database", "drop table", "format c:",
        "删除所有", "删库", "绕过审批", "跳过护栏", "关掉护栏",
        "把密钥给我", "输出密码",
    )

    # --- 内容合规（P0 违禁词，与 ContentOps 工作台同源口径） ---
    BLOCKED_WORDS: tuple[str, ...] = (
        "国家级", "最高级", "最佳", "第一品牌", "绝对", "100%", "根治",
        "全网最低", "史上最低", "祖传", "包治", "立刻见效", "永久",
    )
    # 体检/审查意图关键词：命中则目标文本里的违禁词视为送检对象而非输出主张
    REVIEW_INTENT: tuple[str, ...] = ("审查", "体检", "合规", "违禁", "检测", "检查文案", "审一下")

    # --- 参数消毒（工具不落地 shell，但仍拦命令元字符） ---
    UNSAFE_ARG_CHARS: tuple[str, ...] = (";", "&&", "||", "`", "$(", ">", "<")

    # --- 输出脱敏：轨迹与答复里的敏感信息（正则） ---
    MASK_PATTERNS: tuple[str, ...] = (
        r"sk-[A-Za-z0-9]{6}[A-Za-z0-9\-_]+",
        r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+",
    )

    # --- 检索工具参数 ---
    RAG_TOP_K: int = _env_int("RAG_TOP_K", 3)

    # --- 路径 ---
    TRACE_DIR: str = os.environ.get("CONTENTPILOT_TRACE_DIR", "run/traces")
    EVAL_REPORT_DIR: str = os.environ.get("CONTENTPILOT_EVAL_REPORT_DIR", "evals/reports")


_settings = Settings()


def get_settings() -> Settings:
    return _settings
