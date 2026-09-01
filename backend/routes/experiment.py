"""实验数据管理 API 路由"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from backend.auth import get_current_user, get_current_user_optional
from backend.experiment.analyzer import analyze_dataset, parse_upload
from backend.experiment.compare_multi import compare_experiments
from backend.experiment.comparison import compare_expected_vs_actual
from backend.experiment.integration import create_from_workflow, get_workflow_experiment_output
from backend.experiment.metrics import generate_metric_chart
from backend.experiment.reproduce import build_reproduce_manifest, build_reproduce_zip
from backend.storage.experiment_store import experiment_store
from backend.storage.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/experiment", tags=["experiment"])

ALLOWED_DATA_EXT = {".csv", ".xlsx", ".xls"}
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
ALLOWED_FILE_EXT = {".pt", ".pth", ".ckpt", ".onnx", ".pb", ".h5", ".json", ".yaml", ".yml",
                    ".log", ".txt", ".py", ".sh", ".csv", ".xlsx", ".xls", ".pkl", ".npz", ".zip"}
MAX_DATA_SIZE = 10 * 1024 * 1024
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_FILE_SIZE = 200 * 1024 * 1024


class ExperimentCreateRequest(BaseModel):
  title: str = Field(..., min_length=1, max_length=256)
  description: str = Field("", max_length=5000)
  source_workflow_id: str | None = None
  expected_metrics: list | None = None
  config: dict | None = None
  steps: list | None = None


class ExperimentUpdateRequest(BaseModel):
  title: str | None = Field(None, min_length=1, max_length=256)
  description: str | None = Field(None, max_length=5000)
  status: str | None = Field(None, pattern="^(planned|active|paused|completed|archived|failed)$")
  expected_metrics: list | None = None
  config: dict | None = None
  progress: int | None = Field(None, ge=0, le=100)
  current_step: str | None = Field(None, max_length=128)
  steps: list | None = None


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


class MetricItem(BaseModel):
  metric_name: str = Field(..., min_length=1, max_length=128)
  step: float = 0
  value: float = 0
  unit: str = Field("", max_length=32)


class MetricsRequest(BaseModel):
  items: list[MetricItem] = Field(..., min_length=1, max_length=500)


class MultiCompareRequest(BaseModel):
  experiment_ids: list[str] = Field(..., min_length=1, max_length=20)
  metric_names: list[str] | None = None


class ReproduceRequest(BaseModel):
  entrypoint: str = Field("", max_length=512)


def _file_type(filename: str) -> str:
  ext = Path(filename).suffix.lower()
  if ext == ".csv":
    return "csv"
  if ext == ".xlsx":
    return "xlsx"
  if ext == ".xls":
    return "xls"
  raise ValueError(f"不支持的文件格式: {ext}")


def _resolve_download_user(current_user: User | None, token: str) -> User:
  """支持 Authorization 头或 query token 两种认证方式（用于直接下载链接）"""
  if current_user:
    return current_user
  if not token:
    raise HTTPException(401, "未登录")
  from backend.auth import decode_token, get_user_by_id
  try:
    payload = decode_token(token)
    user = get_user_by_id(payload.get("sub", ""))
    if not user:
      raise HTTPException(401, "用户不存在")
    return user
  except HTTPException:
    raise HTTPException(401, "登录已过期")


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
      config=req.config,
      progress=req.progress,
      current_step=req.current_step,
      steps=req.steps,
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


# ───────────────────────── 实验配置管理 ─────────────────────────
@router.patch("/experiments/{experiment_id}/config")
async def update_experiment_config(
  experiment_id: str,
  req: ExperimentUpdateRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    if req.config is None:
      raise ValueError("config 不能为空")
    return experiment_store.save_config(experiment_id, current_user.id, req.config)
  except ValueError as e:
    raise HTTPException(400, str(e))


# ───────────────────────── 训练指标自动采集 ─────────────────────────
@router.post("/experiments/{experiment_id}/metrics")
async def record_metrics(
  experiment_id: str,
  req: MetricsRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    items = [m.model_dump() for m in req.items]
    return experiment_store.record_metrics(experiment_id, current_user.id, items)
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.get("/experiments/{experiment_id}/metrics")
async def list_metrics(
  experiment_id: str,
  metric_name: str | None = Query(None),
  current_user: User = Depends(get_current_user),
):
  try:
    return {
      "experiment_id": experiment_id,
      "metric_names": experiment_store.list_metric_names(experiment_id, current_user.id),
      "metrics": experiment_store.list_metrics(experiment_id, current_user.id, metric_name),
    }
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/experiments/{experiment_id}/metrics/chart")
async def metric_chart(
  experiment_id: str,
  metric_name: str = Query(...),
  current_user: User = Depends(get_current_user),
):
  try:
    points = experiment_store.list_metrics(experiment_id, current_user.id, metric_name)
    unit = ""
    for p in points:
      if p.get("unit"):
        unit = p["unit"]
        break
    return generate_metric_chart(metric_name, points, unit=unit)
  except ValueError as e:
    raise HTTPException(404, str(e))


# ───────────────────────── 实验文件管理（模型/日志/脚本） ─────────────────────────
@router.post("/experiments/{experiment_id}/files")
async def upload_experiment_file(
  experiment_id: str,
  file: UploadFile = File(...),
  file_type: str = Query("other", pattern="^(model|log|script|other)$"),
  current_user: User = Depends(get_current_user),
):
  content = await file.read()
  if not content:
    raise HTTPException(400, "文件为空")
  if len(content) > MAX_FILE_SIZE:
    raise HTTPException(400, f"文件超过大小上限 {MAX_FILE_SIZE // (1024 * 1024)}MB")
  ext = Path(file.filename or "").suffix.lower()
  if ext and ext not in ALLOWED_FILE_EXT:
    raise HTTPException(400, f"不支持的文件格式: {ext}")
  try:
    return experiment_store.save_file(
      experiment_id,
      current_user.id,
      filename=file.filename or "unnamed",
      content=content,
      file_type=file_type,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.get("/experiments/{experiment_id}/files")
async def list_experiment_files(experiment_id: str, current_user: User = Depends(get_current_user)):
  try:
    return experiment_store.list_files(experiment_id, current_user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.get("/files/{file_id}/download")
async def download_experiment_file(
  file_id: str,
  token: str = Query(""),
  current_user: User | None = Depends(get_current_user_optional),
):
  user = _resolve_download_user(current_user, token)
  try:
    f, path = experiment_store.get_file(file_id, user.id)
    if not path.exists():
      raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=f.filename)
  except ValueError as e:
    raise HTTPException(404, str(e))


@router.delete("/files/{file_id}")
async def delete_experiment_file(file_id: str, current_user: User = Depends(get_current_user)):
  try:
    experiment_store.delete_file(file_id, current_user.id)
    return {"status": "deleted", "id": file_id}
  except ValueError as e:
    raise HTTPException(400, str(e))


# ───────────────────────── 多实验对比分析 ─────────────────────────
@router.post("/experiments/compare-multi")
async def compare_multi_experiments(
  req: MultiCompareRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return compare_experiments(
      req.experiment_ids,
      current_user.id,
      metric_names=req.metric_names,
    )
  except ValueError as e:
    raise HTTPException(400, str(e))


# ───────────────────────── 一键复现 ─────────────────────────
@router.post("/experiments/{experiment_id}/reproduce")
async def build_reproduce(
  experiment_id: str,
  req: ReproduceRequest,
  current_user: User = Depends(get_current_user),
):
  try:
    return build_reproduce_manifest(experiment_id, current_user.id, entrypoint=req.entrypoint)
  except ValueError as e:
    raise HTTPException(400, str(e))


@router.get("/experiments/{experiment_id}/reproduce/download")
async def download_reproduce(
  experiment_id: str,
  token: str = Query(""),
  current_user: User | None = Depends(get_current_user_optional),
):
  user = _resolve_download_user(current_user, token)
  try:
    data, zip_name = build_reproduce_zip(experiment_id, user.id)
  except ValueError as e:
    raise HTTPException(404, str(e))
  return Response(
    content=data,
    media_type="application/zip",
    headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
  )
