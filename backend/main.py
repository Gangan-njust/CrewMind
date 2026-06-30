"""FastAPI 后端 API 与 WebSocket 实时通信"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import settings, ENV_FILE
from backend.auth import (
  authenticate_user,
  create_access_token,
  create_user,
  get_current_user,
  serialize_user,
)
from backend.storage.models import User
from backend.agents.registry import (
  VALID_TOOLS,
  create_custom_agent,
  delete_custom_agent,
  update_custom_agent,
)
from backend.crew.manager import workflow_manager
from backend.storage.database import setup_database
from backend.tasks.definitions import TaskStatus
from backend.storage.results import result_store
from backend.storage.templates import template_store
from backend.storage.uploads import upload_store

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
  settings.ensure_dirs()
  setup_database()
  result_store._ensure_legacy_migrated()
  key = settings.deepseek_api_key
  if key:
    logger.info("DeepSeek API Key 已加载 (长度: %d)", len(key))
  else:
    logger.warning("DeepSeek API Key 未配置！请在 %s 中设置 DEEPSEEK_API_KEY", ENV_FILE)
  yield


app = FastAPI(
  title="CrewMind API",
  description="CrewMind · 智能科研协作平台 — 面向高校课题组与科研团队的多智能体协作平台",
  version="1.0.0",
  lifespan=lifespan,
)

app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)


# ── 请求/响应模型 ──────────────────────────────────────────────

class StartWorkflowRequest(BaseModel):
  scenario: str = Field(..., description="场景类型")
  user_input: str = Field(..., min_length=10, description="研究需求描述")
  reference_file_ids: list[str] = Field(default_factory=list, description="上传的参考文件 ID 列表")
  selected_agents: list[str] = Field(default_factory=list, description="参与协作的 Agent 角色 ID 列表")
  topic_id: str | None = Field(None, description="关联课题 ID，用于在同一课题下生成新版本")
  collaboration_mode: str = Field(
    "sequential",
    description="协作模式：sequential（串行）| debate（辩论）| voting（投票）",
  )


class AgentCreateRequest(BaseModel):
  id: str | None = Field(None, description="角色 ID（可选，默认自动生成）")
  name: str = Field(..., min_length=1, max_length=128)
  title: str = Field(..., min_length=1, max_length=256)
  background: str = Field(..., min_length=10)
  goal: str = Field(..., min_length=10)
  tools: list[str] = Field(default_factory=list)
  use_reasoning: bool = False


class AgentUpdateRequest(BaseModel):
  name: str = Field(..., min_length=1, max_length=128)
  title: str = Field(..., min_length=1, max_length=256)
  background: str = Field(..., min_length=10)
  goal: str = Field(..., min_length=10)
  tools: list[str] = Field(default_factory=list)
  use_reasoning: bool = False


class FeedbackRequest(BaseModel):
  task_id: str
  feedback: str = ""
  approved: bool = True


class CompareRequest(BaseModel):
  record_id_a: str
  record_id_b: str


class SetBestVersionRequest(BaseModel):
  record_id: str


class RegisterRequest(BaseModel):
  username: str = Field(..., min_length=3, max_length=64)
  password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
  username: str = Field(..., min_length=1)
  password: str = Field(..., min_length=1)


class TemplateCreateRequest(BaseModel):
  name: str = Field(..., min_length=1, max_length=128, description="模板名称")
  description: str = Field("", max_length=512, description="模板说明")
  scenario: str = Field(..., description="场景类型")
  user_input: str = Field(..., min_length=10, description="需求描述（可用 {{变量名}} 标记待填项）")
  selected_agents: list[str] = Field(default_factory=list, description="勾选的 Agent 列表")


# ── WebSocket 连接管理 ─────────────────────────────────────────

class ConnectionManager:
  def __init__(self):
    self.active: dict[str, list[WebSocket]] = {}

  async def connect(self, crew_id: str, ws: WebSocket):
    await ws.accept()
    self.active.setdefault(crew_id, []).append(ws)

  def disconnect(self, crew_id: str, ws: WebSocket):
    if crew_id in self.active:
      self.active[crew_id] = [c for c in self.active[crew_id] if c != ws]

  async def broadcast(self, crew_id: str, message: dict):
    for ws in self.active.get(crew_id, []):
      try:
        await ws.send_json(message)
      except Exception:
        pass


ws_manager = ConnectionManager()


def _attachment_headers(filename: str) -> dict[str, str]:
  ascii_name = filename.encode("ascii", "ignore").decode() or "export"
  encoded_name = quote(filename)
  return {
    "Content-Disposition": (
      f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'
    ),
  }


def _attach_event_callback(crew) -> None:
  async def event_callback(event_type: str, data: dict[str, Any]):
    await ws_manager.broadcast(crew.id, {"type": event_type, **data})

  crew._event_callback = event_callback


async def _finalize_crew(crew) -> None:
  if crew.status == "completed":
    result_store.save(
      crew_id=crew.id,
      scenario=crew.scenario,
      user_input=crew.user_input,
      user_id=crew.user_id,
      results=crew._serialize_results(),
      topic_id=crew.topic_id,
      metadata={"collaboration_mode": crew.collaboration_mode},
    )


# ── 认证 API ──────────────────────────────────────────────────

@app.post("/api/auth/register")
async def register(req: RegisterRequest):
  try:
    user = create_user(req.username, req.password)
  except ValueError as e:
    raise HTTPException(400, str(e))
  token = create_access_token(user.id, user.username)
  return {"token": token, "user": serialize_user(user)}


@app.post("/api/auth/login")
async def login(req: LoginRequest):
  user = authenticate_user(req.username, req.password)
  if not user:
    raise HTTPException(401, "用户名或密码错误")
  token = create_access_token(user.id, user.username)
  return {"token": token, "user": serialize_user(user)}


@app.get("/api/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
  return serialize_user(current_user)


# ── REST API ──────────────────────────────────────────────────

@app.get("/api/health")
async def health():
  return {"status": "ok", "version": "1.0.0"}


@app.get("/api/scenarios")
async def get_scenarios(current_user: User = Depends(get_current_user)):
  return workflow_manager.get_scenarios(current_user.id)


@app.get("/api/agents")
async def get_agents(current_user: User = Depends(get_current_user)):
  return workflow_manager.get_agents(current_user.id)


@app.get("/api/tools")
async def get_available_tools(current_user: User = Depends(get_current_user)):
  labels = {
    "web_search": "学术文献检索",
    "file_parser": "参考文件解析",
    "code_interpreter": "样本量与预算计算",
  }
  return [{"id": t, "label": labels.get(t, t)} for t in sorted(VALID_TOOLS)]


@app.post("/api/agents")
async def create_agent(req: AgentCreateRequest, current_user: User = Depends(get_current_user)):
  try:
    return create_custom_agent(
      user_id=current_user.id,
      agent_id=req.id,
      name=req.name,
      title=req.title,
      background=req.background,
      goal=req.goal,
      tools=req.tools,
      use_reasoning=req.use_reasoning,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@app.put("/api/agents/{agent_id}")
async def update_agent(
  agent_id: str, req: AgentUpdateRequest, current_user: User = Depends(get_current_user)
):
  try:
    return update_custom_agent(
      agent_id,
      user_id=current_user.id,
      name=req.name,
      title=req.title,
      background=req.background,
      goal=req.goal,
      tools=req.tools,
      use_reasoning=req.use_reasoning,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@app.delete("/api/agents/{agent_id}")
async def remove_agent(agent_id: str, current_user: User = Depends(get_current_user)):
  try:
    delete_custom_agent(agent_id, current_user.id)
    return {"status": "deleted", "id": agent_id}
  except ValueError as e:
    raise HTTPException(400, str(e))


@app.post("/api/uploads")
async def upload_reference_file(
  file: UploadFile = File(...), current_user: User = Depends(get_current_user)
):
  content = await file.read()
  try:
    meta = upload_store.save(content, file.filename or "upload.txt")
  except ValueError as e:
    raise HTTPException(400, str(e))
  return {
    "id": meta["id"],
    "filename": meta["filename"],
    "size": meta["size"],
  }


@app.get("/api/templates")
async def list_templates(current_user: User = Depends(get_current_user)):
  return template_store.list_templates(current_user.id)


@app.get("/api/templates/{template_id}")
async def get_template(template_id: str, current_user: User = Depends(get_current_user)):
  tpl = template_store.get_template(template_id, current_user.id)
  if not tpl:
    raise HTTPException(404, "模板不存在")
  return tpl


@app.post("/api/templates")
async def create_template(req: TemplateCreateRequest, current_user: User = Depends(get_current_user)):
  try:
    return template_store.create_template(
      user_id=current_user.id,
      name=req.name,
      description=req.description,
      scenario=req.scenario,
      user_input=req.user_input,
      selected_agents=req.selected_agents,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@app.delete("/api/templates/{template_id}")
async def delete_template(template_id: str, current_user: User = Depends(get_current_user)):
  try:
    template_store.delete_template(template_id, current_user.id)
    return {"status": "deleted", "id": template_id}
  except ValueError as e:
    raise HTTPException(400, str(e))


@app.get("/api/collaboration-modes")
async def get_collaboration_modes(current_user: User = Depends(get_current_user)):
  from backend.crew.collaboration import COLLABORATION_LABELS, CollaborationMode
  return [
    {"id": mode.value, "label": COLLABORATION_LABELS[mode]}
    for mode in CollaborationMode
  ]


@app.post("/api/workflow/start")
async def start_workflow(req: StartWorkflowRequest, current_user: User = Depends(get_current_user)):
  from backend.crew.collaboration import CollaborationMode

  try:
    CollaborationMode(req.collaboration_mode)
  except ValueError:
    raise HTTPException(400, f"无效的协作模式: {req.collaboration_mode}")

  crew = await workflow_manager.start_workflow(
    scenario=req.scenario,
    user_input=req.user_input,
    user_id=current_user.id,
    reference_file_ids=req.reference_file_ids,
    selected_agents=req.selected_agents or None,
    topic_id=req.topic_id,
    collaboration_mode=req.collaboration_mode,
  )

  _attach_event_callback(crew)

  async def run_crew():
    try:
      await crew.run()
      await _finalize_crew(crew)
    except Exception as e:
      logger.exception("Crew execution failed")
      await ws_manager.broadcast(crew.id, {"type": "crew_failed", "error": str(e)})

  asyncio.create_task(run_crew())

  from backend.tasks.filtering import serialize_tasks

  return {
    "crew_id": crew.id,
    "scenario": crew.scenario,
    "collaboration_mode": crew.collaboration_mode,
    "status": "started",
    "tasks": serialize_tasks(crew.tasks),
  }


@app.get("/api/workflow/{crew_id}")
async def get_workflow_status(crew_id: str, current_user: User = Depends(get_current_user)):
  crew = workflow_manager.get_crew(crew_id, current_user.id)
  if not crew:
    raise HTTPException(404, "工作流不存在")
  from backend.tasks.filtering import serialize_tasks

  return {
    "crew_id": crew.id,
    "scenario": crew.scenario,
    "collaboration_mode": crew.collaboration_mode,
    "status": crew.status,
    "user_input": crew.user_input,
    "results": crew._serialize_results(),
    "tasks": serialize_tasks(crew.tasks),
  }


@app.post("/api/workflow/{crew_id}/feedback")
async def submit_feedback(
  crew_id: str, req: FeedbackRequest, current_user: User = Depends(get_current_user)
):
  crew = workflow_manager.get_crew(crew_id, current_user.id)
  if not crew:
    raise HTTPException(404, "工作流不存在")

  result = crew.results.get(req.task_id)
  if not result:
    raise HTTPException(400, f"任务不存在: {req.task_id}")
  if crew.status != "paused":
    raise HTTPException(400, "工作流未处于待审核状态")
  if result.status != TaskStatus.WAITING_HUMAN:
    raise HTTPException(400, "该任务不在待审核状态")

  _attach_event_callback(crew)

  async def run_feedback():
    try:
      await crew.resume_with_feedback(req.task_id, req.feedback, req.approved)
      await _finalize_crew(crew)
    except Exception as e:
      logger.exception("Crew feedback resume failed")
      await ws_manager.broadcast(crew_id, {"type": "crew_failed", "error": str(e)})

  asyncio.create_task(run_feedback())
  return {"status": "resuming", "crew_id": crew_id}


@app.post("/api/workflow/{crew_id}/suspend")
async def suspend_workflow(crew_id: str, current_user: User = Depends(get_current_user)):
  try:
    return await workflow_manager.suspend_workflow(crew_id, current_user.id)
  except ValueError as e:
    raise HTTPException(400, str(e))


@app.post("/api/workflow/{crew_id}/resume")
async def resume_workflow(crew_id: str, current_user: User = Depends(get_current_user)):
  crew = workflow_manager.get_crew(crew_id, current_user.id)
  if not crew:
    raise HTTPException(404, "工作流不存在")
  if crew.status != "suspended":
    raise HTTPException(400, "工作流未处于中止状态，无法继续")

  _attach_event_callback(crew)

  async def run_resume():
    try:
      await crew.resume_execution()
      await _finalize_crew(crew)
    except Exception as e:
      logger.exception("Crew resume failed")
      await ws_manager.broadcast(crew_id, {"type": "crew_failed", "error": str(e)})

  asyncio.create_task(run_resume())
  return {"status": "resuming", "crew_id": crew_id}


@app.get("/api/results")
async def list_results(
  scenario: str | None = None,
  search: str | None = None,
  limit: int = 50,
  current_user: User = Depends(get_current_user),
):
  return result_store.list_records(current_user.id, scenario, search, limit)


@app.get("/api/topics")
async def list_topics(
  scenario: str | None = None,
  search: str | None = None,
  limit: int = 50,
  current_user: User = Depends(get_current_user),
):
  return result_store.list_topics(current_user.id, scenario, search, limit)


@app.get("/api/topics/{topic_id}")
async def get_topic(topic_id: str, current_user: User = Depends(get_current_user)):
  topic = result_store.get_topic(topic_id, current_user.id)
  if not topic:
    raise HTTPException(404, "课题不存在")
  return topic


@app.get("/api/topics/{topic_id}/versions")
async def list_topic_versions(topic_id: str, current_user: User = Depends(get_current_user)):
  try:
    return result_store.list_topic_versions(topic_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))


@app.post("/api/topics/{topic_id}/best")
async def set_best_version(
  topic_id: str,
  req: SetBestVersionRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return result_store.set_best_version(topic_id, req.record_id, current_user.id)
  except ValueError as e:
    raise HTTPException(400, str(e))


@app.get("/api/results/{record_id}")
async def get_result(record_id: str, current_user: User = Depends(get_current_user)):
  record = result_store.get(record_id, current_user.id)
  if not record:
    raise HTTPException(404, "记录不存在")
  return record


@app.get("/api/results/{record_id}/export")
async def export_result(
  record_id: str,
  format: str = Query("md", pattern="^(md|docx|tex)$"),
  scope: str = Query("full", pattern="^(full|proposal)$"),
  current_user: User = Depends(get_current_user),
):
  record = result_store.get(record_id, current_user.id)
  if not record:
    raise HTTPException(404, "记录不存在")

  filename = result_store.export_filename(record["scenario"], format, scope)

  try:
    if scope == "proposal":
      if format == "md":
        content = result_store.build_proposal_markdown(record)
        return Response(
          content=content.encode("utf-8"),
          media_type="text/markdown; charset=utf-8",
          headers=_attachment_headers(filename),
        )
      if format == "tex":
        content = result_store.build_proposal_latex(record)
        return Response(
          content=content.encode("utf-8"),
          media_type="application/x-tex; charset=utf-8",
          headers=_attachment_headers(filename),
        )
      md_content = result_store.build_proposal_markdown(record)
      docx_bytes = result_store.build_docx(md_content)
      return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=_attachment_headers(filename),
      )

    if format == "md":
      md_content = result_store.build_markdown(record)
      return Response(
        content=md_content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers=_attachment_headers(filename),
      )

    if format == "tex":
      tex_content = result_store.build_latex(record)
      return Response(
        content=tex_content.encode("utf-8"),
        media_type="application/x-tex; charset=utf-8",
        headers=_attachment_headers(filename),
      )

    md_content = result_store.build_markdown(record)
    docx_bytes = result_store.build_docx(md_content)
    return Response(
      content=docx_bytes,
      media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      headers=_attachment_headers(filename),
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@app.get("/api/workflow/{crew_id}/export")
async def export_workflow(
  crew_id: str,
  format: str = Query("md", pattern="^(md|docx|tex)$"),
  scope: str = Query("full", pattern="^(full|proposal)$"),
  current_user: User = Depends(get_current_user),
):
  crew = workflow_manager.get_crew(crew_id, current_user.id)
  if not crew:
    raise HTTPException(404, "工作流不存在")
  if crew.status not in ("completed", "failed"):
    raise HTTPException(400, "工作流尚未完成，暂无法导出")

  filename = result_store.export_filename(crew.scenario, format, scope)
  results = crew._serialize_results()
  task_order = [t.id for t in crew.tasks]

  try:
    if scope == "proposal":
      if format == "md":
        content = result_store.build_proposal_markdown_from_workflow(
          scenario=crew.scenario,
          user_input=crew.user_input,
          results=results,
          task_order=task_order,
        )
        return Response(
          content=content.encode("utf-8"),
          media_type="text/markdown; charset=utf-8",
          headers=_attachment_headers(filename),
        )
      if format == "tex":
        content = result_store.build_proposal_latex_from_workflow(
          scenario=crew.scenario,
          user_input=crew.user_input,
          results=results,
          task_order=task_order,
        )
        return Response(
          content=content.encode("utf-8"),
          media_type="application/x-tex; charset=utf-8",
          headers=_attachment_headers(filename),
        )
      md_content = result_store.build_proposal_markdown_from_workflow(
        scenario=crew.scenario,
        user_input=crew.user_input,
        results=results,
        task_order=task_order,
      )
      docx_bytes = result_store.build_docx(md_content)
      return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=_attachment_headers(filename),
      )

    if format == "md":
      md_content = result_store.build_markdown_from_workflow(
        scenario=crew.scenario,
        user_input=crew.user_input,
        results=results,
      )
      return Response(
        content=md_content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers=_attachment_headers(filename),
      )

    if format == "tex":
      tex_content = result_store.build_latex_from_workflow(
        scenario=crew.scenario,
        user_input=crew.user_input,
        results=results,
      )
      return Response(
        content=tex_content.encode("utf-8"),
        media_type="application/x-tex; charset=utf-8",
        headers=_attachment_headers(filename),
      )

    md_content = result_store.build_markdown_from_workflow(
      scenario=crew.scenario,
      user_input=crew.user_input,
      results=results,
    )
    docx_bytes = result_store.build_docx(md_content)
    return Response(
      content=docx_bytes,
      media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      headers=_attachment_headers(filename),
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@app.post("/api/results/compare")
async def compare_results(req: CompareRequest, current_user: User = Depends(get_current_user)):
  try:
    return result_store.compare(req.record_id_a, req.record_id_b, current_user.id)
  except ValueError as e:
    raise HTTPException(400, str(e))


# ── 智能文献阅读助手 API ───────────────────────────────────────

from backend.routes.literature import (
  register_literature_websocket,
  register_proposal_route,
  router as literature_router,
)

app.include_router(literature_router)
register_proposal_route(app, workflow_manager, ws_manager, _attach_event_callback, _finalize_crew)
register_literature_websocket(app)

from backend.routes.writing import router as writing_router

app.include_router(writing_router)

from backend.routes.experiment import router as experiment_router

app.include_router(experiment_router)


# ── WebSocket 实时事件 ─────────────────────────────────────────

@app.websocket("/ws/{crew_id}")
async def websocket_endpoint(crew_id: str, websocket: WebSocket, token: str = Query("")):
  from backend.auth import decode_token, get_user_by_id

  if not token:
    await websocket.close(code=4001, reason="未登录")
    return
  try:
    payload = decode_token(token)
    user = get_user_by_id(payload.get("sub", ""))
    if not user:
      await websocket.close(code=4001, reason="用户不存在")
      return
  except HTTPException:
    await websocket.close(code=4001, reason="登录已过期")
    return

  crew = workflow_manager.get_crew(crew_id, user.id)
  if not crew:
    await websocket.close(code=4004, reason="工作流不存在")
    return

  await ws_manager.connect(crew_id, websocket)
  try:
    await websocket.send_json({
      "type": "status",
      "crew_id": crew_id,
      "status": crew.status,
      "collaboration_mode": crew.collaboration_mode,
      "results": crew._serialize_results(),
    })

    while True:
      data = await websocket.receive_text()
      msg = json.loads(data)
      if msg.get("type") == "ping":
        await websocket.send_json({"type": "pong"})
  except WebSocketDisconnect:
    ws_manager.disconnect(crew_id, websocket)


# 挂载前端静态文件（生产模式）
import os
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
  app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
