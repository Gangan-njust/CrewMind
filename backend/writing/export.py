"""学术写作项目导出"""
import re
from datetime import datetime

from backend.storage.results import result_store
from backend.writing.citations import format_all_references
from backend.writing.templates import DEFAULT_SECTIONS, PAPER_TEMPLATES, SECTION_LABELS, is_abstract_section, section_display_title


def _strip_markdown_headings(content: str) -> str:
  lines = []
  for line in content.split("\n"):
    if re.match(r"^#{1,6}\s", line.strip()):
      continue
    lines.append(line)
  return "\n".join(lines).strip()


def _section_content_for_export(section: dict) -> str:
  content = (section.get("content") or "").strip()
  if is_abstract_section(section.get("section_type", "")):
    return _strip_markdown_headings(content)
  return content


def _section_sort_key(project: dict, section: dict) -> int:
  if section.get("sort_order") is not None:
    return section["sort_order"]
  paper_type = project.get("paper_type", "journal")
  order = DEFAULT_SECTIONS.get(paper_type, DEFAULT_SECTIONS["journal"])
  try:
    return order.index(section["section_type"])
  except ValueError:
    return len(order)


def build_markdown(project: dict, bibliography: list[dict] | None = None) -> str:
  paper_type = project.get("paper_type", "journal")
  template = PAPER_TEMPLATES.get(paper_type, PAPER_TEMPLATES["journal"])
  title = project.get("title", "未命名论文")
  topic = project.get("topic", "")
  target = project.get("target_journal", "")
  updated = project.get("updated_at", "")

  try:
    updated_display = datetime.fromisoformat(updated).strftime("%Y-%m-%d %H:%M")
  except ValueError:
    updated_display = updated or datetime.now().strftime("%Y-%m-%d %H:%M")

  lines = [
    f"# {title}",
    "",
    f"- **论文类型**: {template['label']}",
  ]
  if topic:
    lines.append(f"- **研究主题**: {topic}")
  if target:
    lines.append(f"- **目标期刊/会议**: {target}")
  lines.extend([
    f"- **最后更新**: {updated_display}",
    "",
  ])

  sections = sorted(project.get("sections", []), key=lambda s: _section_sort_key(project, s))
  has_content = False
  for sec in sections:
    content = _section_content_for_export(sec)
    if not content:
      continue
    has_content = True
    label = section_display_title(sec)
    lines.extend([
      "---",
      "",
      f"## {label}",
      "",
      content,
      "",
    ])

  if not has_content:
    lines.extend([
      "---",
      "",
      "*暂无章节内容*",
      "",
    ])

  if bibliography:
    lines.extend([
      "---",
      "",
      "## 参考文献",
      "",
    ])
    for ref in bibliography:
      lines.append(f"{ref.get('formatted', '')}")
    lines.append("")

  return "\n".join(lines).rstrip() + "\n"


def build_docx(project: dict, bibliography: list[dict] | None = None) -> bytes:
  return result_store.build_docx(build_markdown(project, bibliography))


def export_filename(project: dict, ext: str) -> str:
  title = project.get("title", "论文")
  safe = re.sub(r'[<>:"/\\|?*]', "_", title).strip() or "论文"
  safe = safe[:60]
  timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
  return f"{safe}_{timestamp}.{ext}"


def get_bibliography_for_project(project_id: str, user_id: str, project: dict) -> list[dict]:
  from backend.storage.writing_store import writing_store

  refs = writing_store.list_references(project_id, user_id)
  lit_ids = list(dict.fromkeys(r["literature_id"] for r in refs))
  if not lit_ids:
    return []
  fmt = project.get("citation_format", "gb7714")
  return format_all_references(lit_ids, fmt)
