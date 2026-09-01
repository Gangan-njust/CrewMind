"""文献索引编排：分块、向量化、FTS、状态管理"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select

from backend.config import settings
from backend.literature.content import empty_content_error, resolve_literature_full_text
from backend.rag import chunker, embedder, fts_store, vector_store
from backend.rag.chunker import TextChunk, compute_document_hash
from backend.storage.database import get_session
from backend.storage.models import (
  LiteratureChunkRecord,
  LiteratureIndexStatus,
  LiteratureRecord,
  WorkspaceRecord,
)

logger = logging.getLogger(__name__)

_index_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
  global _index_semaphore
  if _index_semaphore is None:
    _index_semaphore = asyncio.Semaphore(settings.rag_index_concurrency)
  return _index_semaphore


def get_index_status(literature_id: str) -> dict[str, Any] | None:
  with get_session() as session:
    row = session.scalar(
      select(LiteratureIndexStatus).where(
        LiteratureIndexStatus.literature_id == literature_id
      )
    )
    if not row:
      return None
    return _serialize_status(row)


def get_workspace_stats(workspace_id: str) -> dict[str, Any]:
  with get_session() as session:
    total = session.scalar(
      select(func.count()).select_from(LiteratureRecord).where(
        LiteratureRecord.workspace_id == workspace_id
      )
    ) or 0
    indexed = session.scalar(
      select(func.count()).select_from(LiteratureIndexStatus).where(
        LiteratureIndexStatus.workspace_id == workspace_id,
        LiteratureIndexStatus.status == "done",
      )
    ) or 0
    pending = session.scalar(
      select(func.count()).select_from(LiteratureIndexStatus).where(
        LiteratureIndexStatus.workspace_id == workspace_id,
        LiteratureIndexStatus.status == "pending",
      )
    ) or 0
    indexing = session.scalar(
      select(func.count()).select_from(LiteratureIndexStatus).where(
        LiteratureIndexStatus.workspace_id == workspace_id,
        LiteratureIndexStatus.status == "indexing",
      )
    ) or 0
    failed = session.scalar(
      select(func.count()).select_from(LiteratureIndexStatus).where(
        LiteratureIndexStatus.workspace_id == workspace_id,
        LiteratureIndexStatus.status == "failed",
      )
    ) or 0
    chunk_count = session.scalar(
      select(func.count()).select_from(LiteratureChunkRecord).where(
        LiteratureChunkRecord.workspace_id == workspace_id
      )
    ) or 0
  return {
    "workspace_id": workspace_id,
    "literature_total": total,
    "indexed": indexed,
    "pending": pending,
    "indexing": indexing,
    "failed": failed,
    "chunk_count": chunk_count,
  }


def _serialize_status(row: LiteratureIndexStatus) -> dict[str, Any]:
  return {
    "literature_id": row.literature_id,
    "workspace_id": row.workspace_id,
    "status": row.status,
    "content_hash": row.content_hash,
    "chunk_count": row.chunk_count,
    "error_message": row.error_message,
    "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
    "updated_at": row.updated_at.isoformat(),
  }


def _set_status(
  literature_id: str,
  workspace_id: str,
  *,
  status: str,
  content_hash: str = "",
  chunk_count: int = 0,
  error_message: str = "",
  indexed_at: datetime | None = None,
) -> None:
  now = datetime.now()
  with get_session() as session:
    row = session.scalar(
      select(LiteratureIndexStatus).where(
        LiteratureIndexStatus.literature_id == literature_id
      )
    )
    if not row:
      row = LiteratureIndexStatus(
        id=str(uuid.uuid4()),
        literature_id=literature_id,
        workspace_id=workspace_id,
      )
      session.add(row)
    row.status = status
    if content_hash:
      row.content_hash = content_hash
    row.chunk_count = chunk_count
    row.error_message = error_message
    if indexed_at is not None:
      row.indexed_at = indexed_at
    row.updated_at = now
    session.commit()


def _load_literature(literature_id: str) -> LiteratureRecord | None:
  with get_session() as session:
    return session.get(LiteratureRecord, literature_id)


def _should_skip(literature_id: str, doc_hash: str) -> bool:
  with get_session() as session:
    row = session.scalar(
      select(LiteratureIndexStatus).where(
        LiteratureIndexStatus.literature_id == literature_id
      )
    )
    return bool(row and row.status == "done" and row.content_hash == doc_hash)


def _persist_chunks(chunks: list[TextChunk]) -> None:
  now = datetime.now()
  with get_session() as session:
    if not chunks:
      return
    lit_id = chunks[0].literature_id
    session.execute(
      delete(LiteratureChunkRecord).where(LiteratureChunkRecord.literature_id == lit_id)
    )
    for c in chunks:
      session.add(LiteratureChunkRecord(
        id=c.id,
        literature_id=c.literature_id,
        workspace_id=c.workspace_id,
        section_key=c.section_key,
        chunk_index=c.chunk_index,
        content=c.content,
        content_hash=c.content_hash,
        char_start=c.char_start,
        char_end=c.char_end,
        created_at=now,
      ))
    session.commit()


def index_literature(literature_id: str, *, force: bool = False) -> dict[str, Any]:
  """同步索引单篇文献（含失败自动重试）"""
  if not settings.rag_enabled:
    return {"literature_id": literature_id, "status": "skipped", "reason": "rag_disabled"}

  max_retries = settings.rag_index_max_retries
  last_error: Exception | None = None

  for attempt in range(max_retries + 1):
    try:
      return _index_literature_once(literature_id, force=force)
    except ValueError as e:
      # 业务错误（无文本、文献不存在）不重试
      raise
    except Exception as e:
      last_error = e
      if attempt < max_retries:
        wait = 1.5 * (attempt + 1)
        logger.warning(
          "文献索引失败，%ds 后重试 (%d/%d): %s — %s",
          wait, attempt + 1, max_retries, literature_id, e,
        )
        time.sleep(wait)
      else:
        logger.exception("文献索引最终失败: %s", literature_id)

  if last_error:
    raise last_error
  raise RuntimeError(f"索引失败: {literature_id}")


def _index_literature_once(literature_id: str, *, force: bool = False) -> dict[str, Any]:
  """单次索引尝试"""
  if not settings.rag_enabled:
    return {"literature_id": literature_id, "status": "skipped", "reason": "rag_disabled"}

  lit = _load_literature(literature_id)
  if not lit:
    raise ValueError(f"文献不存在: {literature_id}")

  full_text, pdf_err = resolve_literature_full_text(lit, persist=True)
  abstract = (lit.abstract or "").strip()
  if not full_text and not abstract:
    msg = empty_content_error(lit, pdf_err=pdf_err)
    _set_status(
      literature_id, lit.workspace_id,
      status="failed",
      error_message=msg,
    )
    return get_index_status(literature_id) or {}

  doc_hash = compute_document_hash(full_text, abstract)
  if not force and _should_skip(literature_id, doc_hash):
    logger.info("文献 %s 内容未变，跳过索引", literature_id)
    return get_index_status(literature_id) or {}

  _set_status(literature_id, lit.workspace_id, status="indexing")

  try:
    vector_store.delete_literature_chunks(lit.workspace_id, literature_id)
    fts_store.delete_by_literature(literature_id)

    chunks = chunker.chunk_literature(
      literature_id,
      lit.workspace_id,
      full_text,
      abstract,
      semantic=settings.rag_semantic_chunking,
    )
    if not chunks:
      raise ValueError("分块结果为空")

    _persist_chunks(chunks)

    emb = embedder.get_embedder()
    texts = [c.content for c in chunks]
    vectors = emb.embed(texts)

    vector_store.upsert_chunks(
      lit.workspace_id,
      [c.id for c in chunks],
      vectors,
      texts,
      [
        {
          "literature_id": c.literature_id,
          "section_key": c.section_key,
          "chunk_index": c.chunk_index,
        }
        for c in chunks
      ],
    )

    fts_store.upsert_chunks(
      [c.id for c in chunks],
      [c.literature_id for c in chunks],
      [c.workspace_id for c in chunks],
      [c.section_key for c in chunks],
      texts,
    )

    _set_status(
      literature_id,
      lit.workspace_id,
      status="done",
      content_hash=doc_hash,
      chunk_count=len(chunks),
      error_message="",
      indexed_at=datetime.now(),
    )
    logger.info("文献 %s 索引完成，共 %d 块", literature_id, len(chunks))
    return get_index_status(literature_id) or {}

  except Exception as e:
    logger.exception("文献索引失败: %s", literature_id)
    _set_status(
      literature_id,
      lit.workspace_id,
      status="failed",
      content_hash=doc_hash,
      error_message=str(e),
    )
    raise


def delete_literature_index(literature_id: str) -> None:
  lit = _load_literature(literature_id)
  workspace_id = lit.workspace_id if lit else None

  with get_session() as session:
    session.execute(
      delete(LiteratureChunkRecord).where(LiteratureChunkRecord.literature_id == literature_id)
    )
    session.execute(
      delete(LiteratureIndexStatus).where(
        LiteratureIndexStatus.literature_id == literature_id
      )
    )
    session.commit()

  fts_store.delete_by_literature(literature_id)
  if workspace_id:
    vector_store.delete_literature_chunks(workspace_id, literature_id)


def delete_workspace_index(workspace_id: str) -> None:
  with get_session() as session:
    session.execute(
      delete(LiteratureChunkRecord).where(LiteratureChunkRecord.workspace_id == workspace_id)
    )
    session.execute(
      delete(LiteratureIndexStatus).where(
        LiteratureIndexStatus.workspace_id == workspace_id
      )
    )
    session.commit()

  fts_store.delete_by_workspace(workspace_id)
  vector_store.delete_workspace_collection(workspace_id)


def reindex_workspace(workspace_id: str) -> dict[str, Any]:
  with get_session() as session:
    ws = session.get(WorkspaceRecord, workspace_id)
    if not ws:
      raise ValueError("工作空间不存在")
    lit_ids = session.scalars(
      select(LiteratureRecord.id).where(LiteratureRecord.workspace_id == workspace_id)
    ).all()

  results = []
  for lid in lit_ids:
    try:
      results.append(index_literature(lid, force=True))
    except Exception as e:
      results.append({"literature_id": lid, "status": "failed", "error": str(e)})

  return {
    "workspace_id": workspace_id,
    "total": len(lit_ids),
    "results": results,
  }


async def index_literature_async(literature_id: str, *, force: bool = False) -> None:
  """异步索引（带并发限流）"""
  if not settings.rag_enabled:
    return
  sem = _get_semaphore()
  async with sem:
    await asyncio.to_thread(index_literature, literature_id, force=force)


async def schedule_index(literature_id: str, *, force: bool = False) -> None:
  """从 async 处理器调度索引任务"""
  asyncio.create_task(index_literature_async(literature_id, force=force))


def schedule_index_sync(literature_id: str, *, force: bool = False) -> None:
  """从同步上下文安全调度后台索引任务"""
  try:
    loop = asyncio.get_running_loop()
  except RuntimeError:
    index_literature(literature_id, force=force)
    return
  loop.create_task(index_literature_async(literature_id, force=force))
