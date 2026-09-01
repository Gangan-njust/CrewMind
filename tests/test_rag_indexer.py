"""RAG 索引器单元测试"""
import asyncio
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.storage.database import get_session, setup_database
from backend.storage.models import LiteratureIndexStatus, LiteratureRecord, User, WorkspaceRecord


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  setup_database()


@pytest.fixture
def indexed_literature():
  user_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  lit_id = str(uuid.uuid4())
  with get_session() as session:
    session.add(User(
      id=user_id,
      username=f"raguser_{uuid.uuid4().hex[:8]}",
      password_hash="hash",
      created_at=datetime.now(),
    ))
    session.add(WorkspaceRecord(
      id=ws_id, name="RAG测试", description="", user_id=user_id,
      current_selected_ids_json="[]",
      created_at=datetime.now(), updated_at=datetime.now(),
    ))
    session.add(LiteratureRecord(
      id=lit_id, workspace_id=ws_id, title="RAG Test Paper",
      authors_json='["Author"]', journal="Journal", year=2024,
      doi="", abstract="测试摘要内容。",
      pdf_path="",
      full_text="Introduction\n\nThis is test content for RAG indexing.",
      uploaded_at=datetime.now(), status="pending",
    ))
    session.commit()
  return lit_id, ws_id


def test_indexer_skips_unchanged_content(indexed_literature):
  lit_id, _ = indexed_literature

  def mock_embed(texts):
    return [[0.1] * 8 for _ in texts]

  with patch("backend.rag.indexer.embedder.get_embedder") as mock_get:
    mock_get.return_value.embed = mock_embed
    mock_get.return_value.embed_query = lambda q: [0.1] * 8
    with patch("backend.rag.indexer.vector_store.upsert_chunks"):
      with patch("backend.rag.indexer.vector_store.delete_literature_chunks"):
        with patch("backend.rag.indexer.fts_store.upsert_chunks"):
          with patch("backend.rag.indexer.fts_store.delete_by_literature"):
            from backend.rag.indexer import index_literature

            first = index_literature(lit_id, force=True)
            assert first["status"] == "done"
            assert first["chunk_count"] > 0

            second = index_literature(lit_id, force=False)
            assert second["status"] == "done"

            from sqlalchemy import select
            with get_session() as session:
              row = session.scalar(
                select(LiteratureIndexStatus).where(
                  LiteratureIndexStatus.literature_id == lit_id
                )
              )
              assert row is not None
              assert row.content_hash


def test_schedule_index_sync_without_loop_calls_index_directly():
  from backend.rag.indexer import schedule_index_sync

  with patch("backend.rag.indexer.index_literature") as mock_index:
    schedule_index_sync("lit-1", force=True)
    mock_index.assert_called_once_with("lit-1", force=True)


@pytest.mark.asyncio
async def test_schedule_index_sync_with_loop_schedules_task():
  from backend.rag.indexer import schedule_index_sync

  with patch(
    "backend.rag.indexer.index_literature_async",
    new_callable=AsyncMock,
  ) as mock_async:
    schedule_index_sync("lit-2")
    await asyncio.sleep(0.01)
    mock_async.assert_called_once_with("lit-2", force=False)


def test_fastembed_returns_python_floats_for_chroma():
  """Chroma 不接受 list(np.float32)；embed 须产出原生 float。"""
  import numpy as np
  from unittest.mock import MagicMock, patch

  from backend.rag.embedder import FastEmbedEmbedder

  mock_model = MagicMock()
  mock_model.embed.return_value = [np.array([0.5, 1.25], dtype=np.float32)]

  with patch("fastembed.TextEmbedding", return_value=mock_model):
    with patch("backend.rag.hf_hub.configure_hf_hub"):
      emb = FastEmbedEmbedder(model_name="test-model")
      result = emb.embed(["hello"])
  assert result == [[0.5, 1.25]]
  assert all(type(x) is float for x in result[0])
