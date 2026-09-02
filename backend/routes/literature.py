"""智能文献阅读助手 API 路由"""
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.auth import decode_token, get_current_user, get_user_by_id
from backend.llm.client import set_llm_run_context
from backend.literature.analyzer import analyze_batch, get_analysis_progress, identify_research_gaps
from backend.literature.export import export_bibtex, export_endnote_xml, export_references
from backend.literature.filter import filter_literatures, search_literatures
from backend.literature.integration import build_literature_review_context, build_proposal_context
from backend.literature.selection import (
  clear_selection,
  get_selected_ids,
  list_selection_templates,
  save_selection_template,
  select_all,
  set_selected_ids,
  toggle_selection,
)
from backend.storage.literature_store import literature_store
from backend.storage.models import User
from backend.utils.text import sanitize_unicode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["literature"])


class WorkspaceCreateRequest(BaseModel):
  name: str = Field(..., min_length=1, max_length=256)
  description: str = Field("", max_length=2000)


class WorkspaceUpdateRequest(BaseModel):
  name: str = Field(..., min_length=1, max_length=256)
  description: str = Field("", max_length=2000)


class AnalyzeRequest(BaseModel):
  literature_ids: list[str] = Field(default_factory=list, description="空列表表示分析全部待分析文献")
  user_topic: str | None = None


class SelectRequest(BaseModel):
  literature_ids: list[str] = Field(..., min_length=0)


class SaveSelectionRequest(BaseModel):
  selection_name: str = Field(..., min_length=1, max_length=256)
  literature_ids: list[str] = Field(default_factory=list)


class AnalysisUpdateRequest(BaseModel):
  tags: list[str] | None = None
  contribution_summary: str | None = None
  relevance_score: float | None = None
  recommendation_score: float | None = None
  key_findings: list[str] | None = None
  limitations: list[str] | None = None
  citation_templates: list[dict] | None = None
  formulas: list[dict] | None = None
  results: dict | None = None
  images: list[dict] | None = None
  research_background: str | None = None
  research_goal: str | None = None
  methods_summary: str | None = None
  conclusion: str | None = None


class ProposalFromLiteratureRequest(BaseModel):
  workspace_id: str
  literature_ids: list[str] = Field(..., min_length=1)
  mode: str = Field("library_first", pattern="^(only_library|library_first|web_first)$")
  topic: str = Field(..., min_length=5)
  additional_requirements: str = ""
  selected_agents: list[str] = Field(default_factory=list, description="参与开题报告协作的 Agent 角色 ID")


class ReviewFromLiteratureRequest(BaseModel):
  workspace_id: str
  literature_ids: list[str] = Field(..., min_length=1)
  mode: str = Field("library_first", pattern="^(only_library|library_first|web_first)$")
  topic: str = Field(..., min_length=5, description="文献综述主题")
  additional_requirements: str = ""
  selected_agents: list[str] = Field(default_factory=list, description="参与文献综述协作的 Agent 角色 ID")


class RagSearchRequest(BaseModel):
  query: str = Field(..., min_length=1, max_length=2000)
  top_k: int | None = Field(None, ge=1, le=50)
  literature_ids: list[str] | None = None
  section_keys: list[str] | None = None
  mode: str = Field("vector", pattern="^(vector|hybrid)$")


class IndexLiteratureRequest(BaseModel):
  force: bool = False


class RagQueryRequest(BaseModel):
  question: str = Field(..., min_length=1, max_length=2000)
  literature_ids: list[str] | None = None
  stream: bool = False


class LiteratureConnectionManager:
  def __init__(self):
    self.active: dict[str, list[WebSocket]] = {}

  async def connect(self, workspace_id: str, ws: WebSocket):
    await ws.accept()
    self.active.setdefault(workspace_id, []).append(ws)

  def disconnect(self, workspace_id: str, ws: WebSocket):
    if workspace_id in self.active:
      self.active[workspace_id] = [c for c in self.active[workspace_id] if c != ws]

  async def broadcast(self, workspace_id: str, message: dict):
    for ws in self.active.get(workspace_id, []):
      try:
        await ws.send_json(message)
      except Exception:
        pass


literature_ws_manager = LiteratureConnectionManager()


async def _broadcast_progress(workspace_id: str, progress: dict):
  await literature_ws_manager.broadcast(workspace_id, {
    "type": "literature_analysis_progress",
    **progress,
  })


# ── 工作空间 API ──────────────────────────────────────────────

