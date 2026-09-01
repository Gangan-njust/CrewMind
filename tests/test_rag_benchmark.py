"""RAG 黄金 query 召回率与延迟基准测试"""
import json
from pathlib import Path
from unittest.mock import patch

from backend.rag.benchmark import (
  load_benchmark_fixture,
  measure_search_latency,
  recall_at_k,
  run_recall_benchmark,
  synthetic_hybrid_search,
)


def test_recall_benchmark_fixture_passes():
  fixture = load_benchmark_fixture()
  report = run_recall_benchmark(
    lambda q, chunks: synthetic_hybrid_search(q, chunks),
    fixture,
  )
  assert report["passed"], report
  assert report["average_recall"] >= 0.67


def test_hybrid_beats_vector_on_keyword_case():
  fixture = load_benchmark_fixture()
  case = next(c for c in fixture["cases"] if c["id"] == "fts_keyword")
  chunks = case["chunks"]
  query = case["query"]
  expected = case["expected_chunk_ids"]

  hybrid = synthetic_hybrid_search(query, chunks)
  # 纯「向量」mock：无关键词则随机顺序
  vector_only = [{**c, "score": 0.1} for c in chunks]

  assert recall_at_k(hybrid, expected, k=3) >= recall_at_k(vector_only, expected, k=3)


def test_latency_100_chunks_under_threshold():
  fixture = load_benchmark_fixture()
  n = fixture["latency"]["chunk_count"]
  chunks = [
    {
      "chunk_id": f"c{i}",
      "literature_id": "l1",
      "section_key": "methods",
      "content": f"测试内容 chunk {i} 交叉验证",
    }
    for i in range(n)
  ]
  lat = measure_search_latency(
    lambda: synthetic_hybrid_search("交叉验证", chunks),
    iterations=fixture["latency"]["iterations"],
  )
  assert lat["p95_ms"] <= fixture["latency"]["max_ms_p95"]


def test_analysis_helpers_fallback_without_rag():
  from backend.rag.analysis_helpers import build_literature_analysis_context

  with patch("backend.rag.analysis_helpers.settings") as mock_settings:
    mock_settings.rag_enabled = False
    text, used = build_literature_analysis_context(
      "ws", "lit", "Title", "Abstract", "Full text content here.",
    )
  assert not used
  assert "Full text" in text
