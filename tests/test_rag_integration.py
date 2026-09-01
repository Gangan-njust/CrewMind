"""RAG 分析辅助与索引集成测试"""
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
def indexed_lit():
  user_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  lit_id = str(uuid.uuid4())
  with get_session() as session:
    session.add(User(
      id=user_id,
      username=f"int_{uuid.uuid4().hex[:8]}",
      password_hash="hash",
      created_at=datetime.now(),
    ))
    session.add(WorkspaceRecord(
      id=ws_id, name="集成测试", description="", user_id=user_id,
      current_selected_ids_json="[]",
      created_at=datetime.now(), updated_at=datetime.now(),
    ))
    session.add(LiteratureRecord(
      id=lit_id, workspace_id=ws_id, title="Integration Paper",
      authors_json="[]", journal="", year=2024,
      doi="", abstract="研究深度学习。",
      pdf_path="", full_text="Methods\n\nWe use cross-validation.",
      uploaded_at=datetime.now(), status="pending",
    ))
    session.commit()
  return ws_id, lit_id


@pytest.mark.asyncio
async def test_analyze_indexes_before_analyzing(indexed_lit):
  """点击「分析」时应先完成索引（无需手动索引），再基于切块结果分析"""
  ws_id, lit_id = indexed_lit

  def mock_embed(texts):
    return [[0.1] * 8 for _ in texts]

  async def stub_llm(prompt: str) -> dict:
    return {
      "contribution_summary": "贡献",
      "methods_summary": "方法",
      "key_findings": [],
      "limitations": [],
      "research_background": "",
      "research_goal": "",
      "conclusion": "",
      "innovations": [],
      "method_tags": [],
      "domain_tags": [],
      "formulas": [],
      "citations": [],
      "relevance_score": 8.0,
      "recommendation_score": 8.0,
    }

  with patch("backend.rag.indexer.embedder.get_embedder") as mock_get:
    mock_get.return_value.embed = mock_embed
    mock_get.return_value.embed_query = lambda q: [0.1] * 8
    with patch("backend.rag.indexer.vector_store.upsert_chunks"):
      with patch("backend.rag.indexer.vector_store.delete_literature_chunks"):
        with patch("backend.rag.indexer.fts_store.upsert_chunks"):
          with patch("backend.rag.indexer.fts_store.delete_by_literature"):
            with patch("backend.literature.analyzer._llm_json", side_effect=stub_llm):
              with patch(
                "backend.rag.analysis_helpers.build_literature_analysis_context",
                return_value=("Methods\n\nWe use cross-validation.", False),
              ):
                with patch("backend.rag.analysis_helpers.retrieve_multi_query", return_value=[]):
                  from backend.literature.analyzer import analyze_single_literature
                  await analyze_single_literature(lit_id)

  from backend.rag.indexer import get_index_status
  status = get_index_status(lit_id)
  assert status is not None
  assert status["status"] == "done"
  assert status["chunk_count"] > 0


def test_index_status_done_after_index(indexed_lit):
  ws_id, lit_id = indexed_lit

  def mock_embed(texts):
    return [[0.1] * 8 for _ in texts]

  with patch("backend.rag.indexer.embedder.get_embedder") as mock_get:
    mock_get.return_value.embed = mock_embed
    mock_get.return_value.embed_query = lambda q: [0.1] * 8
    with patch("backend.rag.indexer.vector_store.upsert_chunks"):
      with patch("backend.rag.indexer.vector_store.delete_literature_chunks"):
        with patch("backend.rag.indexer.fts_store.upsert_chunks"):
          with patch("backend.rag.indexer.fts_store.delete_by_literature"):
            from backend.rag.indexer import index_literature, get_index_status
            result = index_literature(lit_id, force=True)
            assert result["status"] == "done"
            status = get_index_status(lit_id)
            assert status is not None
            assert status["status"] == "done"
            assert status["chunk_count"] > 0


@pytest.mark.asyncio
async def test_analyze_uses_rag_context_when_available(indexed_lit):
  ws_id, lit_id = indexed_lit
  rag_text = "[证据 1] 来自 RAG 的方法段落关于 cross-validation"
  prompts_seen: list[str] = []

  async def capture_llm(prompt: str) -> dict:
    prompts_seen.append(prompt)
    return {
      "contribution_summary": "贡献",
      "methods_summary": "方法",
      "key_findings": [],
      "limitations": [],
      "research_background": "",
      "research_goal": "",
      "conclusion": "",
      "innovations": [],
      "method_tags": [],
      "domain_tags": [],
      "formulas": [],
      "citations": [],
      "relevance_score": 8.0,
      "recommendation_score": 8.0,
    }

  with patch(
    "backend.rag.analysis_helpers.build_literature_analysis_context",
    return_value=(rag_text, True),
  ):
    with patch("backend.literature.analyzer._llm_json", side_effect=capture_llm):
      with patch("backend.literature.analyzer._load_literature_content") as mock_load:
        mock_load.return_value = {
          "literature_id": lit_id,
          "workspace_id": ws_id,
          "title": "Test",
          "authors": [],
          "journal": "",
          "year": 2024,
          "abstract": "abs",
          "content": "full",
          "pdf_path": "",
        }
        with patch("backend.literature.analyzer._ensure_indexed", new=AsyncMock()):
          with patch("backend.rag.analysis_helpers.retrieve_multi_query", return_value=[]):
            from backend.literature.analyzer import analyze_single_literature
            await analyze_single_literature(lit_id)

  assert prompts_seen
  assert any(rag_text[:15] in p for p in prompts_seen)
