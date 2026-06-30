"""与开题报告、实验方案、文献库的集成"""
import logging
import re

from backend.storage.database import get_session
from backend.storage.models import WritingProjectRecord
from backend.storage.results import result_store
from backend.storage.writing_store import writing_store
from backend.writing.outline import generate_outline

logger = logging.getLogger(__name__)

TASK_OUTPUT_KEYS = {
  "proposal": ["task_planning", "task_literature", "task_experiment", "task_budget"],
  "experiment": ["task_experiment", "task_planning"],
  "literature_based_proposal": [
    "task_planning", "task_literature", "task_experiment", "task_budget",
  ],
}


def _extract_task_outputs(record: dict, task_ids: list[str]) -> dict[str, str]:
  tasks = record.get("tasks", {})
  outputs = {}
  for tid in task_ids:
    task = tasks.get(tid, {})
    output = task.get("output", "")
    if output:
      outputs[tid] = output
  return outputs


def _build_source_content(record: dict) -> str:
  parts = [f"研究需求：{record.get('user_input', '')}"]
  for tid, output in _extract_task_outputs(record, list(record.get("tasks", {}).keys())).items():
    parts.append(f"\n--- {tid} ---\n{output[:3000]}")
  return "\n".join(parts)


async def create_from_workflow(
  user_id: str,
  workflow_record_id: str,
  *,
  title: str = "",
  paper_type: str = "journal",
  target_journal: str = "",
  workspace_id: str | None = None,
) -> dict:
  record = result_store.get(workflow_record_id, user_id)
  if not record:
    raise ValueError("工作方案不存在或无权访问")

  topic = record.get("user_input", "")[:500]
  project_title = title or record.get("title", "") or topic[:50] or "未命名论文"

  source_content = _build_source_content(record)
  outline_result = await generate_outline(
    topic=topic,
    paper_type=paper_type,
    target_journal=target_journal,
    source_content=source_content,
  )

  project = writing_store.create_project(
    user_id=user_id,
    title=project_title,
    topic=topic,
    paper_type=paper_type,
    target_journal=target_journal,
    source_workflow_id=workflow_record_id,
    workspace_id=workspace_id,
    outline=outline_result.get("sections", []),
  )

  _fill_sections_from_workflow(project, record)
  return writing_store.get_project(project["id"], user_id)


def _fill_sections_from_workflow(project: dict, record: dict) -> None:
  scenario = record.get("scenario", "")
  tasks = record.get("tasks", {})

  section_mapping = {
    "intro": _extract_intro(tasks, scenario),
    "methods": _extract_methods(tasks),
    "related_work": _extract_literature(tasks),
  }

  user_id = None
  with get_session() as session:
    proj = session.get(WritingProjectRecord, project["id"])
    if proj:
      user_id = proj.user_id

  if not user_id:
    return

  for section in project.get("sections", []):
    content = section_mapping.get(section["section_type"], "")
    if content:
      writing_store.update_section(
        section["id"],
        user_id,
        content,
        save_version=True,
        version_note="从工作方案自动填充",
      )


def _extract_intro(tasks: dict, scenario: str) -> str:
  parts = []
  planning = tasks.get("task_planning", {}).get("output", "")
  if planning:
    bg_match = re.search(
      r"(研究背景|背景)[：:\s]*([\s\S]{0,2000}?)(?=\n##|\n\d+\.|$)",
      planning,
      re.IGNORECASE,
    )
    if bg_match:
      parts.append(bg_match.group(2).strip())
    else:
      parts.append(planning[:2000])

  lit = tasks.get("task_literature", {}).get("output", "")
  if lit:
    parts.append("\n\n## 文献综述要点\n\n" + lit[:1500])
  return "\n\n".join(parts)


def _extract_methods(tasks: dict) -> str:
  experiment = tasks.get("task_experiment", {}).get("output", "")
  if experiment:
    return experiment
  planning = tasks.get("task_planning", {}).get("output", "")
  method_match = re.search(
    r"(研究方法|实验设计|技术路线)[：:\s]*([\s\S]{0,3000}?)(?=\n##|\n\d+\.|$)",
    planning,
    re.IGNORECASE,
  )
  if method_match:
    return method_match.group(2).strip()
  return ""


def _extract_literature(tasks: dict) -> str:
  lit = tasks.get("task_literature", {}).get("output", "")
  return lit[:5000] if lit else ""


async def fill_methods_from_workflow(
  project_id: str,
  user_id: str,
  workflow_record_id: str,
) -> dict:
  record = result_store.get(workflow_record_id, user_id)
  if not record:
    raise ValueError("工作方案不存在")

  methods_content = _extract_methods(record.get("tasks", {}))
  if not methods_content:
    raise ValueError("未找到实验方案内容")

  project = writing_store.get_project(project_id, user_id)
  methods_section = next(
    (s for s in project["sections"] if s["section_type"] == "methods"),
    None,
  )
  if not methods_section:
    raise ValueError("项目中无 Methods 章节")

  return writing_store.update_section(
    methods_section["id"],
    user_id,
    methods_content,
    save_version=True,
    version_note="从实验方案填充",
  )
