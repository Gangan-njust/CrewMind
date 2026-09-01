#!/usr/bin/env python3
"""预下载 RAG 所需的 HuggingFace 模型（embedding + rerank）

用法:
  py -3 scripts/preload_rag_models.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
  from backend.config import settings
  from backend.rag.hf_hub import configure_hf_hub

  if not settings.rag_enabled:
    print("RAG_ENABLED=false，跳过预加载")
    return 0

  configure_hf_hub()
  print(f"HF_ENDPOINT={__import__('os').environ.get('HF_ENDPOINT', '(未设置)')}")

  provider = (settings.embedding_provider or "fastembed").lower()
  if provider == "fastembed":
    print(f"下载 Embedding 模型: {settings.embedding_model} ...")
    from backend.rag.embedder import get_embedder

    get_embedder()
    print("Embedding 模型 OK")
  else:
    print(f"EMBEDDING_PROVIDER={provider}，跳过本地 embedding 下载")

  if settings.rag_rerank_enabled and provider == "fastembed":
    print(f"下载 Rerank 模型: {settings.rag_rerank_model} ...")
    try:
      from backend.rag.reranker import _get_reranker

      _get_reranker()
      print("Rerank 模型 OK")
    except Exception as e:
      print(f"Rerank 模型预加载失败（检索将回退 RRF 排序）: {e}")
      return 1

  print("全部完成")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
