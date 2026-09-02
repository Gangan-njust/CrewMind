"""步骤11：结果管理与历史方案库"""
import difflib
import hashlib
import io
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

import markdown
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from htmldocx import HtmlToDocx
from sqlalchemy import func, select

from backend.agents.roles import SCENARIO_LABELS, ScenarioType
from backend.config import PROJECT_ROOT, settings
from backend.storage.database import get_session, setup_database
from backend.storage.models import TopicRecord, WorkflowRecord
from backend.tasks.definitions import TASK_FLOWS
from backend.utils.docx_tables import apply_black_fonts, apply_three_line_tables
from backend.utils.text import sanitize_unicode, sanitize_deep

logger = logging.getLogger(__name__)

PROPOSAL_TASK_ID = "task_review"
DOMAIN_REVIEW_TASK_IDS = frozenset({
  "task_cs_review", "task_bio_review", "task_material_review",
})
PROPOSAL_SECTION_PATTERNS = (
  r"完整工作方案\s*[（(]整合版[）)]",
  r"开题报告\s*[（(]完整版[）)]",
  r"完整开题报告",
  r"整合(?:后的)?(?:完整)?(?:开题报告|工作方案|方案)",
  r"完整工作方案",
)
REVIEW_SCENARIOS = frozenset({"literature_review", "literature_based_review"})
REVIEW_DOC_SECTION_PATTERNS = (
  r"完整文献综述\s*[（(]整合版[）)]",
  r"文献综述\s*[（(]完整版[）)]",
  r"完整文献综述",
)
# 综述成文中属于“过程/工具性说明”的章节：导出纯综述时剔除
REVIEW_PROCESS_HEADING_KEYWORDS = (
  "检索", "筛选", "数据库", "纳入标准",
)
REVIEW_REPORT_MARKERS = (
  "终审报告", "质量评估", "主要优点", "存在问题", "改进建议", "录用建议",
)


def _looks_like_review_report(text: str) -> bool:
  head = text[:3000]
  hits = sum(1 for marker in REVIEW_REPORT_MARKERS if marker in head)
  return hits >= 2 or ("终审报告" in head[:200])


def _looks_like_proposal_document(text: str) -> bool:
  head = text[:800].strip()
  if _looks_like_review_report(text):
    return False
  proposal_markers = ("开题报告", "完整工作方案", "研究方案", "课题规划")
  return any(marker in head for marker in proposal_markers)


def _extract_markdown_section(text: str, heading_patterns: tuple[str, ...]) -> str | None:
  for pattern in heading_patterns:
    match = re.search(
      rf"^(#{{1,3}})\s*(?:\d+\s*[.、]?\s*)?(?:{pattern})\s*$",
      text,
      re.MULTILINE,
    )
    if not match:
      continue
    # 整合版方案通常在终审报告末尾，后续子标题可能用 # 级别
    section = text[match.end():].strip()
    if section:
      return section
  return None


def _compose_proposal_from_tasks(tasks: dict, task_order: list[str]) -> str | None:
  parts: list[str] = []
  for tid in task_order:
    if tid == PROPOSAL_TASK_ID or tid in DOMAIN_REVIEW_TASK_IDS:
      continue
    task = tasks.get(tid)
    output = (task or {}).get("output", "").strip()
    if output:
      parts.append(output)
  if not parts:
    return None
  return "\n\n---\n\n".join(parts)


def extract_proposal_output(
  tasks: dict,
  scenario: str,
  task_order: list[str] | None = None,
) -> str | None:
  """提取开题报告/完整方案正文，跳过终审意见。"""
  order = task_order or []
  if not order:
    try:
      order = [t.id for t in TASK_FLOWS[ScenarioType(scenario)]]
    except (ValueError, KeyError):
      order = list(tasks.keys())

  review_task = tasks.get(PROPOSAL_TASK_ID)
  review_output = (review_task or {}).get("output", "").strip()
  if review_output:
    if _looks_like_proposal_document(review_output):
      return review_output
    if _looks_like_review_report(review_output):
      section = _extract_markdown_section(review_output, PROPOSAL_SECTION_PATTERNS)
      if section:
        return section
    else:
      section = _extract_markdown_section(review_output, PROPOSAL_SECTION_PATTERNS)
      if section:
        return section

  composed = _compose_proposal_from_tasks(tasks, order)
  if composed:
    return composed

  if review_output and not _looks_like_review_report(review_output):
    return review_output
  return None


