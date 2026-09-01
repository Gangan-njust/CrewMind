"""学术写作辅助 API 路由"""
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.storage.models import User
from backend.storage.writing_store import writing_store
from backend.writing.assistant import (
  apply_term_replacement,
  check_coherence,
  check_style,
  check_terminology,
  clean_blank_lines,
  expand_writing,
  polish_text,
  rule_based_style_check,
)
from backend.writing.abstract_keywords import (
  check_abstract_and_keywords,
  compose_abstract_content,
  generate_keywords_from_abstract,
  split_abstract_content,
)
from backend.writing.export import (
  build_docx,
  build_markdown,
  export_filename,
  get_bibliography_for_project,
)
from backend.writing.citations import (
  apply_citation,
  check_citation_completeness,
  format_all_references,
  generate_citation_sentences,
  recommend_citations,
)
from backend.writing.completion import complete_article_from_outline
from backend.writing.integration import create_from_workflow, fill_methods_from_workflow
from backend.writing.outline import generate_outline
from backend.writing.templates import CITATION_FORMATS, PAPER_TEMPLATES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/writing", tags=["writing"])


class ProjectCreateRequest(BaseModel):
  title: str = Field(..., min_length=1, max_length=256)
  topic: str = Field("", max_length=2000)
  paper_type: str = Field("journal", pattern="^(journal|conference|thesis)$")
  target_journal: str = Field("", max_length=256)
  workspace_id: str | None = None


class ProjectUpdateRequest(BaseModel):
  title: str | None = Field(None, min_length=1, max_length=256)
  topic: str | None = Field(None, max_length=2000)
  paper_type: str | None = Field(None, pattern="^(journal|conference|thesis)$")
  target_journal: str | None = Field(None, max_length=256)
  workspace_id: str | None = None
  outline: list | None = None
  keywords_zh: list[str] | None = None
  keywords_en: list[str] | None = None
  citation_format: str | None = Field(None, pattern="^(gb7714|apa|mla|chicago)$")


class SectionUpdateRequest(BaseModel):
  content: str = Field(...)
  save_version: bool = True
  version_note: str = ""


class SectionCreateRequest(BaseModel):
  title: str = Field(..., min_length=1, max_length=256)
  after_section_id: str | None = None


class SectionMetaUpdateRequest(BaseModel):
  title: str = Field(..., min_length=1, max_length=256)


class SectionReorderRequest(BaseModel):
  section_ids: list[str] = Field(..., min_length=1)


class OutlineGenerateRequest(BaseModel):
  topic: str = Field(..., min_length=5)
  paper_type: str = Field("journal", pattern="^(journal|conference|thesis)$")
  target_journal: str = ""
  source_workflow_id: str | None = None


class ContinueRequest(BaseModel):
  prefix: str = Field(..., min_length=5)
  section_type: str = "intro"
  context: str = ""
  length: str = Field("medium", pattern="^(short|medium|long)$")


class ExpandSubsectionItem(BaseModel):
  title: str = Field(..., min_length=1, max_length=256)
  level: int = Field(2, ge=2, le=4)
  word_target: int = Field(300, ge=50, le=8000)
  requirements: str = Field("", max_length=2000)
  existing_content: str = Field("", max_length=12000)
  outline_points: list[str] = Field(default_factory=list)
  enabled: bool = True


class ExpandRequest(BaseModel):
  text: str = Field("", max_length=50000)
  section_type: str = "intro"
  topic: str = ""
  length: str = Field("medium", pattern="^(short|medium|long)$")
  mode: str = Field("free", pattern="^(free|structured)$")
  global_requirements: str = Field("", max_length=2000)
  items: list[ExpandSubsectionItem] | None = None
  project_id: str | None = None


class CompleteOutlineRequest(BaseModel):
  global_requirements: str = Field("", max_length=2000)
  skip_filled: bool = True
  min_existing_words: int = Field(80, ge=0, le=5000)