@router.get("/workspaces")
async def list_workspaces(current_user: User = Depends(get_current_user)):
  return literature_store.list_workspaces(current_user.id)


@router.post("/workspaces")
async def create_workspace(req: WorkspaceCreateRequest, current_user: User = Depends(get_current_user)):
  return literature_store.create_workspace(current_user.id, req.name, req.description)


@router.put("/workspaces/{workspace_id}")
async def update_workspace(
  workspace_id: str,
  req: WorkspaceUpdateRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return literature_store.update_workspace(workspace_id, current_user.id, req.name, req.description)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str, current_user: User = Depends(get_current_user)):
  try:
    literature_store.delete_workspace(workspace_id, current_user.id)
    return {"status": "deleted", "id": workspace_id}
  except ValueError as e:
    raise HTTPException(404, str(e))


# ── 文献上传与解析 ────────────────────────────────────────────

@router.post("/workspaces/{workspace_id}/literatures")
async def upload_literatures(
  workspace_id: str,
  files: list[UploadFile] = File(...),
  current_user: User = Depends(get_current_user),
):
  results = []
  for f in files:
    content = await f.read()
    try:
      meta = literature_store.upload_literature(
        workspace_id, current_user.id, f.filename or "paper.pdf", content
      )
      asyncio.create_task(_enrich_and_notify(workspace_id, meta["id"]))
      results.append(meta)
    except ValueError as e:
      raise HTTPException(400, str(e))
  return {"uploaded": results, "count": len(results)}


async def _enrich_and_notify(workspace_id: str, literature_id: str):
  try:
    await literature_store.enrich_metadata(literature_id)
  except Exception:
    pass


@router.get("/workspaces/{workspace_id}/literatures")
async def list_literatures(
  workspace_id: str,
  page: int = Query(1, ge=1),
  page_size: int = Query(50, ge=1, le=200),
  current_user: User = Depends(get_current_user),
):
  try:
    return literature_store.list_literatures(
      workspace_id, current_user.id, page=page, page_size=page_size
    )
  except ValueError as e:
    raise HTTPException(404, str(e))


# 静态子路径须放在 /{literature_id} 之前，避免 selected/filter 等被当成 ID

@router.post("/workspaces/{workspace_id}/literatures/analyze")
async def analyze_literatures(
  workspace_id: str,
  req: AnalyzeRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))

  ids = req.literature_ids
  if not ids:
    all_lits = literature_store.list_literatures(workspace_id, current_user.id)
    ids = [l["id"] for l in all_lits if l["status"] in ("pending", "failed")]

  if not ids:
    raise HTTPException(400, "没有待分析的文献")

  user_topic = req.user_topic
  if not user_topic:
    workspaces = literature_store.list_workspaces(current_user.id)
    ws = next((w for w in workspaces if w["id"] == workspace_id), None)
    user_topic = ws["name"] if ws else None

  async def run_analysis():
    async def report_progress(progress: dict):
      await _broadcast_progress(workspace_id, progress)

    await analyze_batch(ids, workspace_id, user_topic, on_progress=report_progress)

  set_llm_run_context(user_id=current_user.id, run_id=workspace_id, source="literature")
  asyncio.create_task(run_analysis())
  return {"status": "started", "literature_ids": ids, "total": len(ids)}


@router.get("/workspaces/{workspace_id}/literatures/analysis/progress")
async def get_analysis_progress_api(
  workspace_id: str,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))
  return get_analysis_progress(workspace_id)


@router.get("/workspaces/{workspace_id}/literatures/research-gaps")
async def get_research_gaps(
  workspace_id: str,
  topic: str = Query(..., min_length=3),
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
    set_llm_run_context(user_id=current_user.id, run_id=workspace_id, source="literature")
    return await identify_research_gaps(workspace_id, topic)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/workspaces/{workspace_id}/literatures/filter")
async def filter_literatures_api(
  workspace_id: str,
  keyword: str | None = None,
  tags: str | None = None,
  year_min: int | None = None,
  year_max: int | None = None,
  journal: str | None = None,
  author: str | None = None,
  min_relevance: float | None = None,
  status: str | None = None,
  sort_by: str = "uploaded_at",
  sort_order: str = "desc",
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))

  tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
  return filter_literatures(
    workspace_id,
    tags=tag_list,
    keyword=keyword,
    year_min=year_min,
    year_max=year_max,
    journal=journal,
    author=author,
    min_relevance=min_relevance,
    status=status,
    sort_by=sort_by,
    sort_order=sort_order,
  )