def _looks_like_review_document(text: str) -> bool:
  """判断文本是否为综述成文正文（而非终审/评审意见）。"""
  head = text[:800].strip()
  if _looks_like_review_report(text):
    return False
  return any(marker in head for marker in ("# 文献综述", "完整文献综述", "# 综述"))


def _strip_review_process_sections(md: str) -> str:
  """去掉综述正文中属于“过程/工具性说明”的章节（如检索说明、筛选标准、数据库说明）。"""
  lines = md.splitlines()
  out: list[str] = []
  skip_depth: int | None = None
  for line in lines:
    m = re.match(r"^(#{1,6})\s+(.*)$", line)
    if m:
      level = len(m.group(1))
      title = m.group(2).strip()
      if skip_depth is not None and level <= skip_depth:
        skip_depth = None
      if skip_depth is None and any(k in title for k in REVIEW_PROCESS_HEADING_KEYWORDS):
        skip_depth = level
        continue
    if skip_depth is not None:
      continue
    out.append(line)
  return "\n".join(out).strip()


def extract_pure_output(
  tasks: dict,
  scenario: str,
  task_order: list[str] | None = None,
) -> str | None:
  """提取“纯综述/纯文章”正文：只取最终整合成果，不含规划稿、审稿意见、检索说明等过程。"""
  order = task_order or []
  if not order:
    try:
      order = [t.id for t in TASK_FLOWS[ScenarioType(scenario)]]
    except (ValueError, KeyError):
      order = list(tasks.keys())

  if scenario in REVIEW_SCENARIOS:
    review_task = tasks.get(PROPOSAL_TASK_ID) or {}
    review_output = (review_task.get("output") or "").strip()
    lit_task = tasks.get("task_literature") or {}
    lit_output = (lit_task.get("output") or "").strip()

    # 1) 终审任务本身已是综述正文 → 直接使用
    if review_output and _looks_like_review_document(review_output):
      return _strip_review_process_sections(review_output)
    # 2) 终审报告内嵌“完整文献综述（整合版）” → 抽取该节
    if review_output:
      section = _extract_markdown_section(review_output, REVIEW_DOC_SECTION_PATTERNS)
      if section:
        return _strip_review_process_sections(section)
    # 3) 综述撰写任务的成文正文
    if lit_output:
      return _strip_review_process_sections(lit_output)
    # 4) 回退：去掉终审/学科审稿后的任务拼装
    composed = _compose_proposal_from_tasks(tasks, order)
    if composed:
      return composed
    return None

  # 其余场景：与“仅开题报告”一致，返回最终整合正文
  return extract_proposal_output(tasks, scenario, order)

TITLE_MAX_LENGTH = 80

_LATEX_ESCAPES = (
  ("\\", r"\textbackslash{}"),
  ("&", r"\&"),
  ("%", r"\%"),
  ("$", r"\$"),
  ("#", r"\#"),
  ("_", r"\_"),
  ("{", r"\{"),
  ("}", r"\}"),
  ("~", r"\textasciitilde{}"),
  ("^", r"\textasciicircum{}"),
)


def _escape_latex(text: str) -> str:
  for char, repl in _LATEX_ESCAPES:
    text = text.replace(char, repl)
  return text


