#!/usr/bin/env python3
"""RAG 召回率与检索延迟基准测试

用法:
  py -3 scripts/benchmark_rag.py
  py -3 scripts/benchmark_rag.py --workspace WS_ID   # 对真实工作空间压测（需已索引文献）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.rag.benchmark import (
  load_benchmark_fixture,
  measure_search_latency,
  run_recall_benchmark,
  synthetic_hybrid_search,
)


def main() -> int:
  parser = argparse.ArgumentParser(description="RAG 基准测试")
  parser.add_argument("--workspace", help="真实工作空间 ID（可选）")
  parser.add_argument("--query", default="研究方法 实验结果", help="真实检索 query")
  args = parser.parse_args()

  fixture = load_benchmark_fixture()
  print("=== 合成 chunk 召回率基准 ===")
  recall_report = run_recall_benchmark(
    lambda q, chunks: synthetic_hybrid_search(q, chunks),
    fixture,
  )
  print(f"Recall@{recall_report['recall_at_k']} 平均: {recall_report['average_recall']}")
  for case in recall_report["cases"]:
    status = "OK" if case["recall_at_k"] > 0 else "MISS"
    print(f"  [{status}] {case['id']}: {case['recall_at_k']} top={case['top_ids']}")

  print("\n=== 合成 100 chunk 检索延迟（内存 mock） ===")
  big_chunks = [
    {
      "chunk_id": f"perf-{i}",
      "literature_id": f"lit-{i // 10}",
      "section_key": "methods" if i % 3 == 0 else "introduction",
      "content": f"chunk {i} 关于深度学习与交叉验证的内容片段 " * 5,
    }
    for i in range(fixture["latency"]["chunk_count"])
  ]
  lat = measure_search_latency(
    lambda: synthetic_hybrid_search("交叉验证 深度学习", big_chunks),
    iterations=fixture["latency"]["iterations"],
  )
  max_p95 = fixture["latency"]["max_ms_p95"]
  ok = lat["p95_ms"] <= max_p95
  print(f"  mean={lat['mean_ms']}ms p95={lat['p95_ms']}ms max={lat['max_ms']}ms (目标 p95<{max_p95}ms)")

  if args.workspace:
    from backend.config import settings
    from backend.rag.retriever import hybrid_search, vector_search
    from backend.storage.database import setup_database

    setup_database()
    if not settings.rag_enabled:
      print("\n警告: RAG_ENABLED=false，跳过真实工作空间测试")
    else:
      print(f"\n=== 真实工作空间 {args.workspace} ===")
      real_lat = measure_search_latency(
        lambda: hybrid_search(args.workspace, args.query, rerank=False),
        iterations=10,
      )
      print(f"  hybrid mean={real_lat['mean_ms']}ms p95={real_lat['p95_ms']}ms")
      vec_lat = measure_search_latency(
        lambda: vector_search(args.workspace, args.query, top_k=8),
        iterations=10,
      )
      print(f"  vector mean={vec_lat['mean_ms']}ms p95={vec_lat['p95_ms']}ms")

  passed = recall_report["passed"] and ok
  print(f"\n{'通过' if passed else '未达标'}")
  return 0 if passed else 1


if __name__ == "__main__":
  raise SystemExit(main())
