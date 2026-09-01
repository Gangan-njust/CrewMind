"""检索入口：混合检索 + 章节 boost + rerank"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from backend.config import settings
from backend.rag import embedder, fts_store, reranker, vector_store
from backend.rag.metrics import timed_retrieval
from backend.storage.database import get_session
from backend.storage.models import LiteratureRecord

logger = logging.getLogger(__name__)

SECTION_BOOST: dict[str, float] = {
  "abstract": 1.15,
  "methods": 1.10,
}


def _apply_section_boost(scores: dict[str, float], payloads: dict[str, dict]) -> None:
  if not settings.rag_section_boost:
    return
  for cid, hit in payloads.items():
    sk = hit.get("section_key", "")
    boost = SECTION_BOOST.get(sk, 1.0)
    if boost != 1.0:
      scores[cid] = scores.get(cid, 0.0) * boost


def _enrich_hits(workspace_id: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
  if not hits:
    return []
  lit_ids = list({h["literature_id"] for h in hits if h.get("literature_id")})
  titles: dict[str, str] = {}
  with get_session() as session:
    rows = session.scalars(
      select(LiteratureRecord).where(
        LiteratureRecord.workspace_id == workspace_id,
        LiteratureRecord.id.in_(lit_ids),
      )
    ).all()
    for row in rows:
      titles[row.id] = row.title

  enriched = []
  for h in hits:
    enriched.append({
      **h,
      "literature_title": titles.get(h.get("literature_id", ""), ""),
      "excerpt": (h.get("content") or "")[:500],
    })
  return enriched


def _rrf_merge(
  vec_hits: list[dict],
  fts_hits: list[dict],
  *,
  top_k: int,
) -> list[dict[str, Any]]:
  rrf_k = 60
  scores: dict[str, float] = {}
  payloads: dict[str, dict] = {}

  for rank, hit in enumerate(vec_hits):
    cid = hit["chunk_id"]
    scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)
    payloads[cid] = hit

  for rank, hit in enumerate(fts_hits):
    cid = hit["chunk_id"]
    scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)
    if cid not in payloads:
      payloads[cid] = hit

  _apply_section_boost(scores, payloads)

  sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
  merged = []
  for cid in sorted_ids[:top_k]:
    item = {**payloads[cid], "score": scores[cid], "source": "hybrid"}
    merged.append(item)
  return merged


def vector_search(
  workspace_id: str,
  query: str,
  *,
  top_k: int | None = None,
  literature_ids: list[str] | None = None,
  section_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
  if not settings.rag_enabled:
    return []
  k = top_k or settings.rag_top_k
  qvec = embedder.get_embedder().embed_query(query)
  hits = vector_store.search(
    workspace_id,
    qvec,
    top_k=k,
    literature_ids=literature_ids,
    section_keys=section_keys,
  )
  return _enrich_hits(workspace_id, hits)


def hybrid_search(
  workspace_id: str,
  query: str,
  *,
  top_k: int | None = None,
  literature_ids: list[str] | None = None,
  section_keys: list[str] | None = None,
  rerank: bool | None = None,
) -> list[dict[str, Any]]:
  """向量 Top-20 + FTS Top-20，RRF 融合，可选 rerank"""
  if not settings.rag_enabled:
    return []

  limit = top_k or settings.rag_top_k
  with timed_retrieval(workspace_id, query, mode="hybrid") as metrics:
    vec_hits = vector_store.search(
      workspace_id,
      embedder.get_embedder().embed_query(query),
      top_k=20,
      literature_ids=literature_ids,
      section_keys=section_keys,
    )
    fts_hits = fts_store.search(
      workspace_id,
      query,
      top_k=20,
      literature_ids=literature_ids,
      section_keys=section_keys,
    )
    merged = _rrf_merge(vec_hits, fts_hits, top_k=limit)
    metrics.candidate_count = len(merged)

    use_rerank = settings.rag_rerank_enabled if rerank is None else rerank
    if use_rerank and merged:
      final = reranker.rerank_hits(query, merged, top_k=settings.rag_rerank_top_k)
      metrics.rerank_used = True
    else:
      final = merged[: settings.rag_rerank_top_k]

    enriched = _enrich_hits(workspace_id, final)
    metrics.result_count = len(enriched)
    return enriched


def retrieve(
  workspace_id: str,
  query: str,
  *,
  literature_ids: list[str] | None = None,
  section_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
  """生产环境推荐入口：混合检索 + rerank，Top-K 由 rag_rerank_top_k 控制"""
  return hybrid_search(
    workspace_id,
    query,
    literature_ids=literature_ids,
    section_keys=section_keys,
    rerank=True,
  )


def search(
  workspace_id: str,
  query: str,
  *,
  mode: str = "hybrid",
  top_k: int | None = None,
  literature_ids: list[str] | None = None,
  section_keys: list[str] | None = None,
  rerank: bool | None = None,
) -> list[dict[str, Any]]:
  if mode == "vector":
    return vector_search(
      workspace_id, query,
      top_k=top_k,
      literature_ids=literature_ids,
      section_keys=section_keys,
    )
  return hybrid_search(
    workspace_id, query,
    top_k=top_k,
    literature_ids=literature_ids,
    section_keys=section_keys,
    rerank=rerank,
  )
