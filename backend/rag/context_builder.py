"""将检索结果格式化为 prompt 引用块"""
from __future__ import annotations

from typing import Any


def build_rag_context(
  hits: list[dict[str, Any]],
  *,
  max_chars: int = 6000,
) -> str:
  if not hits:
    return ""

  lines = ["以下是与当前任务相关的文献证据片段，请优先引用这些内容，不得虚构未出现的数据：", ""]
  used = 0
  for i, hit in enumerate(hits, 1):
    title = hit.get("literature_title") or hit.get("literature_id", "未知文献")
    section = hit.get("section_key") or "unknown"
    excerpt = (hit.get("content") or hit.get("excerpt") or "").strip()
    block = (
      f"[证据 {i}] 文献：{title}\n"
      f"章节：{section} | chunk_id：{hit.get('chunk_id', '')}\n"
      f"{excerpt}\n"
    )
    if used + len(block) > max_chars:
      break
    lines.append(block)
    used += len(block)

  return "\n".join(lines).strip()


def build_sources(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
  sources = []
  for hit in hits:
    sources.append({
      "literature_id": hit.get("literature_id"),
      "literature_title": hit.get("literature_title", ""),
      "chunk_id": hit.get("chunk_id"),
      "section_key": hit.get("section_key", ""),
      "excerpt": (hit.get("content") or hit.get("excerpt") or "")[:500],
      "score": hit.get("score"),
    })
  return sources
