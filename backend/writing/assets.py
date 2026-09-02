"""写作图表素材：从实验/文献聚合候选图，并把候选解析为可入库的图片文件。

正文引用语法：![图注](cmasset://{asset_id})。
"""
import base64
import logging
from pathlib import Path

from sqlalchemy import select

from backend.config import PROJECT_ROOT, settings
from backend.experiment.metrics import generate_metric_chart
from backend.storage.database import get_session
from backend.storage.experiment_store import experiment_store
from backend.storage.literature_store import literature_store, _safe_filename
from backend.storage.models import (
  ExperimentAnalysisRecord,
  ExperimentAttachmentRecord,
  ExperimentDatasetRecord,
  ExperimentRecord,
  LiteratureAnalysisRecord,
  LiteratureRecord,
)

logger = logging.getLogger(__name__)

def _safe_markdown_caption(raw: str, fallback: str) -> str:
  text = (raw or "").strip().replace("\n", " ").replace("]", "】").replace("[", "【")
  return text or fallback


def experiment_candidates(user_id: str, workflow_id: str | None) -> dict:
  """聚合与写作项目同源（source_workflow_id）的实验图表候选。"""
  result = {
    "charts": [],
    "metrics": [],
    "attachments": [],
  }
  if not workflow_id:
    return result

  with get_session() as session:
    experiments = session.scalars(
      select(ExperimentRecord)
      .where(
        ExperimentRecord.user_id == user_id,
        ExperimentRecord.source_workflow_id == workflow_id,
      )
      .order_by(ExperimentRecord.updated_at.desc())
    ).all()

    for exp in experiments[:5]:
      exp_id = exp.id
      exp_title = exp.title
      datasets = session.scalars(
        select(ExperimentDatasetRecord)
        .where(ExperimentDatasetRecord.experiment_id == exp_id)
        .order_by(ExperimentDatasetRecord.uploaded_at.asc())
      ).all()
      for ds in datasets:
        analyses = session.scalars(
          select(ExperimentAnalysisRecord)
          .where(ExperimentAnalysisRecord.dataset_id == ds.id)
          .order_by(ExperimentAnalysisRecord.created_at.asc())
        ).all()
        if analyses:
          analysis = analyses[-1]
          charts = _load_json_list(analysis.charts_json)
          for index, chart in enumerate(charts[:6]):
            result["charts"].append({
              "kind": "experiment_chart",
              "experiment_id": exp_id,
              "experiment_title": exp_title,
              "dataset_id": ds.id,
              "dataset_filename": ds.filename,
              "analysis_id": analysis.id,
              "chart_index": index,
              "chart_type": chart.get("type", ""),
              "title": _safe_markdown_caption(chart.get("title", ""), f"{exp_title} 图表"),
            })

      metric_names = experiment_store.list_metric_names(exp_id, user_id)
      for name in metric_names[:10]:
        result["metrics"].append({
          "kind": "experiment_metric",
          "experiment_id": exp_id,
          "experiment_title": exp_title,
          "metric_name": name,
          "title": f"{exp_title} · {name} 曲线",
        })

      attachments = session.scalars(
        select(ExperimentAttachmentRecord)
        .where(ExperimentAttachmentRecord.experiment_id == exp_id)
        .order_by(ExperimentAttachmentRecord.uploaded_at.asc())
      ).all()
      for att in attachments[:10]:
        result["attachments"].append({
          "kind": "experiment_attachment",
          "experiment_id": exp_id,
          "experiment_title": exp_title,
          "attachment_id": att.id,
          "filename": att.filename,
          "mime_type": att.mime_type,
          "url": f"/api/experiment/attachments/{att.id}/file",
        })
  return result


def _load_json_list(text: str) -> list:
  import json
  try:
    value = json.loads(text or "null")
    return value if isinstance(value, list) else []
  except json.JSONDecodeError:
    return []


def literature_candidates(user_id: str, workspace_id: str | None) -> list[dict]:
  """聚合写作项目已关联文献工作空间内可复用的文献图。"""
  if not workspace_id:
    return []
  try:
    literature_store._verify_workspace(workspace_id, user_id)
  except ValueError as e:
    logger.warning("写作项目文献工作空间校验失败: %s", e)
    return []

  result: list[dict] = []
  with get_session() as session:
    literatures = session.scalars(
      select(LiteratureRecord)
      .where(LiteratureRecord.workspace_id == workspace_id)
      .order_by(LiteratureRecord.uploaded_at.desc())
    ).all()
    for lit in literatures[:8]:
      analysis = session.scalars(
        select(LiteratureAnalysisRecord)
        .where(LiteratureAnalysisRecord.literature_id == lit.id)
        .order_by(LiteratureAnalysisRecord.created_at.desc())
      ).first()
      images = _load_json_list(analysis.images_json if analysis else "")
      for image in images[:5]:
        filename = str(image.get("filename", "")).strip()
        if not filename:
          continue
        result.append({
          "kind": "literature_image",
          "literature_id": lit.id,
          "literature_title": lit.title,
          "workspace_id": workspace_id,
          "filename": filename,
          "page": image.get("page"),
          "context": str(image.get("context", ""))[:160],
          "url": (
            f"/api/literature/workspaces/{workspace_id}/literatures/{lit.id}/images/"
            f"{filename}"
          ),
        })
  return result


