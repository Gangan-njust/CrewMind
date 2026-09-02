"""基于文献生成文献综述的端到端路由测试"""
import time as _time
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.main import app
from backend.storage.database import get_session, setup_database
from backend.storage.models import LiteratureRecord, WorkspaceRecord


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  setup_database()


def _auth_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
  response = client.post(
    "/api/auth/register",
    json={"username": username, "password": password},
  )
  assert response.status_code in (200, 201), response.text
  token = response.json()["token"]
  return {"Authorization": f"Bearer {token}"}


class _FakeStreamResp:
  def raise_for_status(self):
    pass

  async def aiter_lines(self):
    yield 'data: {"choices":[{"delta":{"content":"综述内容。"}}]}'
    yield 'data: {"choices":[], "usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}'
    yield "data: [DONE]"


class _FakeAsyncClient:
  def __init__(self, *args, **kwargs):
    pass

  async def __aenter__(self):
    return self

  async def __aexit__(self, *args):
    return False

  def stream(self, method, url, headers=None, json=None):
    class CM:
      obj = _FakeStreamResp()

      async def __aenter__(s):
        return s.obj

      async def __aexit__(s, *a):
        return False

    return CM()


def test_literature_review_route_saves_history():
  suffix = uuid.uuid4().hex[:8]
  with TestClient(app) as client:
    headers = _auth_headers(client, f"review_{suffix}", "test123456")
    me = client.get("/api/auth/me", headers=headers).json()
    user_id = me["id"]
    ws_id = str(uuid.uuid4())
    lit_id = str(uuid.uuid4())
    now = datetime.now()
    with get_session() as session:
      session.add(WorkspaceRecord(
        id=ws_id, name="综述测试库", description="", user_id=user_id,
        current_selected_ids_json="[]", created_at=now, updated_at=now,
      ))
      session.add(LiteratureRecord(
        id=lit_id, workspace_id=ws_id, title="Deep Learning Survey",
        authors_json='["Smith"]', journal="AI Review", year=2023,
        doi="10.1234/dl", abstract="Survey", pdf_path="", full_text="",
        uploaded_at=now, status="done",
      ))
      session.commit()

    try:
      with patch("backend.llm.client.httpx.AsyncClient", _FakeAsyncClient), patch(
        "backend.crew.engine.run_agent_tools", new=AsyncMock(return_value=[])
      ):
        res = client.post(
          "/api/reports/literature-review/from-literature",
          headers=headers,
          json={
            "workspace_id": ws_id,
            "literature_ids": [lit_id],
            "mode": "only_library",
            "topic": "基于深度学习的医学影像诊断综述",
            "additional_requirements": "重点梳理方法演进",
            "selected_agents": ["planner", "literature_researcher"],
          },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["scenario"] == "literature_based_review"
        crew_id = body["crew_id"]

        for _ in range(80):
          status = client.get(f"/api/workflow/{crew_id}", headers=headers).json()["status"]
          if status in ("completed", "failed"):
            break
          _time.sleep(0.25)
        assert status == "completed"

      history = client.get(
        "/api/results?scenario=literature_based_review", headers=headers
      ).json()
      review_records = [r for r in history if "基于深度学习的医学影像诊断综述" in r["title"]]
      assert review_records

      # 纯综述（scope=pure）导出应成功，且只含成文正文
      exp = client.get(
        f"/api/results/{review_records[0]['id']}/export",
        params={"format": "md", "scope": "pure"},
        headers=headers,
      )
      assert exp.status_code == 200, exp.text
      assert "综述内容" in exp.text
      assert "用户需求" not in exp.text
    finally:
      with get_session() as session:
        session.execute(delete(LiteratureRecord).where(LiteratureRecord.id == lit_id))
        session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == ws_id))
        session.commit()
