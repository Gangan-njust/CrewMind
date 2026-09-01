"""RAG 索引重试单元测试"""
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from backend.storage.database import get_session, setup_database
from backend.storage.models import LiteratureRecord, User, WorkspaceRecord


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  setup_database()


@pytest.fixture
def retry_literature():
  user_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  lit_id = str(uuid.uuid4())
  with get_session() as session:
    session.add(User(
      id=user_id,
      username=f"retry_{uuid.uuid4().hex[:8]}",
      password_hash="hash",
      created_at=datetime.now(),
    ))
    session.add(WorkspaceRecord(
      id=ws_id, name="重试测试", description="", user_id=user_id,
      current_selected_ids_json="[]",
      created_at=datetime.now(), updated_at=datetime.now(),
    ))
    session.add(LiteratureRecord(
      id=lit_id, workspace_id=ws_id, title="Retry Paper",
      authors_json="[]", journal="", year=2024,
      doi="", abstract="摘要",
      pdf_path="", full_text="Methods\n\nWe propose a novel approach.",
      uploaded_at=datetime.now(), status="pending",
    ))
    session.commit()
  return lit_id


def test_index_retries_on_transient_failure(retry_literature):
  lit_id = retry_literature
  call_count = 0

  def flaky_index(*args, **kwargs):
    nonlocal call_count
    call_count += 1
    if call_count < 2:
      raise RuntimeError("模拟瞬时故障")
    return {"literature_id": lit_id, "status": "done", "chunk_count": 2}

  with patch("backend.rag.indexer.settings") as mock_settings:
    mock_settings.rag_enabled = True
    mock_settings.rag_index_max_retries = 2
    with patch("backend.rag.indexer._index_literature_once", side_effect=flaky_index):
      from backend.rag.indexer import index_literature
      result = index_literature(lit_id, force=True)

  assert call_count == 2
  assert result["status"] == "done"
