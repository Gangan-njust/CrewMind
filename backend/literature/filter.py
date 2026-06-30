"""文献筛选与检索"""
import json
from typing import Any

from sqlalchemy import select

from backend.storage.database import get_session
from backend.storage.models import LiteratureAnalysisRecord, LiteratureRecord, WorkspaceRecord


def _load_json(text: str, default: Any = None) -> Any:
  try:
    return json.loads(text or "null")
  except json.JSONDecodeError:
    return default if default is not None else []


def _serialize_literature(lit: LiteratureRecord, analysis: LiteratureAnalysisRecord | None) -> dict:
  item = {
    "id": lit.id,
    "workspace_id": lit.workspace_id,
    "title": lit.title,
    "authors": _load_json(lit.authors_json, []),
    "journal": lit.journal,
    "year": lit.year,
    "doi": lit.doi,
    "abstract": lit.abstract,
    "pdf_path": lit.pdf_path,
    "uploaded_at": lit.uploaded_at.isoformat(),
    "status": lit.status,
  }
  if analysis:
    item["analysis"] = {
      "tags": _load_json(analysis.tags_json, []),
      "contribution_summary": analysis.contribution_summary,
      "relevance_score": analysis.relevance_score,
      "recommendation_score": analysis.recommendation_score,
      "key_findings": _load_json(analysis.key_findings_json, []),
      "limitations": _load_json(analysis.limitations_json, []),
      "citation_templates": _load_json(analysis.citation_templates_json, []),
      "formulas": _load_json(analysis.formulas_json, []),
      "research_background": analysis.research_background,
      "research_goal": analysis.research_goal,
      "methods_summary": analysis.methods_summary,
      "conclusion": analysis.conclusion,
    }
  return item


def filter_literatures(
  workspace_id: str,
  *,
  tags: list[str] | None = None,
  keyword: str | None = None,
  year_min: int | None = None,
  year_max: int | None = None,
  journal: str | None = None,
  author: str | None = None,
  min_relevance: float | None = None,
  status: str | None = None,
  sort_by: str = "uploaded_at",
  sort_order: str = "desc",
) -> list[dict]:
  """按条件筛选文献"""
  with get_session() as session:
    stmt = (
      select(LiteratureRecord, LiteratureAnalysisRecord)
      .outerjoin(
        LiteratureAnalysisRecord,
        LiteratureAnalysisRecord.literature_id == LiteratureRecord.id,
      )
      .where(LiteratureRecord.workspace_id == workspace_id)
    )
    rows = session.execute(stmt).all()
    results = [_serialize_literature(lit, analysis) for lit, analysis in rows]

  if tags:
    tag_set = set(t.lower() for t in tags)
    results = [
      r for r in results
      if tag_set.intersection(t.lower() for t in (r.get("analysis") or {}).get("tags", []))
    ]

  if keyword:
    kw = keyword.lower()
    results = [
      r for r in results
      if kw in r.get("title", "").lower()
      or kw in r.get("abstract", "").lower()
      or any(kw in a.lower() for a in r.get("authors", []))
    ]

  if year_min is not None:
    results = [r for r in results if r.get("year") and r["year"] >= year_min]
  if year_max is not None:
    results = [r for r in results if r.get("year") and r["year"] <= year_max]

  if journal:
    j = journal.lower()
    results = [r for r in results if j in r.get("journal", "").lower()]

  if author:
    a = author.lower()
    results = [r for r in results if any(a in name.lower() for name in r.get("authors", []))]

  if min_relevance is not None:
    results = [
      r for r in results
      if (r.get("analysis") or {}).get("relevance_score", 0) >= min_relevance
    ]

  if status:
    results = [r for r in results if r.get("status") == status]

  reverse = sort_order.lower() != "asc"
  if sort_by == "relevance_score":
    results.sort(
      key=lambda r: (r.get("analysis") or {}).get("relevance_score") or 0,
      reverse=reverse,
    )
  elif sort_by == "year":
    results.sort(key=lambda r: r.get("year") or 0, reverse=reverse)
  else:
    results.sort(key=lambda r: r.get("uploaded_at", ""), reverse=reverse)

  return results


def search_literatures(
  workspace_id: str,
  *,
  keyword: str | None = None,
  year_min: int | None = None,
  year_max: int | None = None,
  tags: list[str] | None = None,
  min_relevance: float | None = None,
) -> list[dict]:
  """高级组合搜索"""
  return filter_literatures(
    workspace_id,
    keyword=keyword,
    year_min=year_min,
    year_max=year_max,
    tags=tags,
    min_relevance=min_relevance,
  )
