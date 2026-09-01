"""文献库 RAG 问答"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from backend.config import settings
from backend.llm.client import llm_client
from backend.rag.context_builder import build_rag_context, build_sources
from backend.rag.prompts import RAG_QUERY_PROMPT
from backend.rag.retriever import retrieve

logger = logging.getLogger(__name__)


async def answer_query(
  workspace_id: str,
  question: str,
  *,
  literature_ids: list[str] | None = None,
) -> dict[str, Any]:
  if not settings.rag_enabled:
    raise ValueError("RAG 功能未启用")

  hits = retrieve(
    workspace_id,
    question,
    literature_ids=literature_ids,
  )
  sources = build_sources(hits)
  context = build_rag_context(hits) if hits else "（未检索到相关文献片段）"

  prompt = RAG_QUERY_PROMPT.format(question=question.strip(), context=context)
  response = await llm_client.chat(
    [{"role": "user", "content": prompt}],
    temperature=0.3,
  )
  if hasattr(response, "__aiter__"):
    chunks = []
    async for chunk in response:
      chunks.append(chunk)
    answer = "".join(chunks)
  else:
    answer = str(response)

  return {
    "question": question,
    "answer": answer.strip(),
    "sources": sources,
    "evidence_count": len(sources),
  }


async def stream_query(
  workspace_id: str,
  question: str,
  *,
  literature_ids: list[str] | None = None,
) -> AsyncIterator[str]:
  """SSE 事件流：sources → token chunks → done"""
  if not settings.rag_enabled:
    yield _sse("error", {"message": "RAG 功能未启用"})
    return

  hits = retrieve(
    workspace_id,
    question,
    literature_ids=literature_ids,
  )
  sources = build_sources(hits)
  context = build_rag_context(hits) if hits else "（未检索到相关文献片段）"

  yield _sse("sources", {"sources": sources, "evidence_count": len(sources)})

  prompt = RAG_QUERY_PROMPT.format(question=question.strip(), context=context)
  stream = await llm_client.chat(
    [{"role": "user", "content": prompt}],
    temperature=0.3,
    stream=True,
  )

  full_parts: list[str] = []
  async for chunk in stream:
    full_parts.append(chunk)
    yield _sse("token", {"content": chunk})

  yield _sse("done", {
    "question": question,
    "answer": "".join(full_parts).strip(),
    "sources": sources,
  })


def _sse(event: str, data: dict[str, Any]) -> str:
  return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
