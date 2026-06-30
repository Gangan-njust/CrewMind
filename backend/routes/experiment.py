"""实验数据管理 API 路由"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.experiment.analyzer import analyze_dataset, parse_upload
from backend.experiment.comparison import compare_expected_vs_actual
from backend.experiment.integration import create_from_workflow, get_workflow_experiment_output
from backend.storage.experiment_store import experiment_store
from backend.storage.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/experiment", tags=["experiment"])

ALLOWED_DATA_EXT = {".csv", ".xlsx", ".xls"}
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MAX_DATA_SIZE = 10 * 1024 * 1024
MAX_IMAGE_SIZE = 5 * 1024 * 1024


class ExperimentCreateRequest(BaseModel):
  title: str = Field(..., min_length=1, max_length=256)
  description: str = Field("", max_length=5000)
  source_workflow_id: str | None = None
  expected_metrics: list | None = None


class ExperimentUpdateRequest(BaseModel):
  title: str | None = Field(None, min_length=1, max_length=256)
  description: str | None = Field(None, max_length=5000)
  status: str | None = Field(None, pattern="^(active|completed|archived)$")
  expected_metrics: list | None = None


class EntryCreateRequest(BaseModel):
  title: str = Field("", max_length=256)
  step_name: str = Field("", max_length=256)
  notes: str = Field("", max_length=20000)
  instrument_params: dict = Field(default_factory=dict)
  raw_data: dict = Field(default_factory=dict)
  entry_type: str = Field("observation", pattern="^(observation|measurement|note)$")


class EntryUpdateRequest(BaseModel):
  title: str | None = Field(None, max_length=256)
  step_name: str | None = Field(None, max_length=256)
  notes: str | None = Field(None, max_length=20000)
  instrument_params: dict | None = None
  raw_data: dict | None = None
  entry_type: str | None = Field(None, pattern="^(observation|measurement|note)$")


class AnalyzeRequest(BaseModel):
  value_column: str | None = None
  group_column: str | None = None


class CompareRequest(BaseModel):
  dataset_id: str | None = None
  value_column: str | None = None


class FromWorkflowRequest(BaseModel):
  workflow_record_id: str
  title: str = Field("", max_length=256)
  description: str = Field("", max_length=5000)


def _file_type(filename: str) -> str:
  ext = Path(filename).suffix.lower()
  if ext == ".csv":
    return "csv"
  if ext == ".xlsx":
    return "xlsx"
  if ext == ".xls":
    return "xls"
  raise ValueError(f"不支持的文件格式: {ext}")


@router.get("/experiments")
async def list_experiments(current_user: User = Depends(get_current_user)):
  return experiment_store.list_experiments(current_user.id)


@router.post("/experiments")
async def create_experiment(req: ExperimentCreateRequest, current_user: User = Depends(get_current_user)):
  try:
    return experiment_store.create_experiment(
      current_user.id,
      title=req.title,
      description=req.description,
      source_workflow_id=req.source_workflow_id,
      expected_metrics=req.expected_metrics,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.get("/experiments/{experiment_id}")
async def get_experiment(experiment_id: str, current_user: User = Depends(get_current_user)):
  try:
    return experiment_store.get_experiment(experiment_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.patch("/experiments/{experiment_id}")
async def update_experiment(
  experiment_id: str,
  req: ExperimentUpdateRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return experiment_store.update_experiment(
      experiment_id,
      current_user.id,
      title=req.title,
      description=req.description,
      status=req.status,
      expected_metrics=req.expected_metrics,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.delete("/experiments/{experiment_id}")
async def delete_experiment(experiment_id: str, current_user: User = Depends(get_current_user)):
  try:
    experiment_store.delete_experiment(experiment_id, current_user.id)
    return {"status": "deleted", "id": experiment_id}
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/experiments/{experiment_id}/entries")
async def create_entry(
  experiment_id: str,
  req: EntryCreateRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return experiment_store.create_entry(
      experiment_id,
      current_user.id,
      title=req.title,
      step_name=req.step_name,
      notes=req.notes,
      instrument_params=req.instrument_params,
      raw_data=req.raw_data,
      entry_type=req.entry_type,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.patch("/entries/{entry_id}")
async def update_entry(
  entry_id: str,
  req: EntryUpdateRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return experiment_store.update_entry(
      entry_id,
      current_user.id,
      title=req.title,
      step_name=req.step_name,
      notes=req.notes,
      instrument_params=req.instrument_params,
      raw_data=req.raw_data,
      entry_type=req.entry_type,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: str, current_user: User = Depends(get_current_user)):
  try:
    experiment_store.delete_entry(entry_id, current_user.id)
    return {"status": "deleted", "id": entry_id}
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/entries/{entry_id}/attachments")
async def upload_attachment(
  entry_id: str,
  file: UploadFile = File(...),
  attachment_type: str = Query("photo", pattern="^(photo|document)$"),
  current_user: User = Depends(get_current_user),
):
  content = await file.read()
  if len(content) > MAX_IMAGE_SIZE:
    raise HTTPException(400, f"文件大小超过 {MAX_IMAGE_SIZE // 1024 // 1024}MB 限制")
  ext = Path(file.filename or "").suffix.lower()
  if ext not in ALLOWED_IMAGE_EXT and attachment_type == "photo":
    raise HTTPException(400, f"不支持的图片格式，允许: {', '.join(ALLOWED_IMAGE_EXT)}")
  mime = file.content_type or "application/octet-stream"
  try:
    return experiment_store.save_attachment(
      entry_id,
      current_user.id,
      filename=file.filename or "upload.jpg",
      content=content,
      mime_type=mime,
      attachment_type=attachment_type,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.get("/attachments/{attachment_id}/file")
async def get_attachment_file(
  attachment_id: str,
  token: str = Query(""),
):
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
    att, path = experiment_store.get_attachment(attachment_id, user.id)
    if not path.exists():
      raise HTTPException(404, "文件不存在")
    return FileResponse(path, media_type=att.mime_type, filename=att.filename)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(attachment_id: str, current_user: User = Depends(get_current_user)):
  try:
    experiment_store.delete_attachment(attachment_id, current_user.id)
    return {"status": "deleted", "id": attachment_id}
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/experiments/{experiment_id}/datasets")
async def upload_dataset(
  experiment_id: str,
  file: UploadFile = File(...),
  entry_id: str | None = Query(None),
  current_user: User = Depends(get_current_user),
):
  content = await file.read()
  if len(content) > MAX_DATA_SIZE:
    raise HTTPException(400, f"文件大小超过 {MAX_DATA_SIZE // 1024 // 1024}MB 限制")
  filename = file.filename or "data.csv"
  ext = Path(filename).suffix.lower()
  if ext not in ALLOWED_DATA_EXT:
    raise HTTPException(400, f"仅支持 CSV/Excel 格式: {', '.join(ALLOWED_DATA_EXT)}")

  import tempfile
  file_type = _file_type(filename)
  with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
    tmp.write(content)
    tmp_path = Path(tmp.name)

  try:
    parsed = parse_upload(tmp_path, file_type)
    ds = experiment_store.save_dataset(
      experiment_id,
      current_user.id,
      filename=filename,
      content=content,
      file_type=file_type,
      columns=parsed["columns"],
      row_count=parsed["row_count"],
      preview=parsed["preview"],
      entry_id=entry_id,
    )
    return ds
  except ValueError as e:
    raise HTTPException(400, str(e))
  finally:
    tmp_path.unlink(missing_ok=True)


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str, current_user: User = Depends(get_current_user)):
  try:
    experiment_store.delete_dataset(dataset_id, current_user.id)
    return {"status": "deleted", "id": dataset_id}
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.post("/datasets/{dataset_id}/analyze")
async def analyze_data(
  dataset_id: str,
  req: AnalyzeRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    ds, path = experiment_store.get_dataset_file(dataset_id, current_user.id)
    result = analyze_dataset(
      path,
      ds.file_type,
      value_column=req.value_column,
      group_column=req.group_column,
    )
    saved = experiment_store.save_analysis(
      dataset_id,
      current_user.id,
      config=result["config"],
      summary=result["summary"],
      charts=result["charts"],
      stats=result["stats"],
    )
    return saved
  except ValueError as e:
    raise HTTPException(400, str(e))
  except Exception as e:
    logger.exception("数据分析失败")
    raise HTTPException(500, f"数据分析失败: {e}")


@router.get("/datasets/{dataset_id}/analyses")
async def list_analyses(dataset_id: str, current_user: User = Depends(get_current_user)):
  try:
    return experiment_store.list_analyses(dataset_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: str, current_user: User = Depends(get_current_user)):
  try:
    return experiment_store.get_analysis(analysis_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.post("/experiments/{experiment_id}/compare")
async def compare_experiment(
  experiment_id: str,
  req: CompareRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return compare_expected_vs_actual(
      experiment_id,
      current_user.id,
      dataset_id=req.dataset_id,
      value_column=req.value_column,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.get("/workflow/{workflow_id}/expected")
async def get_workflow_expected(workflow_id: str, current_user: User = Depends(get_current_user)):
  try:
    return get_workflow_experiment_output(workflow_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.post("/from-workflow")
async def create_from_workflow_route(req: FromWorkflowRequest, current_user: User = Depends(get_current_user)):
  try:
    return await _create_from_workflow_async(current_user.id, req)
  except ValueError as e:
    raise HTTPException(400, str(e))


async def _create_from_workflow_async(user_id: str, req: FromWorkflowRequest):
  return create_from_workflow(
    user_id,
    req.workflow_record_id,
    title=req.title,
    description=req.description,
  )
