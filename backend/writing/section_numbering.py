"""论文章节编号（摘要、Abstract 不编号）"""
from backend.writing.templates import is_abstract_section, section_display_title

BIBLIOGRAPHY_SECTION_TITLE = "参考文献"


def is_numbered_section(section: dict) -> bool:
  if is_abstract_section(section.get("section_type", "")):
    return False
  if (section.get("title") or "").strip() == BIBLIOGRAPHY_SECTION_TITLE:
    return False
  return True


def compute_section_numbers(sections: list[dict]) -> dict[str, int]:
  sorted_sections = sorted(sections, key=lambda s: s.get("sort_order", 0))
  numbers: dict[str, int] = {}
  num = 0
  for sec in sorted_sections:
    if not is_numbered_section(sec):
      continue
    num += 1
    numbers[sec["id"]] = num
  return numbers


def numbered_section_title(section: dict, numbers: dict[str, int]) -> str:
  base = section_display_title(section)
  num = numbers.get(section["id"])
  if num is None:
    return base
  return f"{num}.{base}"
