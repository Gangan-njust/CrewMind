"""学术写作项目导出"""
import re
from datetime import datetime

from backend.storage.results import result_store
from backend.storage.writing_store import writing_store
from backend.writing.citations import format_all_references
from backend.writing.section_numbering import compute_section_numbers, numbered_section_title
from backend.writing.templates import DEFAULT_SECTIONS, PAPER_TEMPLATES, is_abstract_section

# 图表提醒占位标记：<!-- figure: ... --> 与 ![图注占位](待插入图表)
FIGURE_COMMENT_RE = re.compile(r"<!--[ \t]*figure.*?-->", re.DOTALL | re.IGNORECASE)
FIGURE_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*待插入图表\s*\)")
CMASSET_RE = re.compile(r"!\[([^\]]*)\]\(\s*cmasset://([a-zA-Z0-9-]+)\s*\)")


def _strip_markdown_headings(content: str) -> str:
  lines = []
  for line in content.split("\n"):
    if re.match(r"^#{1,6}\s", line.strip()):
      continue
    lines.append(line)
  return "\n".join(lines).strip()


def _strip_figure_placeholders(content: str, *, keep_image_placeholders: bool = False) -> str:
  """剔除图表提醒占位：HTML 注释始终剔除；占位图片行默认剔除。"""
  content = FIGURE_COMMENT_RE.sub("", content)
  if not keep_image_placeholders:
    content = FIGURE_IMAGE_RE.sub("", content)
  return content


def _section_content_for_export(section: dict, *, keep_image_placeholders: bool = False) -> str:
  content = (section.get("content") or "").strip()
  content = _strip_figure_placeholders(content, keep_image_placeholders=keep_image_placeholders)
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


def build_markdown(
  project: dict,
  bibliography: list[dict] | None = None,
  *,
  keep_image_placeholders: bool = False,
) -> str:
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
  section_numbers = compute_section_numbers(sections)

  has_content = False
  for sec in sections:
    content = _section_content_for_export(sec, keep_image_placeholders=keep_image_placeholders)
    if not content:
      continue
    has_content = True
    label = numbered_section_title(sec, section_numbers)
    lines.extend([
      f"## {label}",
      "",
      content,
      "",
    ])

  if not has_content:
    lines.extend([
      "*暂无章节内容*",
      "",
    ])

  if bibliography:
    has_bib_section = any(
      (sec.get("title") or "").strip() == "参考文献"
      for sec in project.get("sections", [])
    )
    if not has_bib_section:
      lines.extend([
        "## 参考文献",
        "",
      ])
      for ref in bibliography:
        lines.append(f"[{ref.get('index', '')}] {ref.get('formatted', '')}")
      lines.append("")

  return "\n".join(lines).rstrip() + "\n"


def _resolve_cmassets(md: str, project_id: str) -> str:
  """把 cmasset://{id} 引用替换为磁盘绝对路径，供 docx 内嵌真实图表。"""
  if not project_id or "cmasset://" not in md:
    return md

  def repl(match: re.Match) -> str:
    caption = match.group(1)
    asset_id = match.group(2)
    path = writing_store.resolve_asset_path(asset_id)
    if path and path.is_file():
      return f"![{caption}]({path.as_posix()})"
    return ""  # 素材文件缺失 → 移除该引用行，避免导出坏图

  return CMASSET_RE.sub(repl, md)


def build_docx(
  project: dict,
  bibliography: list[dict] | None = None,
  *,
  keep_image_placeholders: bool = False,
) -> bytes:
  md = build_markdown(project, bibliography, keep_image_placeholders=keep_image_placeholders)
  md = _resolve_cmassets(md, project.get("id") or "")
  return result_store.build_docx(md, first_line_indent=True)


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
