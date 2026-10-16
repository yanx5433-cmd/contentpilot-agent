"""JSONL 轨迹：contentpilot.trace.v1（append-only，可回放、可审计、可评测）.

设计取舍：
- 每行一个事件，进程崩了也留有部分轨迹；grep / jq / pandas 可直接读；
- 首行 header、末行 summary，读回时按 seq 校验连续性即可发现丢行；
- 脱敏在落盘前完成，敏感串绝不进磁盘。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

TRACE_SCHEMA = "contentpilot.trace.v1"

_compiled: dict[tuple[str, ...], list[re.Pattern[str]]] = {}


def mask_text(text: str, patterns: tuple[str, ...]) -> str:
    """敏感串打码，保留前 6 字符便于识别「这里曾经有个 Key」。"""
    pats = _compiled.setdefault(
        patterns, [re.compile(p) for p in patterns]
    )
    out = text
    for pat in pats:
        out = pat.sub(lambda m: m.group(0)[:6] + "****", out)
    return out


def mask_obj(obj: Any, patterns: tuple[str, ...]) -> Any:
    """递归脱敏：dict/list/str 都过一遍，防止密钥藏在 result 字段里落盘。"""
    if isinstance(obj, str):
        return mask_text(obj, patterns)
    if isinstance(obj, dict):
        return {k: mask_obj(v, patterns) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_obj(v, patterns) for v in obj]
    return obj


def write_trace(result, trace_dir: str, patterns: tuple[str, ...] = ()) -> Path:
    """写 run/traces/<task_id>.jsonl：首行 header + 逐事件行 + 末行 summary。"""
    d = Path(trace_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{result.task_id}.jsonl"

    def rec(kind: str, **kw: Any) -> dict[str, Any]:
        return {"schema": TRACE_SCHEMA, "kind": kind, **kw}

    lines: list[str] = [
        json.dumps(
            rec("header", task_id=result.task_id, goal=mask_text(result.goal, patterns), ts_ms=int(time.time() * 1000)),
            ensure_ascii=False,
        )
    ]
    seq = 0
    for e in result.events:
        seq += 1
        lines.append(
            json.dumps(
                rec("event", seq=seq, ts_ms=e.ts_ms, type=e.type, payload=mask_obj(e.payload, patterns)),
                ensure_ascii=False,
            )
        )
    lines.append(
        json.dumps(
            rec("summary", seq=seq + 1, task_id=result.task_id, status=result.status, budget=result.budget.to_dict(), blockers=result.blockers),
            ensure_ascii=False,
        )
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def read_trace(path: str | Path) -> dict[str, Any]:
    """读回轨迹：header + events + summary。seq 不连续即报错（审计可信度底线）。"""
    header: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("schema") != TRACE_SCHEMA:
            raise ValueError(f"{path}:{lineno} schema 不匹配: {r.get('schema')!r}")
        kind = r.get("kind")
        if kind == "header":
            header = r
        elif kind == "event":
            events.append(r)
        elif kind == "summary":
            summary = r
    seqs = [e["seq"] for e in events]
    if seqs != list(range(1, len(seqs) + 1)):
        raise ValueError(f"轨迹 seq 不连续，审计可信度破坏：{path}")
    return {**header, "events": events, "summary": summary}
