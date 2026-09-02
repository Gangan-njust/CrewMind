"""学术写作项目数据存储"""
import json
import uuid
from datetime import datetime
from difflib import unified_diff
from pathlib import Path

from sqlalchemy import delete, select

from backend.config import PROJECT_ROOT, settings
from backend.storage.database import get_session
from backend.storage.models import (
  WritingAssetRecord,
  WritingProjectRecord,
  WritingReferenceRecord,
  WritingSectionRecord,
  WritingSectionVersionRecord,
)
from backend.storage.literature_store import literature_store
from backend.writing.paragraph_format import ensure_paragraph_first_indent
from backend.writing.templates import DEFAULT_SECTIONS, PAPER_TEMPLATES, SECTION_LABELS, section_display_title


def _normalize_workspace_id(workspace_id: str | None) -> str | None:
  if workspace_id is None:
    return None
  workspace_id = workspace_id.strip()
  return workspace_id or None


def _load_json(text: str, default=None):
  try:
    return json.loads(text or "null")
  except json.JSONDecodeError:
    return default if default is not None else []


def _count_words(text: str) -> int:
  if not text.strip():
    return 0
  chinese = len([c for c in text if "\u4e00" <= c <= "\u9fff"])
  english = len(text.split()) - chinese
  return chinese + max(english, 0)


BIBLIOGRAPHY_SECTION_TITLE = "参考文献"


