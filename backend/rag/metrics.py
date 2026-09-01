"""RAG 检索与索引监控指标"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

logger = logging.getLogger(__name__)

_fallback_count = 0


@dataclass
class RetrievalMetrics:
  workspace_id: str
  query: str
  mode: str = "hybrid"
  elapsed_ms: float = 0.0
  candidate_count: int = 0
  result_count: int = 0
  rerank_used: bool = False
  fallback: bool = False
  extra: dict = field(default_factory=dict)


def record_fallback(reason: str) -> None:
  global _fallback_count
  _fallback_count += 1
  logger.warning("RAG fallback (#%d): %s", _fallback_count, reason)


def get_fallback_count() -> int:
  return _fallback_count


def log_retrieval(metrics: RetrievalMetrics) -> None:
  logger.info(
    "RAG retrieve workspace=%s mode=%s ms=%.1f candidates=%d results=%d rerank=%s fallback=%s",
    metrics.workspace_id[:8],
    metrics.mode,
    metrics.elapsed_ms,
    metrics.candidate_count,
    metrics.result_count,
    metrics.rerank_used,
    metrics.fallback,
  )


@contextmanager
def timed_retrieval(
  workspace_id: str,
  query: str,
  *,
  mode: str = "hybrid",
) -> Iterator[RetrievalMetrics]:
  metrics = RetrievalMetrics(workspace_id=workspace_id, query=query, mode=mode)
  start = time.perf_counter()
  try:
    yield metrics
  finally:
    metrics.elapsed_ms = (time.perf_counter() - start) * 1000
    log_retrieval(metrics)
