"""本地文献库 RAG 检索工具"""
import json
import logging

from backend.config import settings
from backend.rag.context_builder import build_rag_context
from backend.rag.prompts import RAG_SEARCH_TOOL_HINT
from backend.rag.retriever import retrieve
from backend.tools.base import BaseTool

logger = logging.getLogger(__name__)


class RagSearchTool(BaseTool):
  name = "rag_search"
  description = "检索用户本地文献库中的相关段落，返回带溯源的原文摘录"

  async def run(
    self,
    query: str = "",
    workspace_id: str = "",
    max_results: int = 8,
    **_,
  ) -> str:
    if not query:
      return "错误：请提供检索关键词"
    if not workspace_id:
      return "错误：未关联文献工作空间，无法检索本地文献库"
    if not settings.rag_enabled:
      return "本地文献库检索未启用（RAG_ENABLED=false）"

    try:
      hits = retrieve(workspace_id, query)
      if not hits:
        return (
          f"本地文献库中未找到与「{query}」相关的段落。"
          "请说明该部分需依赖网络检索或人工补充。"
        )
      context = build_rag_context(hits, max_chars=8000)
      payload = {
        "source": "local_literature_library",
        "query": query,
        "count": len(hits),
        "evidence": context,
        "chunks": [
          {
            "chunk_id": h.get("chunk_id"),
            "literature_id": h.get("literature_id"),
            "literature_title": h.get("literature_title"),
            "section_key": h.get("section_key"),
            "excerpt": (h.get("content") or h.get("excerpt") or "")[:500],
          }
          for h in hits
        ],
      }
      return f"{RAG_SEARCH_TOOL_HINT}\n\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    except Exception as e:
      logger.warning("rag_search 失败: %s", e)
      return f"本地文献库检索失败: {e}"
