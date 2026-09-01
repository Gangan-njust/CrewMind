"""文献分析 / 研究空白分析用的 RAG 上下文构建"""
from __future__ import annotations

import logging
from backend.config import settings
from backend.rag.context_builder import build_rag_context
from backend.rag.retriever import retrieve

logger = logging.getLogger(__name__)


def _dedupe_hits(hits: list[dict]) -> list[dict]:
  seen: set[str] = set()
  out: list[dict] = []
  for h in hits:
    cid = h.get("chunk_id", "")
    if cid and cid in seen:
      continue
    if cid:
      seen.add(cid)
    out.append(h)
  return out


def retrieve_multi_query(
  workspace_id: str,
  queries: list[str],
  *,
  literature_ids: list[str] | None = None,
  section_keys: list[str] | None = None,
  per_query_k: int | None = None,
) -> list[dict]:
  if not settings.rag_enabled or not workspace_id:
    return []
  all_hits: list[dict] = []
  for q in queries:
    if not q.strip():
      continue
    try:
      hits = retrieve(
        workspace_id,
        q.strip(),
        literature_ids=literature_ids,
        section_keys=section_keys,
      )
    except Exception as e:
      logger.warning("RAG 检索失败 query=%r: %s", q[:80], e)
      continue
    if per_query_k:
      hits = hits[:per_query_k]
    all_hits.extend(hits)
  return _dedupe_hits(all_hits)


def build_literature_analysis_context(
  workspace_id: str,
  literature_id: str,
  title: str,
  abstract: str,
  full_text: str,
  *,
  max_chars: int = 12000,
) -> tuple[str, bool]:
  """返回 (上下文文本, 是否使用了 RAG)"""
  fallback = full_text or abstract or ""
  if not settings.rag_enabled or not workspace_id:
    return _truncate_plain(fallback, max_chars), False

  queries = [
    f"{title} 研究背景 研究目标 问题定义",
    f"{title} 研究方法 实验设计 数据集",
    f"{title} 实验结果 主要发现",
    f"{title} 结论 局限性 贡献",
  ]
  hits = retrieve_multi_query(
    workspace_id,
    queries,
    literature_ids=[literature_id],
  )
  if hits:
    return build_rag_context(hits, max_chars=max_chars), True

  return _truncate_plain(fallback, max_chars), False


def build_research_gap_context(
  workspace_id: str,
  user_topic: str,
  *,
  max_chars: int = 8000,
) -> tuple[str, bool]:
  if not settings.rag_enabled or not workspace_id:
    return "", False

  queries = [
    f"{user_topic} 研究空白 未解决问题",
    f"{user_topic} 局限性 不足 挑战",
    f"{user_topic} 未来方向 发展趋势",
    f"{user_topic} 方法对比 差异",
  ]
  hits = retrieve_multi_query(workspace_id, queries)
  if not hits:
    return "", False
  return build_rag_context(hits, max_chars=max_chars), True


def _truncate_plain(text: str, max_len: int) -> str:
  if len(text) <= max_len:
    return text
  half = max_len // 2
  return text[:half] + "\n\n[...内容截断...]\n\n" + text[-half:]