class PolishRequest(BaseModel):
  text: str = Field("", max_length=50000)
  section_type: str = "intro"
  topic: str = ""
  style: str = Field("moderate", pattern="^(conservative|moderate|deep)$")
  mode: str = Field("free", pattern="^(free|structured)$")
  global_requirements: str = Field("", max_length=2000)
  items: list[ExpandSubsectionItem] | None = None
  project_id: str | None = None


class TermReplaceRequest(BaseModel):
  full_text: str
  replacements: list[dict]


class CoherenceCheckRequest(BaseModel):
  project_id: str


class StyleCheckRequest(BaseModel):
  text: str = Field(..., min_length=1)
  section_type: str = "intro"


class BlankLinesCheckRequest(BaseModel):
  text: str = Field(default="")


class CitationRecommendRequest(BaseModel):
  selected_text: str = Field(..., min_length=1)
  context: str = ""
  project_id: str


class CitationSentenceRequest(BaseModel):
  literature_id: str
  purpose: str = ""


class CitationCompletenessRequest(BaseModel):
  project_id: str


class CitationApplyRequest(BaseModel):
  project_id: str
  section_id: str
  literature_id: str
  selected_text: str = ""
  purpose: str = ""


class ReferenceAddRequest(BaseModel):
  literature_id: str
  citation_context: str = ""
  position: int = 0


class RollbackRequest(BaseModel):
  target_version: int = Field(..., ge=1)


class CompareRequest(BaseModel):
  version_a: int = Field(..., ge=1)
  version_b: int = Field(..., ge=1)


class FromWorkflowRequest(BaseModel):
  workflow_record_id: str
  title: str = ""
  paper_type: str = Field("journal", pattern="^(journal|conference|thesis)$")
  target_journal: str = ""
  workspace_id: str | None = None


class FillMethodsRequest(BaseModel):
  workflow_record_id: str


def _get_project_topic(project_id: str, user_id: str) -> tuple[dict, str]:
  project = writing_store.get_project(project_id, user_id)
  return project, project.get("topic", "")


# ── 模板信息 ──────────────────────────────────────────────────

@router.get("/templates")
async def list_templates(current_user: User = Depends(get_current_user)):
  return {
    "paper_types": PAPER_TEMPLATES,
    "citation_formats": CITATION_FORMATS,
  }


# ── 写作项目 CRUD ─────────────────────────────────────────────

@router.get("/projects")
async def list_projects(current_user: User = Depends(get_current_user)):
  return writing_store.list_projects(current_user.id)


