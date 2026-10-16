"""API 层测试：TestClient 全接口覆盖（离线，无需网络与 Key）."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.server import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENTPILOT_TRACE_DIR", str(tmp_path / "traces"))
    # server 在 create_app 时读一次 settings；环境变量方式对单例无效，
    # 改为直接改单例字段，测完恢复
    from app.config import get_settings

    s = get_settings()
    old = s.TRACE_DIR
    s.TRACE_DIR = str(tmp_path / "traces")
    yield TestClient(create_app())
    s.TRACE_DIR = old


class TestMeta:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_tools_listing(self, client):
        r = client.get("/api/tools")
        assert r.status_code == 200
        names = [t["name"] for t in r.json()["tools"]]
        assert "register_publish" in names
        write = next(t for t in r.json()["tools"] if t["name"] == "register_publish")
        assert write["side_effect"] is True


class TestRun:
    def test_run_topic_research(self, client):
        r = client.post("/api/run", json={"goal": "研究「开衫」的选题"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "done"
        assert body["answer"]
        assert body["steps"]
        assert body["task_id"].startswith("task_")

    def test_run_blocked_write(self, client):
        r = client.post("/api/run", json={"goal": "发布：「测试视频」"})
        assert r.status_code == 200
        assert r.json()["status"] == "blocked"

    def test_run_input_gate(self, client):
        r = client.post("/api/run", json={"goal": "第一品牌的口号"})
        assert r.status_code == 200
        assert r.json()["status"] == "blocked"

    def test_run_validation(self, client):
        r = client.post("/api/run", json={"goal": ""})
        assert r.status_code == 422

    def test_trace_endpoint(self, client):
        r = client.post("/api/run", json={"goal": "出一份周报"})
        task_id = r.json()["task_id"]
        r2 = client.get(f"/api/trace/{task_id}")
        assert r2.status_code == 200
        assert r2.json()["schema"] == "contentpilot.trace.v1"

    def test_trace_404(self, client):
        r = client.get("/api/trace/task_nonexistent")
        assert r.status_code == 404

    def test_trace_bad_id_400(self, client):
        r = client.get("/api/trace/evil_path")
        assert r.status_code == 400


class TestPreview:
    def test_plan_preview(self, client):
        r = client.post("/api/plan/preview", json={"goal": "出一份周报"})
        assert r.status_code == 200
        steps = r.json()["steps"]
        assert steps[0]["tool"] == "account_metrics"

    def test_index_served(self, client):
        r = client.get("/")
        assert r.status_code == 200
