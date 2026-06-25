"""步骤11：结果管理与历史方案库"""
import io
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import markdown
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt
from htmldocx import HtmlToDocx
from sqlalchemy import select

from backend.agents.roles import SCENARIO_LABELS, ScenarioType
from backend.config import PROJECT_ROOT, settings
from backend.storage.database import get_session, setup_database
from backend.storage.models import WorkflowRecord
from backend.tasks.definitions import TASK_FLOWS

logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 80


def generate_base_title(user_input: str, scenario: str) -> str:
  line = user_input.strip().split("\n")[0].strip()
  if not line:
    try:
      scenario_type = ScenarioType(scenario)
      return SCENARIO_LABELS[scenario_type]
    except ValueError:
      return scenario or "工作方案"
  if len(line) > TITLE_MAX_LENGTH:
    return line[:TITLE_MAX_LENGTH].rstrip() + "..."
  return line


def make_unique_title(
  session,
  user_id: str,
  base_title: str,
  created_at: datetime,
) -> str:
  existing = session.scalars(
    select(WorkflowRecord.title).where(
      WorkflowRecord.user_id == user_id,
      WorkflowRecord.title == base_title,
    )
  ).first()
  if existing:
    return f"{base_title} ({created_at.strftime('%Y-%m-%d %H:%M:%S')})"
  return base_title


