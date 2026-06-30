"""实验数据管理存储"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from backend.config import PROJECT_ROOT, settings
from backend.storage.database import get_session
from backend.storage.models import (
  ExperimentAnalysisRecord,
  ExperimentAttachmentRecord,
  ExperimentDatasetRecord,
  ExperimentEntryRecord,
  ExperimentRecord,
)


def _load_json(text: str, default=None):
  try:
    return json.loads(text or "null")
  except json.JSONDecodeError:
    return default if default is not None else []


def _experiment_dir(experiment_id: str) -> Path:
  return PROJECT_ROOT / settings.experiment_dir / experiment_id


class ExperimentStore:
  def _verify_experiment(self, experiment_id: str, user_id: str) -> ExperimentRecord:
    with get_session() as session:
      exp = session.get(ExperimentRecord, experiment_id)
      if not exp or exp.user_id != user_id:
        raise ValueError("实验不存在或无权访问")
      return exp

  def _verify_entry(self, entry_id: str, user_id: str) -> ExperimentEntryRecord:
    with get_session() as session:
      entry = session.get(ExperimentEntryRecord, entry_id)
      if not entry:
        raise ValueError("实验记录不存在")
      self._verify_experiment(entry.experiment_id, user_id)
      return entry

  def _verify_dataset(self, dataset_id: str, user_id: str) -> ExperimentDatasetRecord:
    with get_session() as session:
      ds = session.get(ExperimentDatasetRecord, dataset_id)
      if not ds:
        raise ValueError("数据集不存在")
      self._verify_experiment(ds.experiment_id, user_id)
      return ds

  def _serialize_experiment(self, exp: ExperimentRecord, *, entry_count: int = 0, dataset_count: int = 0) -> dict:
    return {
      "id": exp.id,
      "title": exp.title,
      "description": exp.description,
      "source_workflow_id": exp.source_workflow_id,
      "expected_metrics": _load_json(exp.expected_metrics_json, []),
      "status": exp.status,
      "entry_count": entry_count,
      "dataset_count": dataset_count,
      "created_at": exp.created_at.isoformat(),
      "updated_at": exp.updated_at.isoformat(),
    }

  def _serialize_entry(self, entry: ExperimentEntryRecord, attachments: list | None = None) -> dict:
    return {
      "id": entry.id,
      "experiment_id": entry.experiment_id,
      "title": entry.title,
      "step_name": entry.step_name,
      "notes": entry.notes,
      "instrument_params": _load_json(entry.instrument_params_json, {}),
      "raw_data": _load_json(entry.raw_data_json, {}),
      "entry_type": entry.entry_type,
      "created_at": entry.created_at.isoformat(),
      "updated_at": entry.updated_at.isoformat(),
      "attachments": attachments or [],
    }

  def _serialize_attachment(self, att: ExperimentAttachmentRecord) -> dict:
    return {
      "id": att.id,
      "entry_id": att.entry_id,
      "filename": att.filename,
      "mime_type": att.mime_type,
      "file_size": att.file_size,
      "attachment_type": att.attachment_type,
      "uploaded_at": att.uploaded_at.isoformat(),
      "url": f"/api/experiment/attachments/{att.id}/file",
    }

  def _serialize_dataset(self, ds: ExperimentDatasetRecord) -> dict:
    return {
      "id": ds.id,
      "experiment_id": ds.experiment_id,
      "entry_id": ds.entry_id,
      "filename": ds.filename,
      "file_type": ds.file_type,
      "columns": _load_json(ds.columns_json, []),
      "row_count": ds.row_count,
      "preview": _load_json(ds.preview_json, []),
      "uploaded_at": ds.uploaded_at.isoformat(),
    }

  def _serialize_analysis(self, analysis: ExperimentAnalysisRecord) -> dict:
    return {
      "id": analysis.id,
      "dataset_id": analysis.dataset_id,
      "config": _load_json(analysis.config_json, {}),
      "summary": _load_json(analysis.summary_json, {}),
      "charts": _load_json(analysis.charts_json, []),
      "stats": _load_json(analysis.stats_json, []),
      "created_at": analysis.created_at.isoformat(),
    }

  def list_experiments(self, user_id: str) -> list[dict]:
    with get_session() as session:
      rows = session.scalars(
        select(ExperimentRecord)
        .where(ExperimentRecord.user_id == user_id)
        .order_by(ExperimentRecord.updated_at.desc())
      ).all()
      result = []
      for exp in rows:
        entries = session.scalars(
          select(ExperimentEntryRecord).where(ExperimentEntryRecord.experiment_id == exp.id)
        ).all()
        datasets = session.scalars(
          select(ExperimentDatasetRecord).where(ExperimentDatasetRecord.experiment_id == exp.id)
        ).all()
        result.append(self._serialize_experiment(exp, entry_count=len(entries), dataset_count=len(datasets)))
      return result

  def create_experiment(
    self,
    user_id: str,
    *,
    title: str,
    description: str = "",
    source_workflow_id: str | None = None,
    expected_metrics: list | None = None,
  ) -> dict:
    now = datetime.now()
    exp_id = str(uuid.uuid4())
    with get_session() as session:
      exp = ExperimentRecord(
        id=exp_id,
        user_id=user_id,
        title=title,
        description=description,
        source_workflow_id=source_workflow_id,
        expected_metrics_json=json.dumps(expected_metrics or [], ensure_ascii=False),
        status="active",
        created_at=now,
        updated_at=now,
      )
      session.add(exp)
      session.commit()
    _experiment_dir(exp_id).mkdir(parents=True, exist_ok=True)
    return self.get_experiment(exp_id, user_id)

  def get_experiment(self, experiment_id: str, user_id: str) -> dict:
    with get_session() as session:
      exp = self._verify_experiment(experiment_id, user_id)
      entries = session.scalars(
        select(ExperimentEntryRecord)
        .where(ExperimentEntryRecord.experiment_id == experiment_id)
        .order_by(ExperimentEntryRecord.created_at.desc())
      ).all()
      datasets = session.scalars(
        select(ExperimentDatasetRecord)
        .where(ExperimentDatasetRecord.experiment_id == experiment_id)
        .order_by(ExperimentDatasetRecord.uploaded_at.desc())
      ).all()
      entry_data = []
      for entry in entries:
        attachments = session.scalars(
          select(ExperimentAttachmentRecord).where(ExperimentAttachmentRecord.entry_id == entry.id)
        ).all()
        entry_data.append(
          self._serialize_entry(entry, [self._serialize_attachment(a) for a in attachments])
        )
      data = self._serialize_experiment(exp, entry_count=len(entries), dataset_count=len(datasets))
      data["entries"] = entry_data
      data["datasets"] = [self._serialize_dataset(ds) for ds in datasets]
      return data

  def update_experiment(
    self,
    experiment_id: str,
    user_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    expected_metrics: list | None = None,
  ) -> dict:
    with get_session() as session:
      exp = session.get(ExperimentRecord, experiment_id)
      if not exp or exp.user_id != user_id:
        raise ValueError("实验不存在或无权访问")
      if title is not None:
        exp.title = title
      if description is not None:
        exp.description = description
      if status is not None:
        exp.status = status
      if expected_metrics is not None:
        exp.expected_metrics_json = json.dumps(expected_metrics, ensure_ascii=False)
      exp.updated_at = datetime.now()
      session.commit()
    return self.get_experiment(experiment_id, user_id)

  def delete_experiment(self, experiment_id: str, user_id: str) -> None:
    with get_session() as session:
      exp = session.get(ExperimentRecord, experiment_id)
      if not exp or exp.user_id != user_id:
        raise ValueError("实验不存在或无权访问")
      entries = session.scalars(
        select(ExperimentEntryRecord).where(ExperimentEntryRecord.experiment_id == experiment_id)
      ).all()
      entry_ids = [e.id for e in entries]
      if entry_ids:
        session.execute(
          delete(ExperimentAttachmentRecord).where(ExperimentAttachmentRecord.entry_id.in_(entry_ids))
        )
      datasets = session.scalars(
        select(ExperimentDatasetRecord).where(ExperimentDatasetRecord.experiment_id == experiment_id)
      ).all()
      for ds in datasets:
        session.execute(
          delete(ExperimentAnalysisRecord).where(ExperimentAnalysisRecord.dataset_id == ds.id)
        )
      session.execute(
        delete(ExperimentDatasetRecord).where(ExperimentDatasetRecord.experiment_id == experiment_id)
      )
      session.execute(
        delete(ExperimentEntryRecord).where(ExperimentEntryRecord.experiment_id == experiment_id)
      )
      session.delete(exp)
      session.commit()
    exp_dir = _experiment_dir(experiment_id)
    if exp_dir.exists():
      import shutil
      shutil.rmtree(exp_dir, ignore_errors=True)

  def create_entry(
    self,
    experiment_id: str,
    user_id: str,
    *,
    title: str = "",
    step_name: str = "",
    notes: str = "",
    instrument_params: dict | None = None,
    raw_data: dict | None = None,
    entry_type: str = "observation",
  ) -> dict:
    now = datetime.now()
    with get_session() as session:
      self._verify_experiment(experiment_id, user_id)
      entry = ExperimentEntryRecord(
        id=str(uuid.uuid4()),
        experiment_id=experiment_id,
        title=title,
        step_name=step_name,
        notes=notes,
        instrument_params_json=json.dumps(instrument_params or {}, ensure_ascii=False),
        raw_data_json=json.dumps(raw_data or {}, ensure_ascii=False),
        entry_type=entry_type,
        created_at=now,
        updated_at=now,
      )
      session.add(entry)
      exp = session.get(ExperimentRecord, experiment_id)
      exp.updated_at = now
      session.commit()
      return self._serialize_entry(entry)

  def update_entry(
    self,
    entry_id: str,
    user_id: str,
    *,
    title: str | None = None,
    step_name: str | None = None,
    notes: str | None = None,
    instrument_params: dict | None = None,
    raw_data: dict | None = None,
    entry_type: str | None = None,
  ) -> dict:
    with get_session() as session:
      entry = session.get(ExperimentEntryRecord, entry_id)
      if not entry:
        raise ValueError("实验记录不存在")
      exp = session.get(ExperimentRecord, entry.experiment_id)
      if not exp or exp.user_id != user_id:
        raise ValueError("无权访问")
      if title is not None:
        entry.title = title
      if step_name is not None:
        entry.step_name = step_name
      if notes is not None:
        entry.notes = notes
      if instrument_params is not None:
        entry.instrument_params_json = json.dumps(instrument_params, ensure_ascii=False)
      if raw_data is not None:
        entry.raw_data_json = json.dumps(raw_data, ensure_ascii=False)
      if entry_type is not None:
        entry.entry_type = entry_type
      now = datetime.now()
      entry.updated_at = now
      exp.updated_at = now
      session.commit()
      attachments = session.scalars(
        select(ExperimentAttachmentRecord).where(ExperimentAttachmentRecord.entry_id == entry_id)
      ).all()
      return self._serialize_entry(entry, [self._serialize_attachment(a) for a in attachments])

  def delete_entry(self, entry_id: str, user_id: str) -> None:
    with get_session() as session:
      entry = session.get(ExperimentEntryRecord, entry_id)
      if not entry:
        raise ValueError("实验记录不存在")
      exp = session.get(ExperimentRecord, entry.experiment_id)
      if not exp or exp.user_id != user_id:
        raise ValueError("无权访问")
      session.execute(
        delete(ExperimentAttachmentRecord).where(ExperimentAttachmentRecord.entry_id == entry_id)
      )
      session.delete(entry)
      session.commit()

  def save_attachment(
    self,
    entry_id: str,
    user_id: str,
    *,
    filename: str,
    content: bytes,
    mime_type: str,
    attachment_type: str = "photo",
  ) -> dict:
    entry = self._verify_entry(entry_id, user_id)
    att_id = str(uuid.uuid4())
    safe_name = Path(filename).name
    dest_dir = _experiment_dir(entry.experiment_id) / "attachments"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{att_id}_{safe_name}"
    dest_path.write_bytes(content)
    now = datetime.now()
    with get_session() as session:
      att = ExperimentAttachmentRecord(
        id=att_id,
        entry_id=entry_id,
        filename=safe_name,
        file_path=str(dest_path.relative_to(PROJECT_ROOT)),
        mime_type=mime_type,
        file_size=len(content),
        attachment_type=attachment_type,
        uploaded_at=now,
      )
      session.add(att)
      exp = session.get(ExperimentRecord, entry.experiment_id)
      exp.updated_at = now
      session.commit()
      return self._serialize_attachment(att)

  def get_attachment(self, attachment_id: str, user_id: str) -> tuple[ExperimentAttachmentRecord, Path]:
    with get_session() as session:
      att = session.get(ExperimentAttachmentRecord, attachment_id)
      if not att:
        raise ValueError("附件不存在")
      entry = session.get(ExperimentEntryRecord, att.entry_id)
      exp = session.get(ExperimentRecord, entry.experiment_id)
      if not exp or exp.user_id != user_id:
        raise ValueError("无权访问")
      return att, PROJECT_ROOT / att.file_path

  def delete_attachment(self, attachment_id: str, user_id: str) -> None:
    att, path = self.get_attachment(attachment_id, user_id)
    with get_session() as session:
      row = session.get(ExperimentAttachmentRecord, attachment_id)
      session.delete(row)
      session.commit()
    if path.exists():
      path.unlink()

  def save_dataset(
    self,
    experiment_id: str,
    user_id: str,
    *,
    filename: str,
    content: bytes,
    file_type: str,
    columns: list,
    row_count: int,
    preview: list,
    entry_id: str | None = None,
  ) -> dict:
    self._verify_experiment(experiment_id, user_id)
    ds_id = str(uuid.uuid4())
    safe_name = Path(filename).name
    dest_dir = _experiment_dir(experiment_id) / "datasets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{ds_id}_{safe_name}"
    dest_path.write_bytes(content)
    now = datetime.now()
    with get_session() as session:
      ds = ExperimentDatasetRecord(
        id=ds_id,
        experiment_id=experiment_id,
        entry_id=entry_id,
        filename=safe_name,
        file_path=str(dest_path.relative_to(PROJECT_ROOT)),
        file_type=file_type,
        columns_json=json.dumps(columns, ensure_ascii=False),
        row_count=row_count,
        preview_json=json.dumps(preview, ensure_ascii=False),
        uploaded_at=now,
      )
      session.add(ds)
      exp = session.get(ExperimentRecord, experiment_id)
      exp.updated_at = now
      session.commit()
      return self._serialize_dataset(ds)

  def get_dataset_file(self, dataset_id: str, user_id: str) -> tuple[ExperimentDatasetRecord, Path]:
    ds = self._verify_dataset(dataset_id, user_id)
    return ds, PROJECT_ROOT / ds.file_path

  def delete_dataset(self, dataset_id: str, user_id: str) -> None:
    ds, path = self.get_dataset_file(dataset_id, user_id)
    with get_session() as session:
      session.execute(
        delete(ExperimentAnalysisRecord).where(ExperimentAnalysisRecord.dataset_id == dataset_id)
      )
      row = session.get(ExperimentDatasetRecord, dataset_id)
      session.delete(row)
      session.commit()
    if path.exists():
      path.unlink()

  def save_analysis(
    self,
    dataset_id: str,
    user_id: str,
    *,
    config: dict,
    summary: dict,
    charts: list,
    stats: list,
  ) -> dict:
    self._verify_dataset(dataset_id, user_id)
    now = datetime.now()
    with get_session() as session:
      analysis = ExperimentAnalysisRecord(
        id=str(uuid.uuid4()),
        dataset_id=dataset_id,
        config_json=json.dumps(config, ensure_ascii=False),
        summary_json=json.dumps(summary, ensure_ascii=False),
        charts_json=json.dumps(charts, ensure_ascii=False),
        stats_json=json.dumps(stats, ensure_ascii=False),
        created_at=now,
      )
      session.add(analysis)
      session.commit()
      return self._serialize_analysis(analysis)

  def list_analyses(self, dataset_id: str, user_id: str) -> list[dict]:
    self._verify_dataset(dataset_id, user_id)
    with get_session() as session:
      rows = session.scalars(
        select(ExperimentAnalysisRecord)
        .where(ExperimentAnalysisRecord.dataset_id == dataset_id)
        .order_by(ExperimentAnalysisRecord.created_at.desc())
      ).all()
      return [self._serialize_analysis(a) for a in rows]

  def get_analysis(self, analysis_id: str, user_id: str) -> dict:
    with get_session() as session:
      analysis = session.get(ExperimentAnalysisRecord, analysis_id)
      if not analysis:
        raise ValueError("分析结果不存在")
      self._verify_dataset(analysis.dataset_id, user_id)
      return self._serialize_analysis(analysis)


experiment_store = ExperimentStore()
