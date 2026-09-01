"""RAG 检索与 rerank 单元测试"""
from unittest.mock import patch

from backend.rag.retriever import _apply_section_boost, _rrf_merge


def test_rrf_merge_combines_vector_and_fts():
  vec = [{"chunk_id": "a", "literature_id": "l1", "section_key": "intro", "content": "vec only"}]
  fts = [{"chunk_id": "b", "literature_id": "l1", "section_key": "methods", "content": "fts only"}]
  merged = _rrf_merge(vec, fts, top_k=2)
  ids = {m["chunk_id"] for m in merged}
  assert ids == {"a", "b"}


def test_section_boost_prefers_abstract_and_methods():
  scores = {"a": 1.0, "b": 1.0}
  payloads = {
    "a": {"section_key": "introduction"},
    "b": {"section_key": "abstract"},
  }
  with patch("backend.rag.retriever.settings") as mock_settings:
    mock_settings.rag_section_boost = True
    _apply_section_boost(scores, payloads)
  assert scores["b"] > scores["a"]


def test_rerank_orders_by_score():
  hits = [
    {"chunk_id": "1", "content": "无关内容"},
    {"chunk_id": "2", "content": "深度学习分类方法"},
  ]
  with patch("backend.rag.reranker.settings") as mock_settings:
    mock_settings.rag_rerank_enabled = True
    mock_settings.rag_rerank_top_k = 2
    mock_settings.rag_rerank_model = "BAAI/bge-reranker-base"
    with patch("backend.rag.reranker._get_reranker") as mock_get:
      mock_get.return_value.rerank.return_value = [0.1, 0.9]
      from backend.rag.reranker import rerank_hits
      result = rerank_hits("深度学习", hits)
  assert result[0]["chunk_id"] == "2"
  assert result[0]["rerank_score"] == 0.9


def test_hybrid_beats_vector_on_keyword_fixture():
  """混合检索应能通过 FTS 召回纯向量难以命中的关键词"""
  query = "交叉验证"
  vec_hits = [{"chunk_id": "v1", "literature_id": "l1", "section_key": "intro", "content": "引言"}]
  fts_hits = [{"chunk_id": "f1", "literature_id": "l1", "section_key": "methods", "content": "采用五折交叉验证评估模型"}]

  merged = _rrf_merge(vec_hits, fts_hits, top_k=5)
  texts = " ".join(h["content"] for h in merged)
  assert "交叉验证" in texts

  vec_only_text = " ".join(h["content"] for h in vec_hits)
  assert "交叉验证" not in vec_only_text
