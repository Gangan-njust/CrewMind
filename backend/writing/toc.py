"""导出与预览共用的目录生成"""
import re

from backend.writing.section_numbering import (
  compute_section_numbers,
  is_numbered_section,
  numbered_section_title,
)
from backend.writing.templates import is_abstract_section

HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$")


def _strip_markdown_headings(content: str) -> str:
  lines = []
  for line in content.split("\n"):
    if re.match(r"^#{1,6}\s", line.strip()):
      continue
    lines.append(line)
  return "\n".join(lines).strip()


def _section_content_for_toc(section: dict) -> str:
  content = (section.get("content") or "").strip()
  if is_abstract_section(section.get("section_type", "")):
    return _strip_markdown_headings(content)
  return content


def parse_markdown_headings(content: str) -> list[dict]:
  headings: list[dict] = []
  for line in content.split("\n"):
    match = HEADING_RE.match(line.strip())
    if match:
      headings.append({
        "level": len(match.group(1)),
        "title": match.group(2).strip(),
      })
  return headings


def build_table_of_contents_items(sections: list[dict]) -> list[dict]:
  sorted_sections = sorted(sections, key=lambda s: s.get("sort_order", 0))
  section_numbers = compute_section_numbers(sorted_sections)
  items: list[dict] = []

  for section in sorted_sections:
    items.append({
      "indent": 0,
      "label": numbered_section_title(section, section_numbers),
    })

    content = _section_content_for_toc(section)
    chapter_num = section_numbers.get(section["id"])
    counters = [0, 0, 0]
    for heading in parse_markdown_headings(content):
      idx = heading["level"] - 2
      counters[idx] += 1
      for i in range(idx + 1, len(counters)):
        counters[i] = 0

      label = heading["title"]
      if chapter_num is not None and is_numbered_section(section):
        num_parts = [chapter_num, *counters[: idx + 1]]
        label = f"{'.'.join(str(n) for n in num_parts)} {heading['title']}"

      items.append({
        "indent": heading["level"] - 1,
        "label": label,
      })

  return items


def format_table_of_contents_markdown(items: list[dict], *, trailing_separator: bool = True) -> str:
  if not items:
    return ""
  lines = ["## 目录", ""]
  for item in items:
    prefix = "  " * item["indent"]
    lines.append(f"{prefix}- {item['label']}")
  if trailing_separator:
    lines.extend(["", "---", ""])
  return "\n".join(lines)