class ResultStore:
  """结构化存储工作方案，支持历史检索与对比"""

  def __init__(self, legacy_dir: Path | None = None):
    setup_database()
    self.legacy_dir = legacy_dir or (PROJECT_ROOT / settings.results_dir)
    self._legacy_migrated = False

  def _ensure_legacy_migrated(self) -> None:
    if self._legacy_migrated:
      return
    self._migrate_legacy_files()
    self._legacy_migrated = True

  def save(
    self,
    crew_id: str,
    scenario: str,
    user_input: str,
    results: dict,
    user_id: str,
    metadata: dict | None = None,
  ) -> str:
    """保存工作方案，返回记录 ID"""
    self._ensure_legacy_migrated()
    record_id = str(uuid.uuid4())
    created_at = datetime.now()
    base_title = generate_base_title(user_input, scenario)

    with get_session() as session:
      title = make_unique_title(session, user_id, base_title, created_at)
      session.add(WorkflowRecord(
        id=record_id,
        crew_id=crew_id,
        user_id=user_id,
        scenario=scenario,
        title=title,
        user_input=user_input,
        created_at=created_at,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        tasks_json=json.dumps(results, ensure_ascii=False),
      ))
      session.commit()

    return record_id

  def list_records(
    self,
    user_id: str,
    scenario: str | None = None,
    search: str | None = None,
    limit: int = 50,
  ) -> list[dict]:
    self._ensure_legacy_migrated()
    with get_session() as session:
      stmt = (
        select(WorkflowRecord)
        .where(WorkflowRecord.user_id == user_id)
        .order_by(WorkflowRecord.created_at.desc())
      )
      if scenario:
        stmt = stmt.where(WorkflowRecord.scenario == scenario)
      if search:
        keyword = f"%{search.strip()}%"
        stmt = stmt.where(
          WorkflowRecord.title.ilike(keyword)
          | WorkflowRecord.user_input.ilike(keyword)
        )
      rows = session.scalars(stmt.limit(limit)).all()
      return [self._to_list_item(row) for row in rows]

  def get(self, record_id: str, user_id: str | None = None) -> dict | None:
    self._ensure_legacy_migrated()
    with get_session() as session:
      row = session.get(WorkflowRecord, record_id)
      if not row:
        return None
      if user_id is not None and row.user_id != user_id:
        return None
      return self._to_record(row)

  def compare(self, record_id_a: str, record_id_b: str, user_id: str) -> dict:
    """对比两个方案"""
    a = self.get(record_id_a, user_id)
    b = self.get(record_id_b, user_id)
    if not a or not b:
      raise ValueError("记录不存在")

    comparison = {
      "record_a": {"id": record_id_a, "created_at": a["created_at"], "scenario": a["scenario"]},
      "record_b": {"id": record_id_b, "created_at": b["created_at"], "scenario": b["scenario"]},
      "task_diffs": [],
    }

    all_task_ids = set(a.get("tasks", {}).keys()) | set(b.get("tasks", {}).keys())
    for tid in sorted(all_task_ids):
      task_a = a.get("tasks", {}).get(tid, {})
      task_b = b.get("tasks", {}).get(tid, {})
      comparison["task_diffs"].append({
        "task_id": tid,
        "status_a": task_a.get("status", "missing"),
        "status_b": task_b.get("status", "missing"),
        "output_length_a": len(task_a.get("output", "")),
        "output_length_b": len(task_b.get("output", "")),
      })

    return comparison

  def get_markdown(self, record_id: str, user_id: str) -> str | None:
    record = self.get(record_id, user_id)
    if not record:
      return None
    return self.build_markdown(record)

  def build_markdown(self, record: dict) -> str:
    scenario = record.get("scenario", "")
    scenario_label, task_names = self._resolve_scenario_meta(scenario)
    created_at = record.get("created_at", datetime.now().isoformat())
    try:
      created_display = datetime.fromisoformat(created_at).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
      created_display = created_at

    lines = [
      "# 工作方案",
      "",
      f"- **标题**: {record.get('title', '')}",
      f"- **场景**: {scenario_label}",
      f"- **创建时间**: {created_display}",
      f"- **用户需求**: {record.get('user_input', '')}",
      "",
    ]

    for tid, task in record.get("tasks", {}).items():
      title = task_names.get(tid, tid)
      lines.extend([
        "---",
        "",
        f"## {title}",
        "",
        f"**状态**: {task.get('status', 'unknown')}",
        "",
      ])
      if task.get("human_feedback"):
        lines.extend([
          "**人工审核意见**:",
          "",
          task["human_feedback"],
          "",
        ])
      if task.get("output"):
        lines.append(task["output"])
        lines.append("")
      elif task.get("error"):
        lines.extend([
          f"**错误**: {task['error']}",
          "",
        ])
      else:
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"

  def build_markdown_from_workflow(
    self,
    scenario: str,
    user_input: str,
    results: dict,
    created_at: str | None = None,
  ) -> str:
    record = {
      "scenario": scenario,
      "user_input": user_input,
      "created_at": created_at or datetime.now().isoformat(),
      "tasks": results,
    }
    return self.build_markdown(record)

  def build_docx(self, md_content: str) -> bytes:
    html = markdown.markdown(
      md_content,
      extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
    )
    document = Document()
    self._configure_docx_styles(document)
    HtmlToDocx().add_html_to_document(html, document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()

  def export_filename(self, scenario: str, ext: str) -> str:
    scenario_label, _ = self._resolve_scenario_meta(scenario)
    safe_label = "".join(c if c.isalnum() or c in "._-" else "_" for c in scenario_label)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"工作方案_{safe_label}_{timestamp}.{ext}"

  def _migrate_legacy_files(self) -> None:
    """将旧版 JSON 文件数据导入数据库（一次性）"""
    if not self.legacy_dir.exists():
      return

    from backend.auth import get_user_by_username

    admin = get_user_by_username("admin")
    admin_id = admin.id if admin else None

    imported = 0
    with get_session() as session:
      existing_ids = set(session.scalars(select(WorkflowRecord.id)).all())

      for json_path in self.legacy_dir.glob("*.json"):
        if json_path.name == "index.json":
          continue

        try:
          record = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
          logger.warning("跳过无效的历史文件 %s: %s", json_path.name, exc)
          continue

        record_id = record.get("id")
        if not record_id or record_id in existing_ids:
          continue

        created_at_raw = record.get("created_at")
        try:
          created_at = datetime.fromisoformat(created_at_raw)
        except (TypeError, ValueError):
          created_at = datetime.fromtimestamp(json_path.stat().st_mtime)

        session.add(WorkflowRecord(
          id=record_id,
          crew_id=record.get("crew_id", ""),
          user_id=admin_id,
          scenario=record.get("scenario", ""),
          title=record.get("title") or generate_base_title(
            record.get("user_input", ""),
            record.get("scenario", ""),
          ),
          user_input=record.get("user_input", ""),
          created_at=created_at,
          metadata_json=json.dumps(record.get("metadata") or {}, ensure_ascii=False),
          tasks_json=json.dumps(record.get("tasks") or {}, ensure_ascii=False),
        ))
        existing_ids.add(record_id)
        imported += 1

      if imported:
        session.commit()
        logger.info("已从 JSON 文件导入 %d 条历史方案到数据库", imported)

  @staticmethod
  def _to_list_item(row: WorkflowRecord) -> dict:
    tasks = json.loads(row.tasks_json or "{}")
    title = row.title or generate_base_title(row.user_input, row.scenario)
    return {
      "id": row.id,
      "title": title,
      "scenario": row.scenario,
      "user_input": row.user_input[:100],
      "created_at": row.created_at.isoformat(),
      "task_count": len(tasks),
    }

  @staticmethod
  def _to_record(row: WorkflowRecord) -> dict:
    title = row.title or generate_base_title(row.user_input, row.scenario)
    return {
      "id": row.id,
      "crew_id": row.crew_id,
      "title": title,
      "scenario": row.scenario,
      "user_input": row.user_input,
      "created_at": row.created_at.isoformat(),
      "metadata": json.loads(row.metadata_json or "{}"),
      "tasks": json.loads(row.tasks_json or "{}"),
    }

  def _resolve_scenario_meta(self, scenario: str) -> tuple[str, dict[str, str]]:
    try:
      scenario_type = ScenarioType(scenario)
      scenario_label = SCENARIO_LABELS[scenario_type]
      task_names = {task.id: task.name for task in TASK_FLOWS[scenario_type]}
      return scenario_label, task_names
    except (ValueError, KeyError):
      return scenario, {}

  @staticmethod
  def _configure_docx_styles(document: Document) -> None:
    normal = document.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    for style_name, size in [("Heading 1", 18), ("Heading 2", 15), ("Heading 3", 13)]:
      if style_name in document.styles:
        heading = document.styles[style_name]
        heading.font.name = "Microsoft YaHei"
        heading.font.size = Pt(size)
        heading._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

  def _build_markdown(self, record: dict) -> str:
    return self.build_markdown(record)


result_store = ResultStore()
