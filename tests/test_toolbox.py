"""工具箱：API 配置（用户 Key 回退系统 Key）与 LLM 用量统计"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.llm.client import DeepSeekClient, set_llm_run_context
from backend.main import app
from backend.storage import api_config_store, usage_store


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  from backend.storage.database import setup_database

  setup_database()


def _auth_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
  response = client.post(
    "/api/auth/register",
    json={"username": username, "password": password},
  )
  assert response.status_code in (200, 201), response.text
  token = response.json()["token"]
  return {"Authorization": f"Bearer {token}"}


class TestUserApiConfig:
  def test_config_roundtrip(self):
    suffix = uuid.uuid4().hex[:8]
    with TestClient(app) as client:
      headers = _auth_headers(client, f"toolbox_{suffix}", "test123456")

      # 初始：未配置 → 使用系统 Key
      res = client.get("/api/toolbox/api-config", headers=headers)
      assert res.status_code == 200
      data = res.json()
      assert data["using_system_key"] is True
      assert data["has_api_key"] is False

      # 保存自定义 Key
      res = client.put(
        "/api/toolbox/api-config",
        headers=headers,
        json={
          "api_key": "sk-user-key-123",
          "base_url": "https://llm.example.com",
          "model": "custom-model",
        },
      )
      assert res.status_code == 200, res.text
      saved = res.json()
      assert saved["has_api_key"] is True
      assert saved["using_system_key"] is False
      assert saved["base_url"] == "https://llm.example.com"
      assert saved["model"] == "custom-model"

      # 再次读取保持状态
      res = client.get("/api/toolbox/api-config", headers=headers)
      assert res.json()["using_system_key"] is False

      # 清除 → 恢复系统 Key
      res = client.delete("/api/toolbox/api-config", headers=headers)
      assert res.status_code == 200
      assert res.json()["using_system_key"] is True
      res = client.get("/api/toolbox/api-config", headers=headers)
      assert res.json()["using_system_key"] is True


class TestLlmClientUserFallback:
  def test_user_config_overrides_system(self):
    user_id = str(uuid.uuid4())
    api_config_store.save_user_api_config(
      user_id, api_key="sk-own", base_url="https://own.example.com", model="own-model"
    )
    try:
      set_llm_run_context(user_id=user_id, run_id="run-1", source="workflow")
      client = DeepSeekClient()
      assert client.api_key == "sk-own"
      assert client.base_url == "https://own.example.com"
      assert client.model == "own-model"
    finally:
      api_config_store.clear_user_api_config(user_id)

  def test_fallback_to_system_when_user_unset(self, monkeypatch):
    user_id = str(uuid.uuid4())
    api_config_store.clear_user_api_config(user_id)
    monkeypatch.setattr(settings, "deepseek_api_key", "sys-key")
    monkeypatch.setattr(settings, "deepseek_base_url", "https://sys.example.com")
    monkeypatch.setattr(settings, "deepseek_model", "sys-model")
    set_llm_run_context(user_id=user_id, run_id="run-2", source="workflow")
    try:
      client = DeepSeekClient()
      assert client.api_key == "sys-key"
      assert client.base_url == "https://sys.example.com"
      assert client.model == "sys-model"
    finally:
      api_config_store.clear_user_api_config(user_id)

  def test_explicit_constructor_overrides_context(self):
    set_llm_run_context(user_id=str(uuid.uuid4()), run_id="run-3", source="workflow")
    client = DeepSeekClient(api_key="ctor-key", base_url="https://ctor.example.com", model="ctor-model")
    assert client.api_key == "ctor-key"
    assert client.base_url == "https://ctor.example.com"
    assert client.model == "ctor-model"


class TestUsageLogging:
  def test_middleware_context_flows_to_llm(self):
    """中间件注入的用户上下文必须穿透到 llm_client 的实际请求（用户 Key/BaseURL 生效）"""
    from unittest.mock import patch

    class FakeResp:
      def raise_for_status(self):
        pass

      def json(self):
        return {
          "choices": [{
            "message": {
              "content": (
                '{"name":"数据分析师","title":"统计分析与数据挖掘专家",'
                '"background":"熟悉 Python 与统计建模，擅长实验数据清洗与可视化。",'
                '"goal":"根据研究问题设计分析流程并输出可复现结论。",'
                '"tools":["rag_search","web_search"],"use_reasoning":false}'
              )
            }
          }],
          "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }

    captured: dict = {}

    async def fake_post(self, url, headers=None, json=None):
      captured["auth"] = (headers or {}).get("Authorization")
      captured["url"] = url
      return FakeResp()

    class FakeClient:
      def __init__(self, *a, **k):
        pass

      async def __aenter__(self):
        return self

      async def __aexit__(self, *a):
        return False

      post = fake_post

    suffix = uuid.uuid4().hex[:8]
    with TestClient(app) as client:
      headers = _auth_headers(client, f"ctxflow_{suffix}", "test123456")
      me = client.get("/api/auth/me", headers=headers).json()
      api_config_store.save_user_api_config(
        me["id"], api_key="sk-ctx-override", base_url="https://ctx.example.com", model="ctx-model"
      )
      try:
        with patch("backend.llm.client.httpx.AsyncClient", FakeClient):
          res = client.post(
            "/api/agents/extract",
            headers=headers,
            json={"prompt": "你是数据分析专家，负责统计与可视化"},
          )
          assert res.status_code == 200, res.text
      finally:
        api_config_store.clear_user_api_config(me["id"])

    assert captured.get("auth") == "Bearer sk-ctx-override"
    assert "https://ctx.example.com" in captured.get("url", "")

  def test_usage_logged_and_aggregated(self):
    suffix = uuid.uuid4().hex[:8]
    with TestClient(app) as client:
      headers = _auth_headers(client, f"usage_{suffix}", "test123456")
      user = client.get("/api/auth/me", headers=headers).json()
      user_id = user["id"]
      run_id = f"crew-{uuid.uuid4().hex[:8]}"

      # 模拟多次 LLM 调用
      usage_store.log_llm_usage(
        user_id=user_id,
        run_id=run_id,
        source="workflow",
        model="deepseek-chat",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=1200,
      )
      usage_store.log_llm_usage(
        user_id=user_id,
        run_id=run_id,
        source="workflow",
        model="deepseek-chat",
        prompt_tokens=200,
        completion_tokens=80,
        total_tokens=280,
        duration_ms=2300,
      )

      # 汇总
      summary = client.get("/api/toolbox/summary", headers=headers).json()
      assert summary["call_count"] == 2
      assert summary["total_tokens"] == 430
      assert summary["duration_ms"] == 3500

      # 运行记录聚合
      runs = client.get("/api/toolbox/runs", headers=headers).json()
      assert any(r["run_id"] == run_id for r in runs)
      run = next(r for r in runs if r["run_id"] == run_id)
      assert run["call_count"] == 2
      assert run["total_tokens"] == 430
      assert run["prompt_tokens"] == 300
      assert run["completion_tokens"] == 130
      assert run["duration_ms"] == 3500

      # 运行明细
      detail = client.get(f"/api/toolbox/runs/{run_id}", headers=headers).json()
      assert detail["run_id"] == run_id
      assert len(detail["calls"]) == 2

      # 调用日志
      logs = client.get("/api/toolbox/logs", headers=headers).json()
      assert any(c["run_id"] == run_id for c in logs)

      # 按来源过滤
      filtered = client.get("/api/toolbox/runs?source=writing", headers=headers).json()
      assert not any(r["run_id"] == run_id for r in filtered)

      # 清理测试数据
      usage_store._delete_for_test(user_id)

  def test_workflow_run_tracks_usage_and_user_key(self):
    """后台工作流任务必须继承用户上下文：记录 run_id 并优先使用用户 Key"""
    import time as _time
    from unittest.mock import AsyncMock, patch

    class FakeStreamResp:
      def raise_for_status(self):
        pass

      async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"完整方案内容。"}}]}'
        yield 'data: {"choices":[], "usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}'
        yield "data: [DONE]"

    captured: dict = {}

    class FakeClient:
      def __init__(self, *a, **k):
        pass

      async def __aenter__(self):
        return self

      async def __aexit__(self, *a):
        return False

      def stream(self, method, url, headers=None, json=None):
        if headers and captured.get("auth") is None:
          captured["auth"] = headers.get("Authorization")
        class CM:
          obj = FakeStreamResp()

          async def __aenter__(s):
            return s.obj

          async def __aexit__(s, *a):
            return False
        return CM()

    suffix = uuid.uuid4().hex[:8]
    with TestClient(app) as client:
      headers = _auth_headers(client, f"wfusage_{suffix}", "test123456")
      me = client.get("/api/auth/me", headers=headers).json()
      api_config_store.save_user_api_config(
        me["id"], api_key="sk-wf-key", base_url="https://wf.example.com", model="wf-model"
      )
      try:
        with patch("backend.llm.client.httpx.AsyncClient", FakeClient), patch(
          "backend.crew.engine.run_agent_tools", new=AsyncMock(return_value=[])
        ):
          res = client.post(
            "/api/workflow/start",
            headers=headers,
            json={
              "scenario": "literature_review",
              "user_input": "研究深度学习在医学影像诊断中的应用与挑战",
              "collaboration_mode": "sequential",
            },
          )
          assert res.status_code == 200, res.text
          crew_id = res.json()["crew_id"]
          for _ in range(80):
            status = client.get(f"/api/workflow/{crew_id}", headers=headers).json()["status"]
            if status in ("completed", "paused", "failed"):
              break
            _time.sleep(0.25)
      finally:
        api_config_store.clear_user_api_config(me["id"])

      # 运行记录关联到 crew_id，且带正确的用量统计
      runs = client.get("/api/toolbox/runs", headers=headers).json()
      mine = [r for r in runs if r["run_id"] == crew_id]
      assert mine, "未找到工作流运行记录"
      assert mine[0]["call_count"] >= 1
      assert mine[0]["total_tokens"] >= 1
      assert mine[0]["source"] == "workflow"

      detail = client.get(f"/api/toolbox/runs/{crew_id}", headers=headers).json()
      assert len(detail["calls"]) >= 1
      assert all(c["source"] == "workflow" for c in detail["calls"])

      # 后台任务中用户自定义 Key 生效
      assert captured.get("auth") == "Bearer sk-wf-key"

      usage_store._delete_for_test(me["id"])

  def test_unknown_run_detail_returns_404(self):
    suffix = uuid.uuid4().hex[:8]
    with TestClient(app) as client:
      headers = _auth_headers(client, f"usage404_{suffix}", "test123456")
      res = client.get("/api/toolbox/runs/nonexistent-run", headers=headers)
      assert res.status_code == 404
