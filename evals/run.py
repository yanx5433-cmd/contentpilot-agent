"""评测入口：python -m evals.run [--json 路径] [--md 路径].

评测全部离线：不需要 API Key，不访问网络，结果确定可复算。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import ContentPilotAgent
from app.tools.domain import build_registry
from evals.runner import load_cases, render_markdown, run_eval


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(Path(__file__).parent / "cases"))
    ap.add_argument("--json", default=str(Path(__file__).parent / "reports" / "report.json"))
    ap.add_argument("--md", default=str(Path(__file__).parent / "reports" / "report.md"))
    args = ap.parse_args()

    cases = load_cases(args.cases)
    if not cases:
        print(f"no cases found in {args.cases}", file=sys.stderr)
        return 2

    agent = ContentPilotAgent(build_registry())
    report = run_eval(agent, cases)

    out_json = Path(args.json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    out_md = Path(args.md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_markdown(report), encoding="utf-8")

    s = report["summary"]
    print(f"evals: {s['passed']}/{s['total']} passed ({s['pass_rate']:.1%}), avg {s['avg_latency_ms']}ms")
    for k, v in s["by_dimension"].items():
        print(f"  {k:<12} {v['passed']}/{v['total']} = {v['rate']:.1%}")
    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
