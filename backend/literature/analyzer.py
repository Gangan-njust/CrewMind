"""文献智能分析模块"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Callable, Awaitable

from sqlalchemy import select

from backend.config import settings
from backend.literature.content import empty_content_error, resolve_literature_full_text
from backend.literature.parser import resolve_pdf_path
from backend.utils.text import sanitize_unicode, sanitize_deep
from backend.literature.prompts import (
  CITATION_TEMPLATES_PROMPT,
  CORE_EXTRACTION_PROMPT,
  FORMULA_EXTRACTION_PROMPT,
  IMAGE_PLACEMENT_PROMPT,
  INNOVATION_PROMPT,
  RELEVANCE_SCORE_PROMPT,
  RESEARCH_GAP_PROMPT,
  RESULTS_EXTRACTION_PROMPT,
  TAG_GENERATION_PROMPT,
)
from backend.literature.section_splitter import split_sections
from backend.llm.client import llm_client
from backend.storage.database import get_session
from backend.storage.models import LiteratureAnalysisRecord, LiteratureRecord

logger = logging.getLogger(__name__)

_analysis_progress: dict[str, dict[str, Any]] = {}
_analysis_lock = asyncio.Lock()
_semaphore: asyncio.Semaphore | None = None


def get_analysis_progress(workspace_id: str) -> dict[str, Any]:
  return _analysis_progress.get(workspace_id, {
    "workspace_id": workspace_id,
    "total": 0,
    "completed": 0,
    "current_literature": None,
    "status": "idle",
  })


def _get_semaphore() -> asyncio.Semaphore:
  global _semaphore
  if _semaphore is None:
    _semaphore = asyncio.Semaphore(settings.literature_analysis_concurrency)
  return _semaphore


def _parse_json_response(text: str) -> dict:
  text = text.strip()
  if text.startswith("```"):
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
  try:
    return json.loads(text)
  except json.JSONDecodeError:
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
      return json.loads(match.group(0))
    raise ValueError(f"无法解析 LLM JSON 输出: {text[:200]}")


async def _llm_json(prompt: str) -> dict:
  response = await llm_client.chat(
    [{"role": "user", "content": prompt}],
    temperature=0.3,
  )
  if hasattr(response, "__aiter__"):
    chunks = []
    async for chunk in response:
      chunks.append(chunk)
    response = "".join(chunks)
  return _parse_json_response(str(response))


def _truncate(text: str, max_len: int = 12000) -> str:
  if len(text) <= max_len:
    return text
  return text[: max_len // 2] + "\n\n[...内容截断...]\n\n" + text[-max_len // 2 :]


def _set_literature_status(literature_id: str, status: str) -> None:
  with get_session() as session:
    lit = session.get(LiteratureRecord, literature_id)
    if lit:
      lit.status = status
      session.commit()


def _load_literature_content(literature_id: str) -> dict[str, Any]:
  """从数据库加载文献内容与元数据，必要时从 PDF 补提取全文"""
  with get_session() as session:
    lit = session.get(LiteratureRecord, literature_id)
    if not lit:
      raise ValueError(f"文献不存在: {literature_id}")

    lit.status = "processing"
    session.commit()

    meta = {
      "literature_id": literature_id,
      "workspace_id": lit.workspace_id,
      "title": lit.title or "",
      "authors": json.loads(lit.authors_json or "[]"),
      "journal": lit.journal or "",
      "year": lit.year,
      "abstract": lit.abstract or "",
      "content": "",
      "pdf_path": lit.pdf_path or "",
    }

  content, pdf_err = resolve_literature_full_text(lit, persist=True)
  meta["content"] = content

  if not meta["content"]:
    if not meta["pdf_path"]:
      _set_literature_status(literature_id, "failed")
      raise ValueError(empty_content_error(lit, pdf_err=pdf_err))

    resolved = resolve_pdf_path(meta["pdf_path"])
    if not resolved.exists():
      _set_literature_status(literature_id, "failed")
      raise ValueError(f"PDF 文件不存在: {resolved}")
    _set_literature_status(literature_id, "failed")
    raise ValueError(empty_content_error(lit, pdf_err=pdf_err))

  return meta


async def _ensure_indexed(literature_id: str) -> None:
  """分析前先同步完成 RAG 索引，保证按切块索引结果进行检索分析"""
  if not settings.rag_enabled:
    return
  try:
    from backend.rag.indexer import index_literature
    await asyncio.to_thread(index_literature, literature_id)
  except Exception:
    logger.warning("分析前索引失败，将回退全文截取分析: %s", literature_id, exc_info=True)


def _save_analysis_result(literature_id: str, payload: dict[str, Any]) -> dict[str, Any]:
  now = datetime.now()
  with get_session() as session:
    lit = session.get(LiteratureRecord, literature_id)
    if not lit:
      raise ValueError(f"文献不存在: {literature_id}")

    existing = session.scalar(
      select(LiteratureAnalysisRecord).where(
        LiteratureAnalysisRecord.literature_id == literature_id
      )
    )
    analysis = existing or LiteratureAnalysisRecord(
      id=str(uuid.uuid4()),
      literature_id=literature_id,
      created_at=now,
    )
    if not existing:
      session.add(analysis)

    analysis.tags_json = json.dumps(payload["tags"], ensure_ascii=False)
    analysis.contribution_summary = payload["contribution_summary"]
    analysis.relevance_score = payload["relevance_score"]
    analysis.recommendation_score = payload["recommendation_score"]
    analysis.key_findings_json = json.dumps(payload["key_findings"], ensure_ascii=False)
    analysis.limitations_json = json.dumps(payload["limitations"], ensure_ascii=False)
    analysis.citation_templates_json = json.dumps(payload["citation_templates"], ensure_ascii=False)
    analysis.formulas_json = json.dumps(payload.get("formulas", []), ensure_ascii=False)
    analysis.results_json = json.dumps(payload.get("results", {}), ensure_ascii=False)
    analysis.images_json = json.dumps(payload.get("images", []), ensure_ascii=False)
    analysis.research_background = payload["research_background"]
    analysis.research_goal = payload["research_goal"]
    analysis.methods_summary = payload["methods_summary"]
    analysis.conclusion = payload["conclusion"]
    analysis.updated_at = now
    lit.status = "done"
    session.commit()

    return {
      "literature_id": literature_id,
      "title": lit.title,
      "tags": payload["tags"],
      "contribution_summary": payload["contribution_summary"],
      "relevance_score": payload["relevance_score"],
      "recommendation_score": payload["recommendation_score"],
      "key_findings": payload["key_findings"],
      "limitations": payload["limitations"],
      "citation_templates": payload["citation_templates"],
      "formulas": payload.get("formulas", []),
      "results": payload.get("results", {}),
      "images": payload.get("images", []),
      "research_background": payload["research_background"],
      "research_goal": payload["research_goal"],
      "methods_summary": payload["methods_summary"],
      "conclusion": payload["conclusion"],
      "innovations": payload["innovations"],
      "sections": payload["sections"],
    }


async def analyze_single_literature(
  literature_id: str,
  user_topic: str | None = None,
) -> dict[str, Any]:
  """分析单篇文献并写入 literature_analysis 表"""
  meta = _load_literature_content(literature_id)
  content = meta["content"]
  sections = split_sections(content)

  # 先完成 RAG 索引，再基于切块索引结果检索分析
  await _ensure_indexed(literature_id)

  from backend.rag.analysis_helpers import build_literature_analysis_context

  content_sample, used_rag = build_literature_analysis_context(
    meta.get("workspace_id", ""),
    literature_id,
    meta["title"] or "",
    meta["abstract"] or "",
    content,
  )
  if used_rag:
    logger.info("文献 %s 核心提取使用 RAG 上下文", literature_id)
  else:
    content_sample = _truncate(content or meta["abstract"] or "")

  core = await _llm_json(CORE_EXTRACTION_PROMPT.format(
    title=meta["title"] or "未知标题",
    authors=", ".join(meta["authors"]) if meta["authors"] else "未知",
    journal=meta["journal"] or "未知",
    year=meta["year"] or "未知",
    content=content_sample,
  ))

  results = await _llm_json(RESULTS_EXTRACTION_PROMPT.format(
    title=meta["title"] or "未知标题",
    methods=core.get("methods_summary", "") or "未提供",
    content=content_sample,
  ))

  innovation = await _llm_json(INNOVATION_PROMPT.format(
    title=meta["title"],
    content=core.get("contribution_summary", content_sample[:2000]),
  ))

  tags = await _llm_json(TAG_GENERATION_PROMPT.format(
    title=meta["title"],
    methods=core.get("methods_summary", ""),
    user_topic=user_topic or "通用科研",
  ))

  methods_summary = core.get("methods_summary", "")
  section_map = sections.to_dict()
  formula_source = section_map.get("methods") or section_map.get("results") or content_sample

  from backend.rag.analysis_helpers import retrieve_multi_query

  formula_hits: list[dict] = []
  try:
    formula_hits = retrieve_multi_query(
      meta.get("workspace_id", ""),
      [f"{meta['title']} 公式 算法 模型"],
      literature_ids=[literature_id],
      section_keys=["methods", "results"],
    )
  except Exception:
    logger.warning("公式 RAG 检索失败，回退全文截取: %s", literature_id, exc_info=True)
  if formula_hits:
    from backend.rag.context_builder import build_rag_context
    formula_content = build_rag_context(formula_hits, max_chars=8000)
  else:
    formula_content = _truncate(formula_source, max_len=8000)
  formulas_result = await _llm_json(FORMULA_EXTRACTION_PROMPT.format(
    title=meta["title"] or "未知标题",
    methods=methods_summary or "未提供",
    content=formula_content,
  ))

  findings = core.get("key_findings", [])
  citations = await _llm_json(CITATION_TEMPLATES_PROMPT.format(
    title=meta["title"],
    authors=", ".join(meta["authors"][:3]),
    findings="; ".join(findings[:3]) if findings else core.get("conclusion", ""),
  ))

  relevance_score = None
  recommendation_score = None
  if user_topic:
    rel = await _llm_json(RELEVANCE_SCORE_PROMPT.format(
      user_topic=user_topic,
      title=meta["title"],
      abstract=meta["abstract"] or content_sample[:1000],
      contribution=core.get("contribution_summary", ""),
    ))
    relevance_score = float(rel.get("relevance_score", 0))
    recommendation_score = float(rel.get("recommendation_score", relevance_score))

  method_tags = tags.get("method_tags", [])
  domain_tags = tags.get("domain_tags", [])
  all_tags = list(dict.fromkeys(method_tags + domain_tags))

  # 提取文章中的图片供展示（存在 PDF 时）
  images: list[dict] = []
  if meta.get("pdf_path"):
    try:
      from backend.literature.images import extract_pdf_images
      images = extract_pdf_images(
        meta["pdf_path"],
        meta.get("workspace_id", ""),
        literature_id,
      )
    except Exception:
      logger.warning("文献图片提取失败: %s", literature_id, exc_info=True)

  # 让 LLM 根据「页码 + 所在页文字上下文」把每张图归属到对应章节，便于在内容处内联展示
  if images:
    try:
      image_list = "\n".join(
        f"[{i + 1}] {img['filename']} | 第{img.get('page', '?')}页 | 上下文: {(img.get('context') or '')[:200]}"
        for i, img in enumerate(images)
      )
      placements = await _llm_json(IMAGE_PLACEMENT_PROMPT.format(
        title=meta["title"] or "未知标题",
        methods=methods_summary or "未提供",
        results=results.get("results_summary", "") or core.get("conclusion", ""),
        images=image_list,
      ))
      placed_by_file = {
        p.get("filename"): p
        for p in placements.get("image_placements", [])
        if p.get("filename")
      }
      for img in images:
        placed = placed_by_file.get(img["filename"], {})
        section = (placed.get("section") or "results").strip()
        img["section"] = section if section in {
          "background", "methods", "results", "discussion", "conclusion",
        } else "results"
        img["caption"] = (placed.get("caption") or "").strip()
    except Exception:
      logger.warning("图片章节归属分析失败，默认归入结果章节: %s", literature_id, exc_info=True)
      for img in images:
        img.setdefault("section", "results")
        img.setdefault("caption", "")

  return _save_analysis_result(literature_id, sanitize_deep({
    "tags": all_tags,
    "contribution_summary": core.get("contribution_summary", ""),
    "relevance_score": relevance_score,
    "recommendation_score": recommendation_score,
    "key_findings": core.get("key_findings", []),
    "limitations": core.get("limitations", []),
    "citation_templates": citations.get("citations", []),
    "formulas": formulas_result.get("formulas", []),
    "results": {
      "article_summary": results.get("article_summary", ""),
      "results_summary": results.get("results_summary", ""),
      "result_items": results.get("result_items", []),
      "important_figures": results.get("important_figures", []),
    },
    "images": images,
    "research_background": core.get("research_background", ""),
    "research_goal": core.get("research_goal", ""),
    "methods_summary": methods_summary,
    "conclusion": core.get("conclusion", ""),
    "innovations": innovation.get("innovations", []),
    "sections": sections.to_dict(),
  }))


async def analyze_batch(
  literature_ids: list[str],
  workspace_id: str,
  user_topic: str | None = None,
  on_progress: Callable[[dict], Awaitable[None]] | None = None,
) -> list[dict]:
  """批量分析文献，控制并发并更新进度"""
  async with _analysis_lock:
    _analysis_progress[workspace_id] = {
      "workspace_id": workspace_id,
      "total": len(literature_ids),
      "completed": 0,
      "current_literature": None,
      "status": "running",
    }

  sem = _get_semaphore()
  results: list[dict] = []

  async def _analyze_one(lit_id: str) -> None:
    async with sem:
      _analysis_progress[workspace_id]["current_literature"] = lit_id
      if on_progress:
        await on_progress(_analysis_progress[workspace_id])
      try:
        result = await analyze_single_literature(lit_id, user_topic)
        results.append(result)
      except Exception as e:
        logger.exception("文献分析失败: %s", lit_id)
        _set_literature_status(lit_id, "failed")
        results.append({"literature_id": lit_id, "error": str(e)})
      finally:
        _analysis_progress[workspace_id]["completed"] += 1
        if on_progress:
          await on_progress(_analysis_progress[workspace_id])

  await asyncio.gather(*[_analyze_one(lid) for lid in literature_ids])

  _analysis_progress[workspace_id]["status"] = "completed"
  _analysis_progress[workspace_id]["current_literature"] = None
  if on_progress:
    await on_progress(_analysis_progress[workspace_id])

  return results


async def identify_research_gaps(workspace_id: str, user_topic: str) -> dict:
  """跨文献综合分析，识别研究空白"""
  from backend.storage.literature_store import literature_store

  literatures = literature_store.list_literatures(
    workspace_id, user_id=None, include_analysis=True
  )
  summaries = []
  for lit in literatures:
    if lit.get("status") != "done":
      continue
    analysis = lit.get("analysis") or {}
    summaries.append(
      f"- {lit.get('title')}: {analysis.get('contribution_summary', '')}"
    )

  if not summaries:
    return {"research_gaps": [], "future_directions": []}

  from backend.rag.analysis_helpers import build_research_gap_context

  rag_evidence, used_rag = build_research_gap_context(workspace_id, user_topic)
  if used_rag:
    logger.info("研究空白分析使用 RAG 多 query 检索: workspace=%s", workspace_id)

  prompt = RESEARCH_GAP_PROMPT.format(
    user_topic=user_topic,
    literature_summaries="\n".join(summaries),
    rag_evidence=rag_evidence or "（未检索到额外原文证据，请基于摘要推断）",
  )
  return await _llm_json(prompt)
