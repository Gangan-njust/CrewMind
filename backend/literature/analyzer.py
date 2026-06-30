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
from backend.literature.parser import extract_full_text, resolve_pdf_path
from backend.utils.text import sanitize_unicode, sanitize_deep
from backend.literature.prompts import (
  CITATION_TEMPLATES_PROMPT,
  CORE_EXTRACTION_PROMPT,
  FORMULA_EXTRACTION_PROMPT,
  INNOVATION_PROMPT,
  RELEVANCE_SCORE_PROMPT,
  RESEARCH_GAP_PROMPT,
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
      "title": lit.title or "",
      "authors": json.loads(lit.authors_json or "[]"),
      "journal": lit.journal or "",
      "year": lit.year,
      "abstract": lit.abstract or "",
      "content": sanitize_unicode((lit.full_text or "").strip()),
      "pdf_path": lit.pdf_path or "",
    }

  if not meta["content"]:
    if not meta["pdf_path"]:
      _set_literature_status(literature_id, "failed")
      raise ValueError("文献内容为空，请重新上传 PDF")

    try:
      resolved = resolve_pdf_path(meta["pdf_path"])
      if not resolved.exists():
        _set_literature_status(literature_id, "failed")
        raise ValueError(f"PDF 文件不存在: {resolved}")
      content = extract_full_text(resolved, use_cache=True)
      meta["content"] = content
      with get_session() as session:
        lit = session.get(LiteratureRecord, literature_id)
        if lit:
          lit.full_text = sanitize_unicode(content)
          if not lit.pdf_path:
            lit.pdf_path = str(resolved)
          session.commit()
    except ValueError:
      raise
    except Exception as e:
      _set_literature_status(literature_id, "failed")
      raise ValueError(f"PDF 解析失败: {e}") from e

  return meta


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
  content_sample = _truncate(content or meta["abstract"] or "")

  core = await _llm_json(CORE_EXTRACTION_PROMPT.format(
    title=meta["title"] or "未知标题",
    authors=", ".join(meta["authors"]) if meta["authors"] else "未知",
    journal=meta["journal"] or "未知",
    year=meta["year"] or "未知",
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

  return _save_analysis_result(literature_id, sanitize_deep({
    "tags": all_tags,
    "contribution_summary": core.get("contribution_summary", ""),
    "relevance_score": relevance_score,
    "recommendation_score": recommendation_score,
    "key_findings": core.get("key_findings", []),
    "limitations": core.get("limitations", []),
    "citation_templates": citations.get("citations", []),
    "formulas": formulas_result.get("formulas", []),
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

  prompt = RESEARCH_GAP_PROMPT.format(
    user_topic=user_topic,
    literature_summaries="\n".join(summaries),
  )
  return await _llm_json(prompt)
