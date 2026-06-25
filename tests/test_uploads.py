"""上传存储与 reference_file_ids 链路"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.auth import get_user_by_username
from backend.crew.manager import WorkflowManager
from backend.main import app
from backend.storage.database import setup_database
from backend.storage.uploads import UploadStore, upload_store


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  setup_database()


def _auth_headers(client: TestClient) -> dict[str, str]:
  response = client.post(
    "/api/auth/login",
    json={"username": "admin", "password": "admin123"},
  )
  assert response.status_code == 200
  token = response.json()["token"]
  return {"Authorization": f"Bearer {token}"}


class TestUploadStore:
  def test_save_and_resolve_path(self, isolated_uploads_dir):
    store = UploadStore()
    meta = store.save(b"# Notes\ncontent", "my notes.md")

    assert meta["id"]
    assert meta["filename"] == "my_notes.md"
    assert meta["size"] == len(b"# Notes\ncontent")

    path = store.get_path(meta["id"])
    assert path is not None
    assert path.read_text(encoding="utf-8") == "# Notes\ncontent"

    resolved = store.resolve_paths([meta["id"]])
    assert len(resolved) == 1
    assert resolved[0] == str(path)

  def test_resolve_unknown_id_returns_empty(self, isolated_uploads_dir):
    assert UploadStore().resolve_paths(["nonexistent-id"]) == []

  def test_rejects_oversized_file(self, isolated_uploads_dir):
    store = UploadStore()
    with pytest.raises(ValueError, match="文件过大"):
      store.save(b"x" * (2 * 1024 * 1024 + 1), "big.txt")

  def test_rejects_unsupported_suffix(self, isolated_uploads_dir):
    store = UploadStore()
    with pytest.raises(ValueError, match="不支持的文件类型"):
      store.save(b"data", "malware.exe")

  def test_sanitize_filename(self, isolated_uploads_dir):
    meta = UploadStore().save(b"ok", "../../etc/passwd.txt")
    assert ".." not in meta["filename"]
    assert meta["filename"].endswith(".txt")


class TestUploadApiAndWorkflowChain:
  @pytest.fixture
  def client(self, isolated_uploads_dir):
    return TestClient(app)

  def test_upload_endpoint_returns_file_id(self, client):
    response = client.post(
      "/api/uploads",
      files={"file": ("reference.md", b"# Reference\nKey finding", "text/markdown")},
      headers=_auth_headers(client),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"]
    assert data["filename"] == "reference.md"
    assert data["size"] == len(b"# Reference\nKey finding")

  def test_upload_rejects_invalid_type(self, client):
    response = client.post(
      "/api/uploads",
      files={"file": ("bad.pdf", b"%PDF", "application/pdf")},
      headers=_auth_headers(client),
    )
    assert response.status_code == 400

  @pytest.mark.asyncio
  async def test_workflow_manager_resolves_reference_file_ids(self, isolated_uploads_dir):
    meta = upload_store.save(b"plan content", "plan.md")
    manager = WorkflowManager()
    admin = get_user_by_username("admin")
    assert admin is not None

    crew = await manager.start_workflow(
      scenario="literature_review",
      user_input="研究深度学习医学影像诊断的应用与挑战",
      user_id=admin.id,
      reference_file_ids=[meta["id"], "missing-id"],
    )

    assert len(crew.reference_files) == 1
    assert "plan content" in open(crew.reference_files[0], encoding="utf-8").read()

  @pytest.mark.asyncio
  async def test_reference_files_passed_to_agent_tools(self, isolated_uploads_dir):
    meta = upload_store.save(b"uploaded reference", "ref.md")
    path = upload_store.get_path(meta["id"])
    assert path is not None

    from backend.agents.roles import PLANNER
    from backend.tools.registry import run_agent_tools

    file_parser = AsyncMock()
    file_parser.run_for_files = AsyncMock(return_value="parsed content")

    with patch("backend.tools.registry.TOOL_REGISTRY", {"file_parser": file_parser}):
      messages = await run_agent_tools(
        PLANNER,
        task_prompt="规划课题",
        user_input="研究课题描述",
        context_outputs={},
        reference_files=[str(path)],
        partial_output="",
      )

    file_parser.run_for_files.assert_awaited_once_with([str(path)])
    assert messages and "参考文件内容" in messages[0]["content"]