def list_figure_candidates(project: dict, user_id: str) -> dict:
  """返回写作项目可用图表素材候选（扁平分组）。"""
  exp = experiment_candidates(user_id, project.get("source_workflow_id"))
  lit = literature_candidates(user_id, project.get("workspace_id"))
  payload = {
    "experiment_charts": exp["charts"],
    "experiment_metrics": exp["metrics"],
    "experiment_attachments": exp["attachments"],
    "literature_images": lit,
  }
  total = sum(len(v) for v in payload.values())
  payload["total"] = total
  payload["linked_experiment"] = bool(project.get("source_workflow_id"))
  payload["linked_workspace"] = bool(project.get("workspace_id"))
  return payload


def resolve_source_bytes(
  user_id: str,
  kind: str,
  source: dict,
  *,
  data_base64: str = "",
  caption: str = "",
) -> tuple[bytes, str, str, dict]:
  """按候选 kind 解析出图片二进制，返回 (bytes, filename, caption, meta)。

  校验素材归属后，从实验分析/指标曲线/实验附件/文献图/上传 base64 得到图片字节。
  """
  source = source or {}
  if kind == "experiment_chart":
    analysis_id = str(source.get("analysis_id") or "")
    chart_index = int(source.get("chart_index") or 0)
    analysis = experiment_store.get_analysis(analysis_id, user_id)
    charts = analysis.get("charts", [])
    if chart_index < 0 or chart_index >= len(charts):
      raise ValueError("图表索引越界")
    chart = charts[chart_index]
    image_b64 = chart.get("image_base64", "")
    if not image_b64:
      raise ValueError("实验分析未生成图表")
    title = _safe_markdown_caption(chart.get("title", ""), caption or "实验图表")
    return _decode_base64(image_b64), f"{title}.png", title or "实验图表", {
      "analysis_id": analysis_id,
      "chart_index": chart_index,
      "chart_type": chart.get("type", ""),
    }

  if kind == "experiment_metric":
    experiment_id = str(source.get("experiment_id") or "")
    metric_name = str(source.get("metric_name") or "").strip()
    if not experiment_id or not metric_name:
      raise ValueError("缺少实验与指标信息")
    points = experiment_store.list_metrics(experiment_id, user_id, metric_name)
    unit = ""
    for p in points:
      if p.get("unit"):
        unit = p["unit"]
        break
    chart = generate_metric_chart(metric_name, points, unit=unit)
    if not chart.get("image_base64"):
      raise ValueError("指标数据为空，无法生成曲线图")
    title = _safe_markdown_caption(caption, chart.get("title", f"{metric_name} 曲线"))
    return _decode_base64(chart["image_base64"]), f"{title}.png", title, {
      "experiment_id": experiment_id,
      "metric_name": metric_name,
      "unit": unit,
    }

  if kind == "experiment_attachment":
    attachment_id = str(source.get("attachment_id") or "")
    if not attachment_id:
      raise ValueError("缺少附件信息")
    record, path = experiment_store.get_attachment(attachment_id, user_id)
    filename = record.filename or f"{attachment_id}.png"
    title = _safe_markdown_caption(caption, Path(filename).stem)
    return path.read_bytes(), filename, title or filename, {
      "attachment_id": attachment_id,
      "filename": record.filename,
    }

  if kind == "literature_image":
    workspace_id = str(source.get("workspace_id") or "")
    literature_id = str(source.get("literature_id") or "")
    filename = str(source.get("filename") or "").strip()
    if not workspace_id or not literature_id or not filename:
      raise ValueError("缺少文献图片信息")
    literature_store._verify_workspace(workspace_id, user_id)
    safe_name = _safe_filename(filename)
    image_path = (
      PROJECT_ROOT / settings.literature_dir / workspace_id / literature_id / "images" / safe_name
    ).resolve()
    if not image_path.is_file():
      raise ValueError("文献图片文件已丢失")
    title = _safe_markdown_caption(caption, Path(safe_name).stem)
    return image_path.read_bytes(), safe_name, title or safe_name, {
      "workspace_id": workspace_id,
      "literature_id": literature_id,
      "filename": safe_name,
    }

  if kind == "upload":
    if not data_base64:
      raise ValueError("上传图表缺少 base64 内容")
    title = _safe_markdown_caption(caption, "上传图表")
    return _decode_base64(data_base64), f"{title}.png", title, {}

  raise ValueError(f"不支持的图表素材类型: {kind}")


def _decode_base64(data: str) -> bytes:
  try:
    return base64.b64decode(str(data or "").strip())
  except Exception as e:
    raise ValueError(f"图片数据解析失败: {e}")