def _inline_markdown_to_latex(text: str) -> str:
  pattern = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|[^*`]+)")
  parts: list[str] = []
  for match in pattern.finditer(text):
    chunk = match.group(0)
    if chunk.startswith("`") and chunk.endswith("`"):
      parts.append(rf"\texttt{{{_escape_latex(chunk[1:-1])}}}")
    elif chunk.startswith("**") and chunk.endswith("**"):
      parts.append(rf"\textbf{{{_escape_latex(chunk[2:-2])}}}")
    elif chunk.startswith("*") and chunk.endswith("*"):
      parts.append(rf"\textit{{{_escape_latex(chunk[1:-1])}}}")
    else:
      parts.append(_escape_latex(chunk))
  return "".join(parts)


def _markdown_to_latex(md: str) -> str:
  if not md.strip():
    return ""

  lines = md.splitlines()
  parts: list[str] = []
  in_verbatim = False
  list_active = False
  i = 0

  def close_list() -> None:
    nonlocal list_active
    if list_active:
      parts.append(r"\end{itemize}")
      list_active = False

  while i < len(lines):
    line = lines[i]

    if line.strip().startswith("```"):
      if in_verbatim:
        parts.append(r"\end{verbatim}")
        in_verbatim = False
      else:
        close_list()
        parts.append(r"\begin{verbatim}")
        in_verbatim = True
      i += 1
      continue

    if in_verbatim:
      parts.append(line)
      i += 1
      continue

    stripped = line.strip()

    header = re.match(r"^(#{1,6})\s+(.*)$", stripped)
    if header:
      close_list()
      level = len(header.group(1))
      title = _inline_markdown_to_latex(header.group(2))
      if level == 1:
        parts.append(rf"\section{{{title}}}")
      elif level == 2:
        parts.append(rf"\subsection{{{title}}}")
      elif level == 3:
        parts.append(rf"\subsubsection{{{title}}}")
      else:
        parts.append(rf"\paragraph{{{title}}}\mbox{{}}")
      i += 1
      continue

    list_item = re.match(r"^[-*+]\s+(.*)$", stripped)
    if list_item:
      if not list_active:
        parts.append(r"\begin{itemize}")
        list_active = True
      parts.append(rf"\item {_inline_markdown_to_latex(list_item.group(1))}")
      i += 1
      continue

    if re.match(r"^---+$", stripped):
      close_list()
      parts.append(r"\noindent\rule{\textwidth}{0.4pt}")
      i += 1
      continue

    if not stripped:
      close_list()
      parts.append("")
      i += 1
      continue

    close_list()
    parts.append(_inline_markdown_to_latex(stripped))
    parts.append("")
    i += 1

  close_list()
  if in_verbatim:
    parts.append(r"\end{verbatim}")
  return "\n".join(parts).strip()


def normalize_user_input(text: str) -> str:
  return re.sub(r"\s+", " ", sanitize_unicode(text).strip()).lower()


def compute_topic_key(user_input: str, scenario: str) -> str:
  raw = f"{scenario}::{normalize_user_input(user_input)}"
  return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


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
    topic_id: str | None = None,
  ) -> str:
    """保存工作方案，返回记录 ID"""
    self._ensure_legacy_migrated()
    user_input = sanitize_unicode(user_input)
    results = sanitize_deep(results)
    metadata = sanitize_deep(metadata or {})
    record_id = str(uuid.uuid4())
    created_at = datetime.now()
    base_title = generate_base_title(user_input, scenario)

    with get_session() as session:
      topic = self._resolve_topic(
        session, user_id, scenario, user_input, topic_id, base_title, created_at
      )
      version_number = self._next_version_number(session, topic.id)
      title = f"{topic.title} · v{version_number}"

      session.add(WorkflowRecord(
        id=record_id,
        crew_id=crew_id,
        user_id=user_id,
        topic_id=topic.id,
        version_number=version_number,
        scenario=scenario,
        title=title,
        user_input=user_input,
        created_at=created_at,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        tasks_json=json.dumps(results, ensure_ascii=False),
      ))
      topic.updated_at = created_at
      session.commit()

    return record_id

  def _resolve_topic(
    self,
    session,
    user_id: str,
    scenario: str,
    user_input: str,
    topic_id: str | None,
    base_title: str,
    created_at: datetime,
  ) -> TopicRecord:
    if topic_id:
      topic = session.get(TopicRecord, topic_id)
      if not topic or topic.user_id != user_id:
        raise ValueError("课题不存在")
      return topic

    topic_key = compute_topic_key(user_input, scenario)
    topic = session.scalars(
      select(TopicRecord).where(
        TopicRecord.user_id == user_id,
        TopicRecord.topic_key == topic_key,
      )
    ).first()
    if topic:
      return topic

    topic = TopicRecord(
      id=str(uuid.uuid4()),
      user_id=user_id,
      scenario=scenario,
      title=base_title,
      topic_key=topic_key,
      user_input=user_input,
      best_record_id=None,
      created_at=created_at,
      updated_at=created_at,
    )
    session.add(topic)
    session.flush()
    return topic

  @staticmethod
  def _next_version_number(session, topic_id: str) -> int:
    current = session.scalar(
      select(func.max(WorkflowRecord.version_number)).where(
        WorkflowRecord.topic_id == topic_id
      )
    )
    return (current or 0) + 1

  def list_topics(
    self,
    user_id: str,
    scenario: str | None = None,
    search: str | None = None,
    limit: int = 50,
  ) -> list[dict]:
    self._ensure_legacy_migrated()
    with get_session() as session:
      stmt = (
        select(TopicRecord)
        .where(TopicRecord.user_id == user_id)
        .order_by(TopicRecord.updated_at.desc())
      )
      if scenario:
        stmt = stmt.where(TopicRecord.scenario == scenario)
      if search:
        keyword = f"%{search.strip()}%"
        stmt = stmt.where(
          TopicRecord.title.ilike(keyword) | TopicRecord.user_input.ilike(keyword)
        )
      topics = session.scalars(stmt.limit(limit)).all()
      result = []
      for topic in topics:
        version_count = session.scalar(
          select(func.count()).select_from(WorkflowRecord).where(
            WorkflowRecord.topic_id == topic.id
          )
        ) or 0
        result.append(self._to_topic_item(topic, version_count))
      return result

  def list_topic_versions(self, topic_id: str, user_id: str) -> list[dict]:
    self._ensure_legacy_migrated()
    with get_session() as session:
      topic = session.get(TopicRecord, topic_id)
      if not topic or topic.user_id != user_id:
        raise ValueError("课题不存在")
      rows = session.scalars(
        select(WorkflowRecord)
        .where(WorkflowRecord.topic_id == topic_id)
        .order_by(WorkflowRecord.version_number.desc())
      ).all()
      return [self._to_version_item(row, topic.best_record_id) for row in rows]

  def get_topic(self, topic_id: str, user_id: str) -> dict | None:
    self._ensure_legacy_migrated()
    with get_session() as session:
      topic = session.get(TopicRecord, topic_id)
      if not topic or topic.user_id != user_id:
        return None
      version_count = session.scalar(
        select(func.count()).select_from(WorkflowRecord).where(
          WorkflowRecord.topic_id == topic.id
        )
      ) or 0
      return self._to_topic_item(topic, version_count)

  def set_best_version(self, topic_id: str, record_id: str, user_id: str) -> dict:
    self._ensure_legacy_migrated()
    with get_session() as session:
      topic = session.get(TopicRecord, topic_id)
      if not topic or topic.user_id != user_id:
        raise ValueError("课题不存在")
      record = session.get(WorkflowRecord, record_id)
      if not record or record.topic_id != topic_id or record.user_id != user_id:
        raise ValueError("版本不存在")
      topic.best_record_id = record_id
      topic.updated_at = datetime.now()
      session.commit()
      version_count = session.scalar(
        select(func.count()).select_from(WorkflowRecord).where(
          WorkflowRecord.topic_id == topic.id
        )
      ) or 0
      return self._to_topic_item(topic, version_count)

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
    """对比两个方案版本，返回并排差异与优劣分析"""
    a = self.get(record_id_a, user_id)
    b = self.get(record_id_b, user_id)
    if not a or not b:
      raise ValueError("记录不存在")

    _, task_names_a = self._resolve_scenario_meta(a["scenario"])
    _, task_names_b = self._resolve_scenario_meta(b["scenario"])
    task_names = {**task_names_a, **task_names_b}

    insights_a = self._extract_review_insights(a.get("tasks", {}))
    insights_b = self._extract_review_insights(b.get("tasks", {}))
    advantages_a: list[str] = []
    advantages_b: list[str] = []
    task_diffs: list[dict] = []

    all_task_ids = set(a.get("tasks", {}).keys()) | set(b.get("tasks", {}).keys())
    for tid in sorted(all_task_ids):
      task_a = a.get("tasks", {}).get(tid, {})
      task_b = b.get("tasks", {}).get(tid, {})
      output_a = task_a.get("output", "")
      output_b = task_b.get("output", "")
      len_a = len(output_a)
      len_b = len(output_b)
      task_name = task_names.get(tid, tid)

      if len_a > len_b + 50:
        advantages_a.append(f"「{task_name}」内容更详尽（多 {len_a - len_b} 字）")
      elif len_b > len_a + 50:
        advantages_b.append(f"「{task_name}」内容更详尽（多 {len_b - len_a} 字）")

      if task_a.get("status") == "completed" and task_b.get("status") != "completed":
        advantages_a.append(f"「{task_name}」已完成，另一版本未完成")
      elif task_b.get("status") == "completed" and task_a.get("status") != "completed":
        advantages_b.append(f"「{task_name}」已完成，另一版本未完成")

      similarity = difflib.SequenceMatcher(None, output_a, output_b).ratio() if output_a or output_b else 1.0

      task_diffs.append({
        "task_id": tid,
        "task_name": task_name,
        "status_a": task_a.get("status", "missing"),
        "status_b": task_b.get("status", "missing"),
        "output_a": output_a,
        "output_b": output_b,
        "output_length_a": len_a,
        "output_length_b": len_b,
        "similarity": round(similarity, 3),
        "line_diff": self._line_diff(output_a, output_b),
      })

    if insights_a["score"] is not None and insights_b["score"] is not None:
      if insights_a["score"] > insights_b["score"]:
        advantages_a.append(f"终审评分更高（{insights_a['score']} vs {insights_b['score']} 分）")
      elif insights_b["score"] > insights_a["score"]:
        advantages_b.append(f"终审评分更高（{insights_b['score']} vs {insights_a['score']} 分）")

    return {
      "record_a": {
        "id": record_id_a,
        "title": a.get("title", ""),
        "version_number": a.get("version_number", 1),
        "created_at": a["created_at"],
        "scenario": a["scenario"],
        "pros": insights_a["pros"],
        "cons": insights_a["cons"],
      },
      "record_b": {
        "id": record_id_b,
        "title": b.get("title", ""),
        "version_number": b.get("version_number", 1),
        "created_at": b["created_at"],
        "scenario": b["scenario"],
        "pros": insights_b["pros"],
        "cons": insights_b["cons"],
      },
      "advantages_a": advantages_a,
      "advantages_b": advantages_b,
      "task_diffs": task_diffs,
    }

  @staticmethod
  def _line_diff(text_a: str, text_b: str) -> list[dict]:
    lines_a = text_a.splitlines()
    lines_b = text_b.splitlines()
    hunks: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, lines_a, lines_b).get_opcodes():
      if tag == "equal":
        hunks.append({"type": "equal", "lines_a": lines_a[i1:i2], "lines_b": lines_b[j1:j2]})
      elif tag == "delete":
        hunks.append({"type": "remove", "lines_a": lines_a[i1:i2], "lines_b": []})
      elif tag == "insert":
        hunks.append({"type": "add", "lines_a": [], "lines_b": lines_b[j1:j2]})
      elif tag == "replace":
        hunks.append({"type": "change", "lines_a": lines_a[i1:i2], "lines_b": lines_b[j1:j2]})
    return hunks

  @staticmethod
  def _extract_review_insights(tasks: dict) -> dict:
    review_output = ""
    for tid, task in tasks.items():
      if "review" in tid and task.get("output"):
        review_output = task["output"]
        break

    pros: list[str] = []
    cons: list[str] = []
    score: int | None = None

    if review_output:
      score_match = re.search(r"质量评估[^0-9]*(\d+)", review_output)
      if score_match:
        score = int(score_match.group(1))

      section_map = {
        "pros": [r"主要优点", r"优点"],
        "cons": [r"存在问题", r"问题与不足", r"不足之处"],
      }
      for section, patterns in section_map.items():
        for pattern in patterns:
          match = re.search(
            rf"##?\s*\d*\.?\s*{pattern}\s*\n(.*?)(?=\n##|\Z)",
            review_output,
            re.DOTALL | re.IGNORECASE,
          )
          if match:
            items = [
              line.strip().lstrip("-•*0123456789. ").strip()
              for line in match.group(1).splitlines()
              if line.strip() and not line.strip().startswith("#")
            ]
            if section == "pros":
              pros.extend(items[:5])
            else:
              cons.extend(items[:5])
            break

    return {"pros": pros, "cons": cons, "score": score}

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

  def build_proposal_markdown(self, record: dict) -> str:
    output = extract_proposal_output(
      record.get("tasks", {}),
      record.get("scenario", ""),
    )
    if not output:
      raise ValueError("未找到开题报告内容，请确认终审任务已完成")
    return output.rstrip() + "\n"

  def build_proposal_markdown_from_workflow(
    self,
    scenario: str,
    user_input: str,
    results: dict,
    task_order: list[str] | None = None,
  ) -> str:
    output = extract_proposal_output(results, scenario, task_order)
    if not output:
      raise ValueError("未找到开题报告内容，请确认终审任务已完成")
    return output.rstrip() + "\n"

  def build_latex(self, record: dict) -> str:
    scenario = record.get("scenario", "")
    scenario_label, task_names = self._resolve_scenario_meta(scenario)
    created_at = record.get("created_at", datetime.now().isoformat())
    try:
      created_display = datetime.fromisoformat(created_at).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
      created_display = created_at

    title = record.get("title", "工作方案")
    user_input = record.get("user_input", "")

    sections: list[str] = [
      r"\documentclass[UTF8]{ctexart}",
      r"\usepackage{hyperref}",
      r"\usepackage{geometry}",
      r"\geometry{a4paper, margin=2.5cm}",
      r"\usepackage{verbatim}",
      r"\usepackage{enumitem}",
      "",
      rf"\title{{{_escape_latex(title)}}}",
      rf"\author{{场景：{_escape_latex(scenario_label)}}}",
      rf"\date{{{_escape_latex(created_display)}}}",
      "",
      r"\begin{document}",
      r"\maketitle",
      "",
      r"\section*{用户需求}",
      _escape_latex(user_input),
      "",
    ]

    for tid, task in record.get("tasks", {}).items():
      task_title = task_names.get(tid, tid)
      sections.extend([
        r"\section{" + _escape_latex(task_title) + "}",
        rf"\textbf{{状态：}}{_escape_latex(task.get('status', 'unknown'))}",
        "",
      ])
      if task.get("human_feedback"):
        sections.extend([
          r"\subsection*{人工审核意见}",
          _markdown_to_latex(task["human_feedback"]),
          "",
        ])
      if task.get("output"):
        sections.append(_markdown_to_latex(task["output"]))
        sections.append("")
      elif task.get("error"):
        sections.extend([
          rf"\textbf{{错误：}}{_escape_latex(task['error'])}",
          "",
        ])

    sections.extend([r"\end{document}", ""])
    return "\n".join(sections)

  def build_latex_from_workflow(
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
    return self.build_latex(record)

  def build_proposal_latex(self, record: dict) -> str:
    output = extract_proposal_output(
      record.get("tasks", {}),
      record.get("scenario", ""),
    )
    if not output:
      raise ValueError("未找到开题报告内容，请确认终审任务已完成")

    title = record.get("title") or "开题报告"
    sections: list[str] = [
      r"\documentclass[UTF8]{ctexart}",
      r"\usepackage{hyperref}",
      r"\usepackage{geometry}",
      r"\geometry{a4paper, margin=2.5cm}",
      r"\usepackage{verbatim}",
      r"\usepackage{enumitem}",
      "",
      rf"\title{{{_escape_latex(title)}}}",
      r"\date{}",
      "",
      r"\begin{document}",
      r"\maketitle",
      "",
      _markdown_to_latex(output),
      "",
      r"\end{document}",
      "",
    ]
    return "\n".join(sections)

  def build_proposal_latex_from_workflow(
    self,
    scenario: str,
    user_input: str,
    results: dict,
    title: str | None = None,
    task_order: list[str] | None = None,
  ) -> str:
    output = extract_proposal_output(results, scenario, task_order)
    if not output:
      raise ValueError("未找到开题报告内容，请确认终审任务已完成")

    doc_title = title or "开题报告"
    sections: list[str] = [
      r"\documentclass[UTF8]{ctexart}",
      r"\usepackage{hyperref}",
      r"\usepackage{geometry}",
      r"\geometry{a4paper, margin=2.5cm}",
      r"\usepackage{verbatim}",
      r"\usepackage{enumitem}",
      "",
      rf"\title{{{_escape_latex(doc_title)}}}",
      r"\date{}",
      "",
      r"\begin{document}",
      r"\maketitle",
      "",
      _markdown_to_latex(output),
      "",
      r"\end{document}",
      "",
    ]
    return "\n".join(sections)

  def build_pure_markdown(self, record: dict) -> str:
    """导出纯综述/纯文章 Markdown：仅含最终整合正文，不含分析过程。"""
    output = extract_pure_output(
      record.get("tasks", {}),
      record.get("scenario", ""),
    )
    if not output:
      raise ValueError("未找到纯正文内容，请确认对应任务已完成")
    return output.rstrip() + "\n"

  def build_pure_markdown_from_workflow(
    self,
    scenario: str,
    user_input: str,
    results: dict,
    task_order: list[str] | None = None,
  ) -> str:
    output = extract_pure_output(results, scenario, task_order)
    if not output:
      raise ValueError("未找到纯正文内容，请确认对应任务已完成")
    return output.rstrip() + "\n"

  def build_pure_latex(self, record: dict) -> str:
    output = extract_pure_output(
      record.get("tasks", {}),
      record.get("scenario", ""),
    )
    if not output:
      raise ValueError("未找到纯正文内容，请确认对应任务已完成")
    title = record.get("title") or "纯综述/纯文章"
    sections: list[str] = [
      r"\documentclass[UTF8]{ctexart}",
      r"\usepackage{hyperref}",
      r"\usepackage{geometry}",
      r"\geometry{a4paper, margin=2.5cm}",
      r"\usepackage{verbatim}",
      r"\usepackage{enumitem}",
      "",
      rf"\title{{{_escape_latex(title)}}}",
      r"\date{}",
      "",
      r"\begin{document}",
      r"\maketitle",
      "",
      _markdown_to_latex(output),
      "",
      r"\end{document}",
      "",
    ]
    return "\n".join(sections)

  def build_pure_latex_from_workflow(
    self,
    scenario: str,
    user_input: str,
    results: dict,
    title: str | None = None,
    task_order: list[str] | None = None,
  ) -> str:
    output = extract_pure_output(results, scenario, task_order)
    if not output:
      raise ValueError("未找到纯正文内容，请确认对应任务已完成")
    doc_title = title or "纯综述/纯文章"
    sections: list[str] = [
      r"\documentclass[UTF8]{ctexart}",
      r"\usepackage{hyperref}",
      r"\usepackage{geometry}",
      r"\geometry{a4paper, margin=2.5cm}",
      r"\usepackage{verbatim}",
      r"\usepackage{enumitem}",
      "",
      rf"\title{{{_escape_latex(doc_title)}}}",
      r"\date{}",
      "",
      r"\begin{document}",
      r"\maketitle",
      "",
      _markdown_to_latex(output),
      "",
      r"\end{document}",
      "",
    ]
    return "\n".join(sections)


  def build_docx(self, md_content: str, *, first_line_indent: bool = False) -> bytes:
    html = markdown.markdown(
      md_content,
      extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
    )
    document = Document()
    self._configure_docx_styles(document)
    HtmlToDocx().add_html_to_document(html, document)
    apply_three_line_tables(document)
    apply_black_fonts(document)
    if first_line_indent:
      from backend.utils.docx_tables import apply_paragraph_first_line_indent
      apply_paragraph_first_line_indent(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()

  def export_filename(self, scenario: str, ext: str, scope: str = "full") -> str:
    scenario_label, _ = self._resolve_scenario_meta(scenario)
    safe_label = "".join(c if c.isalnum() or c in "._-" else "_" for c in scenario_label)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if scope == "proposal":
      prefix = "开题报告"
    elif scope in ("pure", "clean"):
      prefix = "纯综述" if "review" in scenario else "纯文章"
    else:
      prefix = "工作方案"
    return f"{prefix}_{safe_label}_{timestamp}.{ext}"

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
      "topic_id": row.topic_id,
      "version_number": row.version_number or 1,
      "title": title,
      "scenario": row.scenario,
      "user_input": row.user_input[:100],
      "created_at": row.created_at.isoformat(),
      "task_count": len(tasks),
      "partial": bool(json.loads(row.metadata_json or "{}").get("partial")),
    }

  @staticmethod
  def _to_record(row: WorkflowRecord) -> dict:
    title = row.title or generate_base_title(row.user_input, row.scenario)
    return {
      "id": row.id,
      "crew_id": row.crew_id,
      "topic_id": row.topic_id,
      "version_number": row.version_number or 1,
      "title": title,
      "scenario": row.scenario,
      "user_input": row.user_input,
      "created_at": row.created_at.isoformat(),
      "metadata": json.loads(row.metadata_json or "{}"),
      "tasks": json.loads(row.tasks_json or "{}"),
    }

  @staticmethod
  def _to_topic_item(topic: TopicRecord, version_count: int) -> dict:
    return {
      "id": topic.id,
      "title": topic.title,
      "scenario": topic.scenario,
      "user_input": topic.user_input[:200],
      "version_count": version_count,
      "best_record_id": topic.best_record_id,
      "created_at": topic.created_at.isoformat(),
      "updated_at": topic.updated_at.isoformat(),
    }

  @staticmethod
  def _to_version_item(row: WorkflowRecord, best_record_id: str | None) -> dict:
    tasks = json.loads(row.tasks_json or "{}")
    return {
      "id": row.id,
      "topic_id": row.topic_id,
      "version_number": row.version_number or 1,
      "title": row.title,
      "scenario": row.scenario,
      "created_at": row.created_at.isoformat(),
      "task_count": len(tasks),
      "partial": bool(json.loads(row.metadata_json or "{}").get("partial")),
      "is_best": row.id == best_record_id,
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
    black = RGBColor(0, 0, 0)
    normal = document.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)
    normal.font.color.rgb = black
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    for style_name, size in [("Heading 1", 18), ("Heading 2", 15), ("Heading 3", 13)]:
      if style_name in document.styles:
        heading = document.styles[style_name]
        heading.font.name = "Microsoft YaHei"
        heading.font.size = Pt(size)
        heading.font.color.rgb = black
        heading._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

  def _build_markdown(self, record: dict) -> str:
    return self.build_markdown(record)


result_store = ResultStore()
