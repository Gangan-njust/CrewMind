"""文献工作空间数据存储"""
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, select

from backend.config import settings, PROJECT_ROOT
from backend.literature.metadata import extract_doi_from_text, fetch_metadata
from backend.literature.parser import extract_full_text, is_pdf_file
from backend.utils.text import sanitize_unicode, sanitize_deep
from backend.storage.database import get_session
from backend.storage.models import (
  LiteratureAnalysisRecord,
  LiteratureRecord,
  WorkspaceRecord,
  WorkspaceSelectionRecord,
)


def _load_json(text: str, default=None):
  try:
    return json.loads(text or "null")
  except json.JSONDecodeError:
    return default if default is not None else []


def _literature_dir(workspace_id: str) -> Path:
  path = (PROJECT_ROOT / settings.literature_dir / workspace_id).resolve()
  path.mkdir(parents=True, exist_ok=True)
  return path


def _safe_filename(name: str) -> str:
  base = Path(name).name
  base = re.sub(r"[^\w.\- ()]+", "_", base, flags=re.UNICODE)
  return base[:120] or "paper.pdf"


class LiteratureStore:
  def _verify_workspace(self, workspace_id: str, user_id: str) -> None:
    with get_session() as session:
      ws = session.get(WorkspaceRecord, workspace_id)
      if not ws or ws.user_id != user_id:
        raise ValueError("工作空间不存在或无权访问")

  def list_workspaces(self, user_id: str) -> list[dict]:
    with get_session() as session:
      rows = session.scalars(
        select(WorkspaceRecord)
        .where(WorkspaceRecord.user_id == user_id)
        .order_by(WorkspaceRecord.updated_at.desc())
      ).all()
      result = []
      for ws in rows:
        count = session.scalar(
          select(func.count()).select_from(LiteratureRecord).where(
            LiteratureRecord.workspace_id == ws.id
          )
        )
        result.append({
          "id": ws.id,
          "name": ws.name,
          "description": ws.description,
          "literature_count": count or 0,
          "created_at": ws.created_at.isoformat(),
          "updated_at": ws.updated_at.isoformat(),
        })
      return result

  def create_workspace(self, user_id: str, name: str, description: str = "") -> dict:
    now = datetime.now()
    ws_id = str(uuid.uuid4())
    with get_session() as session:
      ws = WorkspaceRecord(
        id=ws_id,
        name=name,
        description=description,
        user_id=user_id,
        current_selected_ids_json="[]",
        created_at=now,
        updated_at=now,
      )
      session.add(ws)
      session.commit()
      return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "literature_count": 0,
        "created_at": ws.created_at.isoformat(),
        "updated_at": ws.updated_at.isoformat(),
      }

  def update_workspace(self, workspace_id: str, user_id: str, name: str, description: str) -> dict:
    self._verify_workspace(workspace_id, user_id)
    with get_session() as session:
      ws = session.get(WorkspaceRecord, workspace_id)
      ws.name = name
      ws.description = description
      ws.updated_at = datetime.now()
      session.commit()
      count = session.scalar(
        select(func.count()).select_from(LiteratureRecord).where(
          LiteratureRecord.workspace_id == workspace_id
        )
      )
      return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "literature_count": count or 0,
        "created_at": ws.created_at.isoformat(),
        "updated_at": ws.updated_at.isoformat(),
      }

  def delete_workspace(self, workspace_id: str, user_id: str) -> None:
    self._verify_workspace(workspace_id, user_id)
    with get_session() as session:
      lit_ids = session.scalars(
        select(LiteratureRecord.id).where(LiteratureRecord.workspace_id == workspace_id)
      ).all()
      if lit_ids:
        session.execute(
          delete(LiteratureAnalysisRecord).where(
            LiteratureAnalysisRecord.literature_id.in_(lit_ids)
          )
        )
      session.execute(delete(LiteratureRecord).where(LiteratureRecord.workspace_id == workspace_id))
      session.execute(
        delete(WorkspaceSelectionRecord).where(
          WorkspaceSelectionRecord.workspace_id == workspace_id
        )
      )
      session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id))
      session.commit()

    lit_dir = PROJECT_ROOT / settings.literature_dir / workspace_id
    if lit_dir.exists():
      shutil.rmtree(lit_dir, ignore_errors=True)

  def upload_literature(
    self,
    workspace_id: str,
    user_id: str,
    filename: str,
    content: bytes,
  ) -> dict:
    self._verify_workspace(workspace_id, user_id)
    if not is_pdf_file(filename, content):
      raise ValueError("仅支持 PDF 格式文献")

    lit_id = str(uuid.uuid4())
    safe_name = _safe_filename(filename)
    pdf_path = _literature_dir(workspace_id) / f"{lit_id}_{safe_name}"
    pdf_path.write_bytes(content)
    pdf_path = pdf_path.resolve()

    title = Path(filename).stem
    doi = ""
    abstract = ""
    authors: list[str] = []
    journal = ""
    year = None

    try:
      text_preview = extract_full_text(pdf_path, use_cache=False)[:5000]
      doi = extract_doi_from_text(text_preview) or ""
    except Exception:
      text_preview = ""

    now = datetime.now()
    lit = LiteratureRecord(
      id=lit_id,
      workspace_id=workspace_id,
      title=title,
      authors_json=json.dumps(authors, ensure_ascii=False),
      journal=journal,
      year=year,
      doi=doi,
      abstract=abstract,
      pdf_path=str(pdf_path),
      full_text=sanitize_unicode(text_preview) if text_preview else "",
      uploaded_at=now,
      status="pending",
    )
    with get_session() as session:
      session.add(lit)
      session.commit()

    return self.get_literature(workspace_id, lit_id, user_id)

  async def enrich_metadata(self, literature_id: str) -> dict:
    with get_session() as session:
      lit = session.get(LiteratureRecord, literature_id)
      if not lit or not lit.doi:
        return {}
      try:
        meta = await fetch_metadata(lit.doi)
        lit.title = meta.get("title") or lit.title
        lit.authors_json = json.dumps(meta.get("authors", []), ensure_ascii=False)
        lit.journal = meta.get("journal") or lit.journal
        lit.year = meta.get("year") or lit.year
        lit.abstract = meta.get("abstract") or lit.abstract
        lit.doi = meta.get("doi") or lit.doi
        session.commit()
        return meta
      except Exception:
        return {}

  def list_literatures(
    self,
    workspace_id: str,
    user_id: str | None = None,
    *,
    include_analysis: bool = True,
    page: int = 1,
    page_size: int = 50,
  ) -> list[dict]:
    if user_id:
      self._verify_workspace(workspace_id, user_id)

    with get_session() as session:
      stmt = select(LiteratureRecord).where(LiteratureRecord.workspace_id == workspace_id)
      stmt = stmt.order_by(LiteratureRecord.uploaded_at.desc())
      if page_size:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
      rows = session.scalars(stmt).all()
      result = []
      for lit in rows:
        analysis = None
        if include_analysis:
          analysis = session.scalar(
            select(LiteratureAnalysisRecord).where(
              LiteratureAnalysisRecord.literature_id == lit.id
            )
          )
        result.append(self._serialize(lit, analysis))
      return result

  def get_literature(self, workspace_id: str, literature_id: str, user_id: str) -> dict:
    self._verify_workspace(workspace_id, user_id)
    with get_session() as session:
      lit = session.get(LiteratureRecord, literature_id)
      if not lit or lit.workspace_id != workspace_id:
        raise ValueError("文献不存在")
      analysis = session.scalar(
        select(LiteratureAnalysisRecord).where(
          LiteratureAnalysisRecord.literature_id == literature_id
        )
      )
      return self._serialize(lit, analysis)

  def get_literatures_by_ids(self, workspace_id: str, literature_ids: list[str]) -> list[dict]:
    with get_session() as session:
      rows = session.scalars(
        select(LiteratureRecord).where(
          LiteratureRecord.workspace_id == workspace_id,
          LiteratureRecord.id.in_(literature_ids),
        )
      ).all()
      id_order = {lid: i for i, lid in enumerate(literature_ids)}
      items = []
      for lit in rows:
        analysis = session.scalar(
          select(LiteratureAnalysisRecord).where(
            LiteratureAnalysisRecord.literature_id == lit.id
          )
        )
        items.append((id_order.get(lit.id, 999), self._serialize(lit, analysis)))
      items.sort(key=lambda x: x[0])
      return [item[1] for item in items]

  def delete_literature(self, workspace_id: str, literature_id: str, user_id: str) -> None:
    self._verify_workspace(workspace_id, user_id)
    pdf_path = ""
    with get_session() as session:
      lit = session.get(LiteratureRecord, literature_id)
      if not lit or lit.workspace_id != workspace_id:
        raise ValueError("文献不存在")
      pdf_path = lit.pdf_path
      session.execute(
        delete(LiteratureAnalysisRecord).where(
          LiteratureAnalysisRecord.literature_id == literature_id
        )
      )
      session.delete(lit)
      session.commit()

    if pdf_path:
      Path(pdf_path).unlink(missing_ok=True)

  def update_analysis(self, literature_id: str, user_id: str, updates: dict) -> dict:
    with get_session() as session:
      lit = session.get(LiteratureRecord, literature_id)
      if not lit:
        raise ValueError("文献不存在")
      ws = session.get(WorkspaceRecord, lit.workspace_id)
      if not ws or ws.user_id != user_id:
        raise ValueError("无权修改")

      analysis = session.scalar(
        select(LiteratureAnalysisRecord).where(
          LiteratureAnalysisRecord.literature_id == literature_id
        )
      )
      if not analysis:
        raise ValueError("分析结果不存在")

      field_map = {
        "tags": "tags_json",
        "contribution_summary": "contribution_summary",
        "relevance_score": "relevance_score",
        "recommendation_score": "recommendation_score",
        "key_findings": "key_findings_json",
        "limitations": "limitations_json",
        "citation_templates": "citation_templates_json",
        "formulas": "formulas_json",
        "research_background": "research_background",
        "research_goal": "research_goal",
        "methods_summary": "methods_summary",
        "conclusion": "conclusion",
      }
      json_fields = {"tags", "key_findings", "limitations", "citation_templates", "formulas"}
      for key, col in field_map.items():
        if key in updates:
          val = updates[key]
          if key in json_fields:
            val = json.dumps(val, ensure_ascii=False)
          setattr(analysis, col, val)
      analysis.updated_at = datetime.now()
      session.commit()
      return self._serialize(lit, analysis)

  def _serialize(self, lit: LiteratureRecord, analysis: LiteratureAnalysisRecord | None) -> dict:
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
        "id": analysis.id,
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
        "created_at": analysis.created_at.isoformat(),
        "updated_at": analysis.updated_at.isoformat(),
      }
    return sanitize_deep(item)


literature_store = LiteratureStore()
