"""文献选定功能"""
import json
import uuid
from datetime import datetime

from sqlalchemy import select

from backend.storage.database import get_session
from backend.storage.models import WorkspaceRecord, WorkspaceSelectionRecord


def get_selected_ids(workspace_id: str) -> list[str]:
  with get_session() as session:
    ws = session.get(WorkspaceRecord, workspace_id)
    if not ws:
      raise ValueError("工作空间不存在")
    return json.loads(ws.current_selected_ids_json or "[]")


def set_selected_ids(workspace_id: str, literature_ids: list[str]) -> list[str]:
  with get_session() as session:
    ws = session.get(WorkspaceRecord, workspace_id)
    if not ws:
      raise ValueError("工作空间不存在")
    ws.current_selected_ids_json = json.dumps(list(dict.fromkeys(literature_ids)))
    ws.updated_at = datetime.now()
    session.commit()
    return json.loads(ws.current_selected_ids_json)


def toggle_selection(workspace_id: str, literature_id: str, selected: bool) -> list[str]:
  ids = get_selected_ids(workspace_id)
  if selected and literature_id not in ids:
    ids.append(literature_id)
  elif not selected and literature_id in ids:
    ids.remove(literature_id)
  return set_selected_ids(workspace_id, ids)


def select_all(workspace_id: str, literature_ids: list[str]) -> list[str]:
  return set_selected_ids(workspace_id, literature_ids)


def clear_selection(workspace_id: str) -> list[str]:
  return set_selected_ids(workspace_id, [])


def save_selection_template(workspace_id: str, selection_name: str, literature_ids: list[str]) -> dict:
  with get_session() as session:
    ws = session.get(WorkspaceRecord, workspace_id)
    if not ws:
      raise ValueError("工作空间不存在")

    record = WorkspaceSelectionRecord(
      id=str(uuid.uuid4()),
      workspace_id=workspace_id,
      selected_literature_ids_json=json.dumps(literature_ids),
      selection_name=selection_name,
      created_at=datetime.now(),
    )
    session.add(record)
    session.commit()
    return {
      "id": record.id,
      "workspace_id": workspace_id,
      "selection_name": selection_name,
      "selected_literature_ids": literature_ids,
      "created_at": record.created_at.isoformat(),
    }


def list_selection_templates(workspace_id: str) -> list[dict]:
  with get_session() as session:
    rows = session.scalars(
      select(WorkspaceSelectionRecord)
      .where(WorkspaceSelectionRecord.workspace_id == workspace_id)
      .order_by(WorkspaceSelectionRecord.created_at.desc())
    ).all()
    return [
      {
        "id": r.id,
        "workspace_id": r.workspace_id,
        "selection_name": r.selection_name,
        "selected_literature_ids": json.loads(r.selected_literature_ids_json or "[]"),
        "created_at": r.created_at.isoformat(),
      }
      for r in rows
    ]