@router.post("/projects")
async def create_project(req: ProjectCreateRequest, current_user: User = Depends(get_current_user)):
  try:
    return writing_store.create_project(
      current_user.id,
      req.title,
      req.topic,
      req.paper_type,
      req.target_journal,
      workspace_id=req.workspace_id,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.get("/projects/{project_id}")
async def get_project(project_id: str, current_user: User = Depends(get_current_user)):
  try:
    return writing_store.get_project(project_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.put("/projects/{project_id}")
async def update_project(
  project_id: str,
  req: ProjectUpdateRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return writing_store.update_project(
      project_id,
      current_user.id,
      title=req.title,
      topic=req.topic,
      paper_type=req.paper_type,
      target_journal=req.target_journal,
      workspace_id=req.workspace_id,
      outline=req.outline,
      keywords_zh=req.keywords_zh,
      keywords_en=req.keywords_en,
      citation_format=req.citation_format,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, current_user: User = Depends(get_current_user)):
  try:
    writing_store.delete_project(project_id, current_user.id)
    return {"status": "deleted", "id": project_id}
  except ValueError as e:
    raise HTTPException(404, str(e))


# ── 章节编辑 ──────────────────────────────────────────────────

@router.put("/sections/{section_id}")
async def update_section(
  section_id: str,
  req: SectionUpdateRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return writing_store.update_section(
      section_id,
      current_user.id,
      req.content,
      save_version=req.save_version,
      version_note=req.version_note,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/projects/{project_id}/sections")
async def create_section(
  project_id: str,
  req: SectionCreateRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return writing_store.create_section(
      project_id,
      current_user.id,
      req.title,
      after_section_id=req.after_section_id,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.patch("/sections/{section_id}")
async def update_section_meta(
  section_id: str,
  req: SectionMetaUpdateRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return writing_store.update_section_meta(section_id, current_user.id, title=req.title)
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.delete("/sections/{section_id}")
async def delete_section(section_id: str, current_user: User = Depends(get_current_user)):
  try:
    writing_store.delete_section(section_id, current_user.id)
    return {"status": "deleted", "id": section_id}
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.put("/projects/{project_id}/sections/reorder")
async def reorder_sections(
  project_id: str,
  req: SectionReorderRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return writing_store.reorder_sections(project_id, current_user.id, req.section_ids)
  except ValueError as e:
    raise HTTPException(400, str(e))


# ── 大纲生成 ──────────────────────────────────────────────────

@router.post("/outline/generate")
async def generate_outline_api(
  req: OutlineGenerateRequest,
  current_user: User = Depends(get_current_user),
):
  source_content = ""
  if req.source_workflow_id:
    from backend.storage.results import result_store
    record = result_store.get(req.source_workflow_id, current_user.id)
    if record:
      from backend.writing.integration import _build_source_content
      source_content = _build_source_content(record)

  try:
    return await generate_outline(
      req.topic,
      req.paper_type,
      req.target_journal,
      source_content,
    )
  except Exception as e:
    raise HTTPException(500, f"大纲生成失败: {e}")


# ── 扩写 / 润色 / 检查 ──────────────────────────────────────

def _attachment_headers(filename: str) -> dict[str, str]:
  ascii_name = filename.encode("ascii", "ignore").decode() or "export"
  encoded_name = quote(filename)
  return {
    "Content-Disposition": (
      f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'
    ),
  }


@router.post("/expand")
async def expand_writing_api(req: ExpandRequest, current_user: User = Depends(get_current_user)):
  if req.mode == "free" and len(req.text.strip()) < 5:
    raise HTTPException(400, "请先输入章节内容再进行扩写")
  if req.mode == "structured" and not req.items:
    raise HTTPException(400, "目录扩写需要至少一个小节配置")
  try:
    workspace_id = None
    if req.project_id:
      project, _ = _get_project_topic(req.project_id, current_user.id)
      workspace_id = project.get("workspace_id")
    return await expand_writing(
      req.text,
      section_type=req.section_type,
      topic=req.topic,
      length=req.length,
      mode=req.mode,
      global_requirements=req.global_requirements,
      items=[item.model_dump() for item in req.items] if req.items else None,
      workspace_id=workspace_id,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/continue")
async def continue_writing_api(req: ContinueRequest, current_user: User = Depends(get_current_user)):
  """兼容旧接口，行为同扩写"""
  try:
    from backend.writing.assistant import continue_writing
    text = req.context.strip() if req.context.strip() else req.prefix
    return await expand_writing(
      text,
      section_type=req.section_type,
      topic="",
      length=req.length,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/projects/{project_id}/complete-outline")
async def complete_outline_api(
  project_id: str,
  req: CompleteOutlineRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    project = writing_store.get_project(project_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))

  try:
    outcome = await complete_article_from_outline(
      project,
      global_requirements=req.global_requirements,
      skip_filled=req.skip_filled,
      min_existing_words=req.min_existing_words,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))
  except Exception as e:
    logger.exception("全文目录补全失败")
    raise HTTPException(500, f"全文补全失败: {e}")

  for item in outcome["results"]:
    if item["status"] != "completed":
      continue
    writing_store.update_section(
      item["section_id"],
      current_user.id,
      item["content"],
      save_version=True,
      version_note="目录补全",
    )

  updated = writing_store.get_project(project_id, current_user.id)
  return {
    **outcome,
    "project": updated,
  }


@router.post("/polish")
async def polish_text_api(req: PolishRequest, current_user: User = Depends(get_current_user)):
  if req.mode == "free" and len(req.text.strip()) < 10:
    raise HTTPException(400, "请先输入章节内容再进行润色")
  if req.mode == "structured" and not req.items:
    raise HTTPException(400, "小节润色需要至少一个小节配置")
  try:
    workspace_id = None
    if req.project_id:
      project, _ = _get_project_topic(req.project_id, current_user.id)
      workspace_id = project.get("workspace_id")
    return await polish_text(
      req.text,
      section_type=req.section_type,
      topic=req.topic,
      style=req.style,
      mode=req.mode,
      global_requirements=req.global_requirements,
      items=[item.model_dump() for item in req.items] if req.items else None,
      workspace_id=workspace_id,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/check/terminology")
async def check_terminology_api(
  req: CoherenceCheckRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    project, _ = _get_project_topic(req.project_id, current_user.id)
    full_text = "\n\n".join(
      s["content"] for s in project["sections"] if s["content"]
    )
    return await check_terminology(full_text)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.post("/check/terminology/replace")
async def apply_term_replace_api(
  req: TermReplaceRequest,
  current_user: User = Depends(get_current_user),
):
  return await apply_term_replacement(req.full_text, req.replacements)


@router.post("/check/coherence")
async def check_coherence_api(
  req: CoherenceCheckRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    project, _ = _get_project_topic(req.project_id, current_user.id)
    return await check_coherence(project.get("outline", []), project["sections"])
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.post("/check/style")
async def check_style_api(req: StyleCheckRequest, current_user: User = Depends(get_current_user)):
  try:
    llm_result = await check_style(req.text, req.section_type)
    rule_issues = rule_based_style_check(req.text)
    existing = llm_result.get("issues", [])
    llm_result["issues"] = existing + rule_issues
    return llm_result
  except Exception as e:
    raise HTTPException(500, str(e))


@router.post("/check/blank-lines")
async def check_blank_lines_api(
  req: BlankLinesCheckRequest,
  current_user: User = Depends(get_current_user),
):
  return clean_blank_lines(req.text)


@router.post("/check/keywords/generate")
async def generate_keywords_api(
  req: CoherenceCheckRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    project, _ = _get_project_topic(req.project_id, current_user.id)
    abstract_zh = ""
    for sec in project["sections"]:
      if sec.get("section_type") == "abstract":
        abstract_zh = sec.get("content") or ""
        break
    result = await generate_keywords_from_abstract(abstract_zh, project.get("topic", ""))
    keywords_zh = result["keywords_zh"]
    writing_store.update_project(
      req.project_id,
      current_user.id,
      keywords_zh=keywords_zh,
    )
    abstract_body = result["abstract_body"]
    abstract_sec = next((s for s in project["sections"] if s.get("section_type") == "abstract"), None)
    if abstract_sec:
      composed = compose_abstract_content(abstract_body, keywords_zh, english=False)
      writing_store.update_section(
        abstract_sec["id"],
        current_user.id,
        composed,
        save_version=True,
        version_note="更新中文关键词",
      )
    updated = writing_store.get_project(req.project_id, current_user.id)
    return {
      "keywords_zh": keywords_zh,
      "abstract_body": abstract_body,
      "summary": f"已从摘要生成 {len(keywords_zh)} 个中文关键词",
      "project": updated,
    }
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/check/abstract-keywords")
async def check_abstract_keywords_api(
  req: CoherenceCheckRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    project, _ = _get_project_topic(req.project_id, current_user.id)
    result = await check_abstract_and_keywords(project)
    return {**result, "type": "abstract_keywords"}
  except ValueError as e:
    raise HTTPException(400, str(e))


# ── 引用功能 ──────────────────────────────────────────────────

@router.post("/citations/recommend")
async def recommend_citations_api(
  req: CitationRecommendRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    project, _ = _get_project_topic(req.project_id, current_user.id)
    return await recommend_citations(
      req.selected_text,
      req.context,
      project.get("workspace_id"),
    )
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.post("/citations/sentences")
async def citation_sentences_api(
  req: CitationSentenceRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return await generate_citation_sentences(req.literature_id, req.purpose)
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/citations/apply")
async def apply_citation_api(
  req: CitationApplyRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    writing_store.get_project(req.project_id, current_user.id)
    return await apply_citation(
      req.project_id,
      current_user.id,
      req.section_id,
      req.literature_id,
      req.selected_text,
      req.purpose,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/citations/completeness")
async def citation_completeness_api(
  req: CitationCompletenessRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    project, _ = _get_project_topic(req.project_id, current_user.id)
    full_text = "\n\n".join(
      f"## {s['section_type']}\n{s['content']}"
      for s in project["sections"] if s["content"]
    )
    return await check_citation_completeness(full_text)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/projects/{project_id}/references")
async def list_references(project_id: str, current_user: User = Depends(get_current_user)):
  try:
    return writing_store.list_references(project_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.post("/sections/{section_id}/references")
async def add_reference(
  section_id: str,
  req: ReferenceAddRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return writing_store.add_reference(
      section_id,
      current_user.id,
      req.literature_id,
      req.citation_context,
      req.position,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.delete("/references/{ref_id}")
async def delete_reference(ref_id: str, current_user: User = Depends(get_current_user)):
  try:
    writing_store.delete_reference(ref_id, current_user.id)
    return {"status": "deleted", "id": ref_id}
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/projects/{project_id}/bibliography")
async def format_bibliography(project_id: str, current_user: User = Depends(get_current_user)):
  try:
    project = writing_store.get_project(project_id, current_user.id)
    refs = writing_store.list_references(project_id, current_user.id)
    lit_ids = list(dict.fromkeys(r["literature_id"] for r in refs))
    fmt = project.get("citation_format", "gb7714")
    return {
      "format": fmt,
      "references": format_all_references(lit_ids, fmt),
    }
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/projects/{project_id}/export")
async def export_project(
  project_id: str,
  format: str = Query("md", pattern="^(md|docx)$"),
  include_bibliography: bool = Query(True),
  current_user: User = Depends(get_current_user),
):
  try:
    project = writing_store.get_project(project_id, current_user.id)
    bibliography = None
    if include_bibliography:
      bibliography = get_bibliography_for_project(project_id, current_user.id, project)

    if format == "docx":
      content = build_docx(project, bibliography)
      media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
      content = build_markdown(project, bibliography).encode("utf-8")
      media_type = "text/markdown; charset=utf-8"

    filename = export_filename(project, format)
    return Response(
      content=content,
      media_type=media_type,
      headers=_attachment_headers(filename),
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


# ── 版本管理 ──────────────────────────────────────────────────

@router.get("/sections/{section_id}/versions")
async def get_section_versions(section_id: str, current_user: User = Depends(get_current_user)):
  try:
    return writing_store.get_section_versions(section_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.post("/sections/{section_id}/compare")
async def compare_versions(
  section_id: str,
  req: CompareRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return writing_store.compare_versions(
      section_id, current_user.id, req.version_a, req.version_b
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/sections/{section_id}/rollback")
async def rollback_section(
  section_id: str,
  req: RollbackRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return writing_store.rollback_section(section_id, current_user.id, req.target_version)
  except ValueError as e:
    raise HTTPException(400, str(e))


# ── 与现有功能集成 ────────────────────────────────────────────

@router.post("/projects/from-workflow")
async def create_from_workflow_api(
  req: FromWorkflowRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return await create_from_workflow(
      current_user.id,
      req.workflow_record_id,
      title=req.title,
      paper_type=req.paper_type,
      target_journal=req.target_journal,
      workspace_id=req.workspace_id,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/projects/{project_id}/fill-methods")
async def fill_methods_api(
  project_id: str,
  req: FillMethodsRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return await fill_methods_from_workflow(
      project_id, current_user.id, req.workflow_record_id
    )
  except ValueError as e:
    raise HTTPException(400, str(e))
