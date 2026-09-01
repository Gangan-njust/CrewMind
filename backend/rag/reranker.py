"""Cross-encoder 重排序（fastembed + bge-reranker-base）"""
from __future__ import annotations

import logging
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

_reranker_instance: Any = None


def _get_reranker():
  global _reranker_instance
  if _reranker_instance is None:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    from backend.rag.hf_hub import configure_hf_hub, format_model_download_error

    model_name = settings.rag_rerank_model
    configure_hf_hub()
    try:
      _reranker_instance = TextCrossEncoder(model_name=model_name)
    except Exception as e:
      msg = format_model_download_error(model_name, e)
      logger.error(msg)
      raise RuntimeError(msg) from e
    logger.info("已加载 rerank 模型: %s", model_name)
  return _reranker_instance


def rerank_hits(
  query: str,
  hits: list[dict[str, Any]],
  *,
  top_k: int | None = None,
) -> list[dict[str, Any]]:
  """对候选 chunk 重排序，返回 Top-K"""
  if not hits:
    return []

  limit = top_k or settings.rag_rerank_top_k
  if len(hits) <= 1:
    return hits[:limit]

  if not settings.rag_rerank_enabled:
    return hits[:limit]

  try:
    documents = [(h.get("content") or h.get("excerpt") or "")[:1500] for h in hits]
    model = _get_reranker()
    scores = list(model.rerank(query, documents))

    scored = sorted(
      zip(hits, scores),
      key=lambda x: float(x[1]),
      reverse=True,
    )
    result = []
    for hit, score in scored[:limit]:
      item = {**hit, "rerank_score": float(score), "source": "rerank"}
      result.append(item)
    return result
  except Exception as e:
    logger.warning("rerank 失败，回退 RRF 排序: %s", e)
    from backend.rag.metrics import record_fallback
    record_fallback(f"rerank: {e}")
    return hits[:limit]
