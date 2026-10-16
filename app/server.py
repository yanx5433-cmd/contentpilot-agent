"""FastAPI 服务：Agent 能力的 HTTP 封装（薄层，逻辑全在 app.agent）."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import ContentPilotAgent
from .agent.trace import read_trace
from .config import get_settings
from .tools.domain import build_registry


class RunRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=500)


def create_app() -> FastAPI:
    app = FastAPI(title="ContentPilot Agent", version="0.3.0")
    agent = ContentPilotAgent(build_registry())

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.3.0"}

    @app.get("/api/tools")
    def tools() -> dict[str, Any]:
        return {
            "tools": [
                {
                    "name": d.name,
                    "description": d.description,
                    "params": d.params,
                    "required": d.required,
                    "side_effect": d.side_effect,
                }
                for d in agent.registry.decls()
            ]
        }

    @app.post("/api/run")
    def run(req: RunRequest) -> dict[str, Any]:
        result = agent.run(req.goal)
        return result.to_dict()

    @app.get("/api/trace/{task_id}")
    def trace(task_id: str) -> dict[str, Any]:
        # task_id 由服务端生成（task_<hex>），路径拼接前再校验一次
        if not task_id.startswith("task_") or "/" in task_id or "\\" in task_id or ".." in task_id:
            raise HTTPException(400, "invalid task id")
        path = Path(agent.trace_dir) / f"{task_id}.jsonl"
        if not path.exists():
            raise HTTPException(404, "trace not found")
        return read_trace(path)

    @app.post("/api/plan/preview")
    def plan_preview(req: RunRequest) -> dict[str, Any]:
        from .agent.planner import make_plan

        steps = make_plan(req.goal)
        return {"steps": [{"tool": s.tool, "args": s.args, "reason": s.reason, "depends_on": s.depends_on} for s in steps]}

    web_dir = Path(__file__).resolve().parents[1] / "web"
    web_dir.mkdir(exist_ok=True)
    app.mount("/ui", StaticFiles(directory=str(web_dir), html=True), name="ui")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    return app


app = create_app()