@router.get("/workspaces/{workspace_id}/literatures/search")
async def search_literatures_api(
  workspace_id: str,
  keyword: str | None = None,
  year_min: int | None = None,
  year_max: int | None = None,
  tags: str | None = None,
  min_relevance: float | None = None,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))

  tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
  return search_literatures(
    workspace_id,
    keyword=keyword,
    year_min=year_min,
    year_max=year_max,
    tags=tag_list,
    min_relevance=min_relevance,
  )


@router.post("/workspaces/{workspace_id}/literatures/select")
async def select_literatures(
  workspace_id: str,
  req: SelectRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
    ids = set_selected_ids(workspace_id, req.literature_ids)
    return {"selected_literature_ids": ids}
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/workspaces/{workspace_id}/literatures/selected")
async def get_selected_literatures(
  workspace_id: str,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
    ids = get_selected_ids(workspace_id)
    lits = literature_store.get_literatures_by_ids(workspace_id, ids)
    return {"selected_literature_ids": ids, "literatures": lits}
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/workspaces/{workspace_id}/literatures/export")
async def export_citations(
  workspace_id: str,
  format: str = Query("bibtex", pattern="^(bibtex|endnote|references|apa|gbt7714)$"),
  literature_ids: str | None = None,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
    if literature_ids:
      ids = [i.strip() for i in literature_ids.split(",") if i.strip()]
    else:
      ids = get_selected_ids(workspace_id)
    lits = literature_store.get_literatures_by_ids(workspace_id, ids)
    if not lits:
      raise HTTPException(400, "没有可导出的文献")

    if format == "bibtex":
      content = export_bibtex(lits)
      return {"format": "bibtex", "content": content}
    if format == "endnote":
      content = export_endnote_xml(lits)
      return {"format": "endnote", "content": content}
    style = "apa" if format == "apa" else "gbt7714"
    content = export_references(lits, style=style)
    return {"format": format, "content": content}
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/workspaces/{workspace_id}/literatures/{literature_id}")
async def get_literature(
  workspace_id: str,
  literature_id: str,
  current_user: User = Depends(get_current_user),
):
  try:
    return literature_store.get_literature(workspace_id, literature_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.delete("/workspaces/{workspace_id}/literatures/{literature_id}")
async def delete_literature(
  workspace_id: str,
  literature_id: str,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store.delete_literature(workspace_id, literature_id, current_user.id)
    return {"status": "deleted", "id": literature_id}
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/workspaces/{workspace_id}/literatures/{literature_id}/images/{filename}")
async def get_literature_image(
  workspace_id: str,
  literature_id: str,
  filename: str,
  token: str = Query(""),
):
  """返回从文献 PDF 中提取的图片文件。

  通过 token 查询参数鉴权（而非 Authorization 头），使 <img> 标签可直接内联展示图片。
  """
  from backend.auth import decode_token, get_user_by_id

  if not token:
    raise HTTPException(401, "未登录")
  try:
    payload = decode_token(token)
    user = get_user_by_id(payload.get("sub", ""))
    if not user:
      raise HTTPException(401, "用户不存在")
  except HTTPException:
    raise HTTPException(401, "登录已过期")

  try:
    literature_store._verify_workspace(workspace_id, user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))

  from backend.config import PROJECT_ROOT, settings
  from backend.storage.literature_store import _safe_filename

  safe_name = _safe_filename(filename)
  image_path = (
    PROJECT_ROOT / settings.literature_dir / workspace_id / literature_id / "images" / safe_name
  ).resolve()
  if not image_path.exists() or not image_path.is_file():
    raise HTTPException(404, "图片不存在")
  return FileResponse(str(image_path))


@router.get("/workspaces/{workspace_id}/literatures/{literature_id}/analysis")
async def get_literature_analysis(
  workspace_id: str,
  literature_id: str,
  current_user: User = Depends(get_current_user),
):
  try:
    lit = literature_store.get_literature(workspace_id, literature_id, current_user.id)
    return lit.get("analysis") or {}
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.put("/workspaces/{workspace_id}/literatures/{literature_id}/analysis")
async def update_literature_analysis(
  workspace_id: str,
  literature_id: str,
  req: AnalysisUpdateRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store.get_literature(workspace_id, literature_id, current_user.id)
    updates = req.model_dump(exclude_none=True)
    return literature_store.update_analysis(literature_id, current_user.id, updates)
  except ValueError as e:
    raise HTTPException(400, str(e))


# ── RAG 索引与检索 API ────────────────────────────────────────

@router.post("/workspaces/{workspace_id}/literatures/{literature_id}/index")
async def index_literature_api(
  workspace_id: str,
  literature_id: str,
  req: IndexLiteratureRequest = IndexLiteratureRequest(),
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store.get_literature(workspace_id, literature_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))

  from backend.rag.indexer import index_literature_async

  async def run_index():
    try:
      await index_literature_async(literature_id, force=req.force)
    except Exception as e:
      logger.exception("手动索引失败: %s", literature_id)

  asyncio.create_task(run_index())
  return {"status": "started", "literature_id": literature_id}


@router.get("/workspaces/{workspace_id}/literatures/{literature_id}/index-status")
async def get_index_status_api(
  workspace_id: str,
  literature_id: str,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store.get_literature(workspace_id, literature_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))

  from backend.rag.indexer import get_index_status

  status = get_index_status(literature_id)
  return status or {
    "literature_id": literature_id,
    "workspace_id": workspace_id,
    "status": "pending",
    "chunk_count": 0,
    "error_message": "",
  }


@router.post("/workspaces/{workspace_id}/rag/search")
async def rag_search_api(
  workspace_id: str,
  req: RagSearchRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))

  from backend.config import settings as app_settings
  if not app_settings.rag_enabled:
    raise HTTPException(400, "RAG 功能未启用")

  from backend.rag.retriever import search

  hits = search(
    workspace_id,
    req.query,
    mode=req.mode,
    top_k=req.top_k,
    literature_ids=req.literature_ids,
    section_keys=req.section_keys,
  )
  return {"query": req.query, "count": len(hits), "results": hits}


@router.get("/workspaces/{workspace_id}/rag/stats")
async def rag_stats_api(
  workspace_id: str,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))

  from backend.rag.indexer import get_workspace_stats

  return get_workspace_stats(workspace_id)


@router.post("/workspaces/{workspace_id}/rag/query")
async def rag_query_api(
  workspace_id: str,
  req: RagQueryRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))

  from backend.config import settings as app_settings
  if not app_settings.rag_enabled:
    raise HTTPException(400, "RAG 功能未启用")

  from backend.rag.query import answer_query, stream_query

  set_llm_run_context(user_id=current_user.id, run_id=workspace_id, source="literature")

  if req.stream:
    return StreamingResponse(
      stream_query(
        workspace_id,
        req.question,
        literature_ids=req.literature_ids,
      ),
      media_type="text/event-stream",
      headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

  try:
    return await answer_query(
      workspace_id,
      req.question,
      literature_ids=req.literature_ids,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/workspaces/{workspace_id}/selections/save")
async def save_selection(
  workspace_id: str,
  req: SaveSelectionRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
    ids = req.literature_ids or get_selected_ids(workspace_id)
    return save_selection_template(workspace_id, req.selection_name, ids)
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.get("/workspaces/{workspace_id}/selections")
async def list_selections(
  workspace_id: str,
  current_user: User = Depends(get_current_user),
):
  try:
    literature_store._verify_workspace(workspace_id, current_user.id)
    return list_selection_templates(workspace_id)
  except ValueError as e:
    raise HTTPException(404, str(e))


# ── 基于文献生成开题报告 ──────────────────────────────────────

def register_proposal_route(app, workflow_manager, ws_manager, attach_callback, finalize_crew):
  """注册开题报告生成路由（需 main.py 注入依赖）"""

  @app.post("/api/reports/proposal/from-literature")
  async def proposal_from_literature(
    req: ProposalFromLiteratureRequest,
    current_user: User = Depends(get_current_user),
  ):
    try:
      literature_store._verify_workspace(req.workspace_id, current_user.id)
    except ValueError as e:
      raise HTTPException(404, str(e))

    context = build_proposal_context(
      req.workspace_id, req.literature_ids, req.topic, req.mode  # type: ignore[arg-type]
    )
    user_input = sanitize_unicode(f"## 研究主题\n\n{req.topic}\n\n{context}")
    if req.additional_requirements:
      user_input += f"\n\n## 补充要求\n\n{sanitize_unicode(req.additional_requirements)}"

    if req.mode == "only_library":
      user_input += "\n\n**注意：仅使用用户文献库，禁止调用网络检索补充。**"
    elif req.mode == "web_first":
      user_input += "\n\n**注意：以网络检索为主，用户文献库为辅，须在文献数据库说明中区分来源。**"

    if not req.selected_agents:
      raise HTTPException(400, "请至少选择一个 Agent 角色")

    from backend.agents.roles import ScenarioType

    try:
      crew = await workflow_manager.start_workflow(
        scenario=ScenarioType.LITERATURE_BASED_PROPOSAL.value,
        user_input=user_input,
        user_id=current_user.id,
        selected_agents=req.selected_agents,
        workspace_id=req.workspace_id,
      )
    except ValueError as e:
      raise HTTPException(400, str(e))
    attach_callback(crew)
    set_llm_run_context(user_id=current_user.id, run_id=crew.id, source="workflow")

    async def run_crew():
      try:
        await crew.run()
        await finalize_crew(crew)
      except Exception as e:
        logger.exception("基于文献的开题报告生成失败")
        await ws_manager.broadcast(crew.id, {"type": "crew_failed", "error": str(e)})

    asyncio.create_task(run_crew())
    from backend.tasks.filtering import serialize_tasks

    return {
      "crew_id": crew.id,
      "status": "started",
      "scenario": crew.scenario,
      "tasks": serialize_tasks(crew.tasks),
    }


# ── 基于文献生成文献综述 ──────────────────────────────────────

def register_literature_review_route(app, workflow_manager, ws_manager, attach_callback, finalize_crew):
  """注册基于文献生成文献综述的路由（需 main.py 注入依赖）"""

  @app.post("/api/reports/literature-review/from-literature")
  async def literature_review_from_literature(
    req: ReviewFromLiteratureRequest,
    current_user: User = Depends(get_current_user),
  ):
    try:
      literature_store._verify_workspace(req.workspace_id, current_user.id)
    except ValueError as e:
      raise HTTPException(404, str(e))

    context = build_literature_review_context(
      req.workspace_id, req.literature_ids, req.topic, req.mode  # type: ignore[arg-type]
    )
    user_input = sanitize_unicode(f"{req.topic}\n\n{context}")
    if req.additional_requirements:
      user_input += f"\n\n## 补充要求\n\n{sanitize_unicode(req.additional_requirements)}"

    if req.mode == "only_library":
      user_input += "\n\n**注意：仅使用用户文献库，禁止调用网络检索补充。**"
    elif req.mode == "web_first":
      user_input += "\n\n**注意：以网络检索为主，用户文献库为辅，须在文献数据库说明中区分来源。**"

    if not req.selected_agents:
      raise HTTPException(400, "请至少选择一个 Agent 角色")

    from backend.agents.roles import ScenarioType

    try:
      crew = await workflow_manager.start_workflow(
        scenario=ScenarioType.LITERATURE_BASED_REVIEW.value,
        user_input=user_input,
        user_id=current_user.id,
        selected_agents=req.selected_agents,
        workspace_id=req.workspace_id,
      )
    except ValueError as e:
      raise HTTPException(400, str(e))
    attach_callback(crew)
    set_llm_run_context(user_id=current_user.id, run_id=crew.id, source="workflow")

    async def run_crew():
      try:
        await crew.run()
        await finalize_crew(crew)
      except Exception as e:
        logger.exception("基于文献的文献综述生成失败")
        await ws_manager.broadcast(crew.id, {"type": "crew_failed", "error": str(e)})

    asyncio.create_task(run_crew())
    from backend.tasks.filtering import serialize_tasks

    return {
      "crew_id": crew.id,
      "status": "started",
      "scenario": crew.scenario,
      "tasks": serialize_tasks(crew.tasks),
    }


# ── WebSocket 文献分析进度 ────────────────────────────────────

def register_literature_websocket(app):
  @app.websocket("/ws/literature/{workspace_id}")
  async def literature_ws(workspace_id: str, websocket: WebSocket, token: str = Query("")):
    if not token:
      await websocket.close(code=4001, reason="未登录")
      return
    try:
      payload = decode_token(token)
      user = get_user_by_id(payload.get("sub", ""))
      if not user:
        await websocket.close(code=4001, reason="用户不存在")
        return
      literature_store._verify_workspace(workspace_id, user.id)
    except HTTPException:
      await websocket.close(code=4001, reason="登录已过期")
      return
    except ValueError:
      await websocket.close(code=4004, reason="工作空间不存在")
      return

    set_llm_run_context(user_id=user.id, run_id=workspace_id, source="literature")
    await literature_ws_manager.connect(workspace_id, websocket)
    try:
      await websocket.send_json({
        "type": "literature_analysis_progress",
        **get_analysis_progress(workspace_id),
      })
      while True:
        import json
        data = await websocket.receive_text()
        msg = json.loads(data)
        if msg.get("type") == "ping":
          await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
      literature_ws_manager.disconnect(workspace_id, websocket)