class WritingStore:
  def _verify_project(self, project_id: str, user_id: str) -> WritingProjectRecord:
    with get_session() as session:
      project = session.get(WritingProjectRecord, project_id)
      if not project or project.user_id != user_id:
        raise ValueError("写作项目不存在或无权访问")
      return project

  def _verify_section(self, section_id: str, user_id: str) -> WritingSectionRecord:
    with get_session() as session:
      section = session.get(WritingSectionRecord, section_id)
      if not section:
        raise ValueError("章节不存在")
      project = session.get(WritingProjectRecord, section.project_id)
      if not project or project.user_id != user_id:
        raise ValueError("无权访问该章节")
      return section

  def _serialize_project(self, project: WritingProjectRecord, sections: list[WritingSectionRecord]) -> dict:
    return {
      "id": project.id,
      "title": project.title,
      "topic": project.topic,
      "paper_type": project.paper_type,
      "target_journal": project.target_journal,
      "source_workflow_id": project.source_workflow_id,
      "workspace_id": project.workspace_id,
      "outline": _load_json(project.outline_json, []),
      "keywords_zh": _load_json(project.keywords_zh_json, []),
      "keywords_en": _load_json(project.keywords_en_json, []),
      "citation_format": project.citation_format,
      "created_at": project.created_at.isoformat(),
      "updated_at": project.updated_at.isoformat(),
      "sections": [self._serialize_section(s) for s in sections],
    }

  def _sort_sections(self, sections: list[WritingSectionRecord], paper_type: str) -> list[WritingSectionRecord]:
    order = DEFAULT_SECTIONS.get(paper_type, DEFAULT_SECTIONS["journal"])
    return sorted(
      sections,
      key=lambda s: (
        s.sort_order if s.sort_order is not None else 999,
        order.index(s.section_type) if s.section_type in order else 999,
      ),
    )

  def _serialize_section(self, section: WritingSectionRecord) -> dict:
    data = {
      "id": section.id,
      "project_id": section.project_id,
      "section_type": section.section_type,
      "title": section.title or "",
      "sort_order": section.sort_order,
      "is_custom": bool(section.is_custom),
      "content": section.content,
      "word_count": section.word_count,
      "version": section.version,
      "created_at": section.created_at.isoformat(),
      "updated_at": section.updated_at.isoformat(),
    }
    data["display_title"] = section_display_title(data)
    return data

  def list_projects(self, user_id: str) -> list[dict]:
    with get_session() as session:
      rows = session.scalars(
        select(WritingProjectRecord)
        .where(WritingProjectRecord.user_id == user_id)
        .order_by(WritingProjectRecord.updated_at.desc())
      ).all()
      return [{
        "id": p.id,
        "title": p.title,
        "topic": p.topic,
        "paper_type": p.paper_type,
        "target_journal": p.target_journal,
        "source_workflow_id": p.source_workflow_id,
        "workspace_id": p.workspace_id,
        "keywords_zh": _load_json(p.keywords_zh_json, []),
        "keywords_en": _load_json(p.keywords_en_json, []),
        "citation_format": p.citation_format,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
      } for p in rows]

  def _ensure_missing_sections(
    self,
    session,
    project: WritingProjectRecord,
    sections: list[WritingSectionRecord],
  ) -> list[WritingSectionRecord]:
    required = DEFAULT_SECTIONS.get(project.paper_type, DEFAULT_SECTIONS["journal"])
    existing_types = {s.section_type for s in sections}
    missing = [st for st in required if st not in existing_types]
    if not missing:
      return sections

    now = datetime.now()
    for section_type in missing:
      sort_order = required.index(section_type)
      section = WritingSectionRecord(
        id=str(uuid.uuid4()),
        project_id=project.id,
        section_type=section_type,
        title="",
        sort_order=sort_order,
        is_custom=False,
        content="",
        word_count=0,
        version=1,
        created_at=now,
        updated_at=now,
      )
      session.add(section)
      session.add(WritingSectionVersionRecord(
        id=str(uuid.uuid4()),
        section_id=section.id,
        content="",
        word_count=0,
        version=1,
        note="自动补全章节",
        created_at=now,
      ))
    session.commit()
    return list(session.scalars(
      select(WritingSectionRecord)
      .where(WritingSectionRecord.project_id == project.id)
    ).all())

  def get_project(self, project_id: str, user_id: str) -> dict:
    self._verify_project(project_id, user_id)
    with get_session() as session:
      project = session.get(WritingProjectRecord, project_id)
      sections = list(session.scalars(
        select(WritingSectionRecord)
        .where(WritingSectionRecord.project_id == project_id)
      ).all())
      sections = self._ensure_missing_sections(session, project, sections)
      sections = self._sort_sections(sections, project.paper_type)
      return self._serialize_project(project, sections)

  def create_project(
    self,
    user_id: str,
    title: str,
    topic: str = "",
    paper_type: str = "journal",
    target_journal: str = "",
    source_workflow_id: str | None = None,
    workspace_id: str | None = None,
    outline: list | None = None,
  ) -> dict:
    if paper_type not in PAPER_TEMPLATES:
      raise ValueError(f"不支持的论文类型: {paper_type}")

    workspace_id = _normalize_workspace_id(workspace_id)
    if workspace_id:
      literature_store._verify_workspace(workspace_id, user_id)

    now = datetime.now()
    project_id = str(uuid.uuid4())
    section_types = DEFAULT_SECTIONS.get(paper_type, DEFAULT_SECTIONS["journal"])

    with get_session() as session:
      project = WritingProjectRecord(
        id=project_id,
        user_id=user_id,
        title=title,
        topic=topic,
        paper_type=paper_type,
        target_journal=target_journal,
        source_workflow_id=source_workflow_id,
        workspace_id=workspace_id,
        outline_json=json.dumps(outline or [], ensure_ascii=False),
        citation_format="gb7714",
        created_at=now,
        updated_at=now,
      )
      session.add(project)

      for idx, section_type in enumerate(section_types):
        section = WritingSectionRecord(
          id=str(uuid.uuid4()),
          project_id=project_id,
          section_type=section_type,
          title="",
          sort_order=idx,
          is_custom=False,
          content="",
          word_count=0,
          version=1,
          created_at=now,
          updated_at=now,
        )
        session.add(section)
        session.add(WritingSectionVersionRecord(
          id=str(uuid.uuid4()),
          section_id=section.id,
          content="",
          word_count=0,
          version=1,
          note="初始版本",
          created_at=now,
        ))

      session.commit()
      return self.get_project(project_id, user_id)

  def update_project(
    self,
    project_id: str,
    user_id: str,
    *,
    title: str | None = None,
    topic: str | None = None,
    paper_type: str | None = None,
    target_journal: str | None = None,
    workspace_id: str | None = None,
    outline: list | None = None,
    keywords_zh: list | None = None,
    keywords_en: list | None = None,
    citation_format: str | None = None,
  ) -> dict:
    self._verify_project(project_id, user_id)
    with get_session() as session:
      project = session.get(WritingProjectRecord, project_id)
      if title is not None:
        project.title = title
      if topic is not None:
        project.topic = topic
      if paper_type is not None:
        if paper_type not in PAPER_TEMPLATES:
          raise ValueError(f"不支持的论文类型: {paper_type}")
        project.paper_type = paper_type
      if target_journal is not None:
        project.target_journal = target_journal
      if workspace_id is not None:
        normalized = _normalize_workspace_id(workspace_id)
        if normalized:
          literature_store._verify_workspace(normalized, user_id)
        project.workspace_id = normalized
      if outline is not None:
        project.outline_json = json.dumps(outline, ensure_ascii=False)
      if keywords_zh is not None:
        project.keywords_zh_json = json.dumps(keywords_zh, ensure_ascii=False)
      if keywords_en is not None:
        project.keywords_en_json = json.dumps(keywords_en, ensure_ascii=False)
      if citation_format is not None:
        project.citation_format = citation_format
      project.updated_at = datetime.now()
      session.commit()
      return self.get_project(project_id, user_id)

  def delete_project(self, project_id: str, user_id: str) -> None:
    self._verify_project(project_id, user_id)
    with get_session() as session:
      sections = session.scalars(
        select(WritingSectionRecord).where(WritingSectionRecord.project_id == project_id)
      ).all()
      section_ids = [s.id for s in sections]
      if section_ids:
        session.execute(
          delete(WritingReferenceRecord).where(WritingReferenceRecord.section_id.in_(section_ids))
        )
        session.execute(
          delete(WritingSectionVersionRecord).where(
            WritingSectionVersionRecord.section_id.in_(section_ids)
          )
        )
      session.execute(delete(WritingSectionRecord).where(WritingSectionRecord.project_id == project_id))
      session.execute(delete(WritingProjectRecord).where(WritingProjectRecord.id == project_id))
      session.commit()

  def update_section(
    self,
    section_id: str,
    user_id: str,
    content: str,
    *,
    save_version: bool = True,
    version_note: str = "",
  ) -> dict:
    self._verify_section(section_id, user_id)
    content = ensure_paragraph_first_indent(content)
    now = datetime.now()
    word_count = _count_words(content)

    with get_session() as session:
      section = session.get(WritingSectionRecord, section_id)
      project = session.get(WritingProjectRecord, section.project_id)

      if save_version and section.content != content:
        new_version = section.version + 1
        session.add(WritingSectionVersionRecord(
          id=str(uuid.uuid4()),
          section_id=section_id,
          content=content,
          word_count=word_count,
          version=new_version,
          note=version_note or "手动保存",
          created_at=now,
        ))
        section.version = new_version

      section.content = content
      section.word_count = word_count
      section.updated_at = now
      project.updated_at = now
      session.commit()
      return self._serialize_section(section)

  def get_section_versions(self, section_id: str, user_id: str) -> list[dict]:
    self._verify_section(section_id, user_id)
    with get_session() as session:
      rows = session.scalars(
        select(WritingSectionVersionRecord)
        .where(WritingSectionVersionRecord.section_id == section_id)
        .order_by(WritingSectionVersionRecord.version.desc())
      ).all()
      return [{
        "id": v.id,
        "section_id": v.section_id,
        "content": v.content,
        "word_count": v.word_count,
        "version": v.version,
        "note": v.note,
        "created_at": v.created_at.isoformat(),
      } for v in rows]

  def compare_versions(self, section_id: str, user_id: str, version_a: int, version_b: int) -> dict:
    versions = self.get_section_versions(section_id, user_id)
    va = next((v for v in versions if v["version"] == version_a), None)
    vb = next((v for v in versions if v["version"] == version_b), None)
    if not va or not vb:
      raise ValueError("版本不存在")
    diff_lines = list(unified_diff(
      va["content"].splitlines(keepends=True),
      vb["content"].splitlines(keepends=True),
      fromfile=f"v{version_a}",
      tofile=f"v{version_b}",
    ))
    return {
      "version_a": va,
      "version_b": vb,
      "diff": "".join(diff_lines),
    }

  def rollback_section(self, section_id: str, user_id: str, target_version: int) -> dict:
    versions = self.get_section_versions(section_id, user_id)
    target = next((v for v in versions if v["version"] == target_version), None)
    if not target:
      raise ValueError("目标版本不存在")
    return self.update_section(
      section_id,
      user_id,
      target["content"],
      save_version=True,
      version_note=f"回滚至 v{target_version}",
    )

  def get_ordered_literature_ids(self, project_id: str, user_id: str) -> list[str]:
    refs = self.list_references(project_id, user_id)
    return list(dict.fromkeys(r["literature_id"] for r in refs))

  def assign_citation_index(
    self,
    project_id: str,
    user_id: str,
    section_id: str,
    literature_id: str,
    citation_context: str = "",
  ) -> tuple[int, bool]:
    lit_ids = self.get_ordered_literature_ids(project_id, user_id)
    if literature_id in lit_ids:
      return lit_ids.index(literature_id) + 1, False
    self.add_reference(section_id, user_id, literature_id, citation_context)
    return len(lit_ids) + 1, True

  def sync_bibliography_section(
    self,
    project_id: str,
    user_id: str,
    bibliography: list[dict],
  ) -> dict | None:
    if not bibliography:
      return None

    project = self.get_project(project_id, user_id)
    sections = project["sections"]
    content = "\n\n".join(
      f"[{ref['index']}] {ref['formatted']}" for ref in bibliography
    )

    bib_section = next(
      (s for s in sections if s.get("title") == BIBLIOGRAPHY_SECTION_TITLE),
      None,
    )
    if bib_section:
      if bib_section["content"].strip() == content.strip():
        return bib_section
      return self.update_section(
        bib_section["id"],
        user_id,
        content,
        save_version=True,
        version_note="参考文献自动更新",
      )

    last_sec = sections[-1] if sections else None
    after_id = last_sec["id"] if last_sec else None
    new_sec = self.create_section(
      project_id,
      user_id,
      BIBLIOGRAPHY_SECTION_TITLE,
      after_section_id=after_id,
    )
    return self.update_section(
      new_sec["id"],
      user_id,
      content,
      save_version=True,
      version_note="参考文献自动生成",
    )

  def add_reference(
    self,
    section_id: str,
    user_id: str,
    literature_id: str,
    citation_context: str = "",
    position: int = 0,
  ) -> dict:
    self._verify_section(section_id, user_id)
    ref_id = str(uuid.uuid4())
    with get_session() as session:
      ref = WritingReferenceRecord(
        id=ref_id,
        section_id=section_id,
        literature_id=literature_id,
        citation_context=citation_context,
        position=position,
      )
      session.add(ref)
      session.commit()
      return {
        "id": ref.id,
        "section_id": ref.section_id,
        "literature_id": ref.literature_id,
        "citation_context": ref.citation_context,
        "position": ref.position,
      }

  def list_references(self, project_id: str, user_id: str) -> list[dict]:
    self._verify_project(project_id, user_id)
    with get_session() as session:
      sections = session.scalars(
        select(WritingSectionRecord).where(WritingSectionRecord.project_id == project_id)
      ).all()
      section_map = {s.id: s.section_type for s in sections}
      refs = session.scalars(
        select(WritingReferenceRecord).where(
          WritingReferenceRecord.section_id.in_(list(section_map.keys()) or [""])
        )
      ).all()
      return [{
        "id": r.id,
        "section_id": r.section_id,
        "section_type": section_map.get(r.section_id, ""),
        "literature_id": r.literature_id,
        "citation_context": r.citation_context,
        "position": r.position,
      } for r in refs]

  def delete_reference(self, ref_id: str, user_id: str) -> None:
    with get_session() as session:
      ref = session.get(WritingReferenceRecord, ref_id)
      if not ref:
        raise ValueError("引用不存在")
      self._verify_section(ref.section_id, user_id)
      session.delete(ref)
      session.commit()

  def create_section(
    self,
    project_id: str,
    user_id: str,
    title: str,
    *,
    after_section_id: str | None = None,
  ) -> dict:
    title = title.strip()
    if not title:
      raise ValueError("章节标题不能为空")
    self._verify_project(project_id, user_id)
    now = datetime.now()

    with get_session() as session:
      project = session.get(WritingProjectRecord, project_id)
      sections = list(session.scalars(
        select(WritingSectionRecord).where(WritingSectionRecord.project_id == project_id)
      ).all())
      sections = self._sort_sections(sections, project.paper_type)

      insert_at = len(sections)
      if after_section_id:
        for i, sec in enumerate(sections):
          if sec.id == after_section_id:
            insert_at = i + 1
            break

      for sec in sections[insert_at:]:
        sec.sort_order += 1

      section = WritingSectionRecord(
        id=str(uuid.uuid4()),
        project_id=project_id,
        section_type="custom",
        title=title,
        sort_order=insert_at,
        is_custom=True,
        content="",
        word_count=0,
        version=1,
        created_at=now,
        updated_at=now,
      )
      session.add(section)
      session.add(WritingSectionVersionRecord(
        id=str(uuid.uuid4()),
        section_id=section.id,
        content="",
        word_count=0,
        version=1,
        note="初始版本",
        created_at=now,
      ))
      project.updated_at = now
      session.commit()
      session.refresh(section)
      return self._serialize_section(section)

  def update_section_meta(
    self,
    section_id: str,
    user_id: str,
    *,
    title: str | None = None,
  ) -> dict:
    self._verify_section(section_id, user_id)
    with get_session() as session:
      section = session.get(WritingSectionRecord, section_id)
      project = session.get(WritingProjectRecord, section.project_id)
      if title is not None:
        title = title.strip()
        if not title:
          raise ValueError("章节标题不能为空")
        section.title = title
      section.updated_at = datetime.now()
      project.updated_at = datetime.now()
      session.commit()
      return self._serialize_section(section)

  def delete_section(self, section_id: str, user_id: str) -> None:
    section = self._verify_section(section_id, user_id)
    with get_session() as session:
      row = session.get(WritingSectionRecord, section_id)
      if not row.is_custom:
        raise ValueError("内置章节不可删除，可重命名或清空内容")
      project = session.get(WritingProjectRecord, row.project_id)
      session.execute(delete(WritingReferenceRecord).where(WritingReferenceRecord.section_id == section_id))
      session.execute(delete(WritingSectionVersionRecord).where(WritingSectionVersionRecord.section_id == section_id))
      session.delete(row)
      remaining = list(session.scalars(
        select(WritingSectionRecord).where(WritingSectionRecord.project_id == row.project_id)
      ).all())
      remaining = self._sort_sections(remaining, project.paper_type)
      for idx, sec in enumerate(remaining):
        sec.sort_order = idx
      project.updated_at = datetime.now()
      session.commit()

  def reorder_sections(self, project_id: str, user_id: str, section_ids: list[str]) -> dict:
    self._verify_project(project_id, user_id)
    with get_session() as session:
      sections = list(session.scalars(
        select(WritingSectionRecord).where(WritingSectionRecord.project_id == project_id)
      ).all())
      id_set = {s.id for s in sections}
      if set(section_ids) != id_set:
        raise ValueError("章节列表不完整或不属于该项目")
      order_map = {sid: idx for idx, sid in enumerate(section_ids)}
      project = session.get(WritingProjectRecord, project_id)
      for sec in sections:
        sec.sort_order = order_map[sec.id]
      project.updated_at = datetime.now()
      session.commit()
      return self.get_project(project_id, user_id)

  # ── 图表素材（writing_assets）──────────────────────────────

  def _asset_dir(self, project_id: str) -> Path:
    return PROJECT_ROOT / settings.writing_dir / project_id / "assets"

  def _serialize_asset(self, record: WritingAssetRecord) -> dict:
    source = _load_json(record.source_json, {})
    caption = record.caption or record.filename
    return {
      "id": record.id,
      "project_id": record.project_id,
      "kind": record.kind,
      "filename": record.filename,
      "caption": caption,
      "source": source,
      "created_at": record.created_at.isoformat(),
      "markdown_ref": f"![{caption}](cmasset://{record.id})",
    }

  def list_assets(self, project_id: str, user_id: str) -> list[dict]:
    self._verify_project(project_id, user_id)
    with get_session() as session:
      rows = session.scalars(
        select(WritingAssetRecord)
        .where(WritingAssetRecord.project_id == project_id)
        .order_by(WritingAssetRecord.created_at.asc())
      ).all()
      return [self._serialize_asset(r) for r in rows]

  def create_asset(
    self,
    project_id: str,
    user_id: str,
    *,
    kind: str,
    data: bytes,
    filename: str = "",
    caption: str = "",
    source: dict | None = None,
  ) -> dict:
    """把图表二进制写入项目资产目录并登记记录。"""
    if not data:
      raise ValueError("图表内容为空")
    self._verify_project(project_id, user_id)

    now = datetime.now()
    asset_id = str(uuid.uuid4())
    raw_name = (filename or "").strip()
    ext = Path(raw_name).suffix.lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
      ext = ".png"
    stored_name = f"{asset_id}{ext}"
    asset_dir = self._asset_dir(project_id)
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / stored_name
    target.write_bytes(data)

    with get_session() as session:
      record = WritingAssetRecord(
        id=asset_id,
        project_id=project_id,
        kind=kind,
        filename=raw_name or stored_name,
        file_path=str(target.relative_to(PROJECT_ROOT))
        if _is_relative_to(target, PROJECT_ROOT)
        else str(target),
        caption=caption.strip(),
        source_json=json.dumps(source or {}, ensure_ascii=False),
        created_at=now,
      )
      session.add(record)
      session.commit()
      return self._serialize_asset(record)

  def get_asset(self, asset_id: str, user_id: str) -> tuple[dict, Path]:
    """返回 (资产字典, 磁盘绝对路径)，校验项目归属。"""
    with get_session() as session:
      record = session.get(WritingAssetRecord, asset_id)
      if not record:
        raise ValueError("图表素材不存在")
      project = session.get(WritingProjectRecord, record.project_id)
      if not project or project.user_id != user_id:
        raise ValueError("图表素材不存在或无权访问")
      path = self.resolve_asset_path(asset_id)
      if not path or not path.is_file():
        raise ValueError("图表文件已丢失")
      return self._serialize_asset(record), path

  def resolve_asset_path(self, asset_id: str) -> Path | None:
    """按 asset_id 解析磁盘路径（不校验用户，仅供导出/同项目内嵌使用）。"""
    with get_session() as session:
      record = session.get(WritingAssetRecord, asset_id)
      if not record:
        return None
      raw = record.file_path
      if not raw:
        return None
      path = Path(raw)
      if not path.is_absolute():
        path = PROJECT_ROOT / path
      return path


def _is_relative_to(path: Path, base: Path) -> bool:
  try:
    path.relative_to(base)
    return True
  except ValueError:
    return False


writing_store = WritingStore()
