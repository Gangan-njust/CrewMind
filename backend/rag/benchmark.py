"""RAG 召回率与延迟评测"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "rag_benchmark.json"


def load_benchmark_fixture(path: Path | None = None) -> dict[str, Any]:
  p = path or FIXTURE_PATH
  with open(p, encoding="utf-8") as f:
    return json.load(f)


def recall_at_k(
  results: list[dict],
  expected_ids: list[str],
  k: int = 3,
) -> float:
  if not expected_ids:
    return 1.0
  top_ids = [r.get("chunk_id") for r in results[:k]]
  hits = sum(1 for eid in expected_ids if eid in top_ids)
  return hits / len(expected_ids)


def run_recall_benchmark(
  search_fn: Callable[[str, list[dict]], list[dict]],
  fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """search_fn(query, all_chunks) -> ranked results"""
  fixture = fixture or load_benchmark_fixture()
  k = fixture.get("recall_at_k", 3)
  case_results = []
  recalls: list[float] = []

  for case in fixture.get("cases", []):
    chunks = case["chunks"]
    query = case["query"]
    expected = case.get("expected_chunk_ids", [])
    results = search_fn(query, chunks)
    r = recall_at_k(results, expected, k=k)
    recalls.append(r)
    case_results.append({
      "id": case.get("id"),
      "query": query,
      "recall_at_k": round(r, 3),
      "top_ids": [x.get("chunk_id") for x in results[:k]],
      "expected": expected,
    })

  avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
  return {
    "recall_at_k": k,
    "average_recall": round(avg_recall, 3),
    "cases": case_results,
    "passed": avg_recall >= 0.67,
  }


def measure_search_latency(
  search_fn: Callable[[], list],
  *,
  iterations: int = 20,
) -> dict[str, float]:
  timings: list[float] = []
  for _ in range(iterations):
    start = time.perf_counter()
    search_fn()
    timings.append((time.perf_counter() - start) * 1000)
  timings.sort()
  p95_idx = max(0, int(len(timings) * 0.95) - 1)
  return {
    "iterations": iterations,
    "mean_ms": round(statistics.mean(timings), 2),
    "p95_ms": round(timings[p95_idx], 2),
    "max_ms": round(max(timings), 2),
  }


def synthetic_hybrid_search(query: str, chunks: list[dict]) -> list[dict]:
  """离线混合检索：关键词匹配 + RRF"""
  from backend.rag.retriever import _rrf_merge

  q_terms = {t for t in query.lower().split() if t}
  scored: list[tuple[float, dict]] = []
  for c in chunks:
    content = (c.get("content") or "").lower()
    score = float(sum(1 for t in q_terms if t in content))
    scored.append((score, {**c, "score": score}))

  scored.sort(key=lambda x: x[0], reverse=True)
  vec_ranked = [h for _, h in scored[:20]]
  fts_ranked = [h for s, h in scored if s > 0][:20] or vec_ranked[:20]
  return _rrf_merge(vec_ranked, fts_ranked, top_k=8)
