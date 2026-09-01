"""Chroma 向量存储，按 workspace 隔离 collection"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from backend.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None


def _collection_name(workspace_id: str) -> str:
  return f"ws_{workspace_id}"


def _get_client() -> chromadb.ClientAPI:
  global _client
  if _client is None:
    persist_dir = (PROJECT_ROOT / settings.rag_dir / "chroma").resolve()
    persist_dir.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(
      path=str(persist_dir),
      settings=ChromaSettings(anonymized_telemetry=False),
    )
    logger.info("Chroma 持久化目录: %s", persist_dir)
  return _client


def _get_collection(workspace_id: str):
  return _get_client().get_or_create_collection(
    name=_collection_name(workspace_id),
    metadata={"hnsw:space": "cosine"},
  )


def upsert_chunks(
  workspace_id: str,
  chunk_ids: list[str],
  embeddings: list[list[float]],
  documents: list[str],
  metadatas: list[dict[str, Any]],
) -> None:
  if not chunk_ids:
    return
  col = _get_collection(workspace_id)
  col.upsert(
    ids=chunk_ids,
    embeddings=embeddings,
    documents=documents,
    metadatas=metadatas,
  )


def delete_chunks(workspace_id: str, chunk_ids: list[str]) -> None:
  if not chunk_ids:
    return
  col = _get_collection(workspace_id)
  col.delete(ids=chunk_ids)


def delete_literature_chunks(workspace_id: str, literature_id: str) -> None:
  col = _get_collection(workspace_id)
  col.delete(where={"literature_id": literature_id})


def delete_workspace_collection(workspace_id: str) -> None:
  name = _collection_name(workspace_id)
  try:
    _get_client().delete_collection(name)
  except Exception:
    pass


def search(
  workspace_id: str,
  query_embedding: list[float],
  *,
  top_k: int = 8,
  literature_ids: list[str] | None = None,
  section_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
  col = _get_collection(workspace_id)
  where: dict[str, Any] | None = None
  if literature_ids:
    where = {"literature_id": {"$in": literature_ids}}
  if section_keys:
    sk_filter = {"section_key": {"$in": section_keys}}
    where = sk_filter if where is None else {"$and": [where, sk_filter]}

  result = col.query(
    query_embeddings=[query_embedding],
    n_results=top_k,
    where=where,
    include=["documents", "metadatas", "distances"],
  )

  hits: list[dict[str, Any]] = []
  ids = result.get("ids", [[]])[0]
  docs = result.get("documents", [[]])[0]
  metas = result.get("metadatas", [[]])[0]
  dists = result.get("distances", [[]])[0]
  for i, cid in enumerate(ids):
    meta = metas[i] or {}
    hits.append({
      "chunk_id": cid,
      "literature_id": meta.get("literature_id", ""),
      "section_key": meta.get("section_key", ""),
      "chunk_index": meta.get("chunk_index", 0),
      "content": docs[i] or "",
      "score": 1.0 - (dists[i] if dists else 0.0),
      "source": "vector",
    })
  return hits
