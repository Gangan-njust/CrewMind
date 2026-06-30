"""根据项目大纲与目录结构补全整篇论文"""
import re

from backend.writing.assistant import expand_writing, expand_writing_structured
from backend.writing.templates import PAPER_TEMPLATES, is_abstract_section, section_display_title

HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$")
DEFAULT_WORD_BY_LEVEL = {2: 400, 3: 250, 4: 150}


def _parse_word_target(raw: str | int | None, default: int = 600) -> int:
  if isinstance(raw, int):
    return max(50, min(raw, 8000))
  if not raw:
    return default
  nums = [int(n) for n in re.findall(r"\d+", str(raw))]
  if not nums:
    return default
  if len(nums) >= 2:
    return max(50, min((nums[0] + nums[1]) // 2, 8000))
  return max(50, min(nums[0], 8000))


def _parse_headings(content: str) -> list[dict]:
  headings = []
  offset = 0
  for line_index, line in enumerate(content.split("\n")):
    match = HEADING_RE.match(line.strip())
    if match:
      level = len(match.group(1))
      if level in (2, 3, 4):
        headings.append({
          "level": level,
          "title": match.group(2).strip(),
          "line": line_index,
          "offset": offset,
        })
    offset += len(line) + 1
  return headings


def _extract_preamble(content: str) -> str:
  headings = _parse_headings(content)
  if not headings:
    return content.strip()
  lines = content.split("\n")
  return "\n".join(lines[: headings[0]["line"]]).strip()


def _split_blocks(content: str, headings: list[dict]) -> list[dict]:
  if not headings:
    return []
  lines = content.split("\n")
  blocks = []
  for index, heading in enumerate(headings):
    start = heading["line"] + 1
    end = headings[index + 1]["line"] if index + 1 < len(headings) else len(lines)
    blocks.append({
      "heading": heading,
      "body": "\n".join(lines[start:end]).strip(),
    })
  return blocks


def _normalize_subsections(raw: list | None) -> list[dict]:
  if not raw:
    return []
  items = []
  for entry in raw:
    if not isinstance(entry, dict):
      continue
    try:
      level = int(entry.get("level", 0))
    except (TypeError, ValueError):
      continue
    title = str(entry.get("title", "")).strip()
    if not title or level not in (2, 3, 4):
      continue
    points = entry.get("outline_points") or []
    if not isinstance(points, list):
      points = []
    items.append({
      "title": title,
      "level": level,
      "word_target": DEFAULT_WORD_BY_LEVEL.get(level, 300),
      "requirements": "",
      "existing_content": "",
      "outline_points": [str(p).strip() for p in points if str(p).strip()],
      "enabled": True,
    })
  return items


def build_section_items(content: str, outline_section: dict | None, section: dict) -> list[dict]:
  if is_abstract_section(section.get("section_type", "")):
    return []
  outline_section = outline_section or {}
  items: list[dict] = []
  headings = _parse_headings(content)
  blocks = _split_blocks(content, headings)
  existing_titles: set[str] = set()

  for block in blocks:
    heading = block["heading"]
    title = heading["title"]
    key = title.lower()
    existing_titles.add(key)
    items.append({
      "title": title,
      "level": heading["level"],
      "word_target": DEFAULT_WORD_BY_LEVEL.get(heading["level"], 300),
      "requirements": "",
      "existing_content": block["body"],
      "outline_points": [],
      "enabled": True,
    })

  for sub in _normalize_subsections(outline_section.get("subsections")):
    key = sub["title"].lower()
    if key in existing_titles:
      for item in items:
        if item["title"].lower() == key and sub["outline_points"]:
          item["outline_points"] = sub["outline_points"]
      continue
    items.append(sub)
    existing_titles.add(key)

  outline_points = outline_section.get("outline_points") or []
  if not items and outline_points:
    section_word = _parse_word_target(outline_section.get("word_target"), 800)
    per_point = max(150, section_word // max(len(outline_points), 1))
    for index, point in enumerate(outline_points):
      point_text = str(point).strip()
      if not point_text:
        continue
      title = point_text if len(point_text) <= 40 else f"要点 {index + 1}"
      items.append({
        "title": title,
        "level": 2,
        "word_target": per_point,
        "requirements": point_text if len(point_text) > 40 else "",
        "existing_content": content.strip() if index == 0 else "",
        "outline_points": [point_text],
        "enabled": True,
      })

  if not items:
    label = section_display_title(section)
    items.append({
      "title": label,
      "level": 2,
      "word_target": _parse_word_target(outline_section.get("word_target"), 600),
      "requirements": outline_section.get("writing_hints", ""),
      "existing_content": content.strip(),
      "outline_points": [str(p).strip() for p in outline_points if str(p).strip()],
      "enabled": True,
    })

  return items


def _summarize_section(section: dict, content: str, max_len: int = 180) -> str:
  label = section_display_title(section)
  preview = re.sub(r"\s+", " ", content.strip())[:max_len]
  if len(content.strip()) > max_len:
    preview += "..."
  return f"- {label}：{preview or '（暂无内容）'}"


async def complete_article_from_outline(
  project: dict,
  *,
  global_requirements: str = "",
  skip_filled: bool = True,
  min_existing_words: int = 80,
) -> dict:
  sections = sorted(project.get("sections", []), key=lambda s: s.get("sort_order", 0))
  outline_map = {
    entry.get("section_type"): entry
    for entry in project.get("outline", [])
    if entry.get("section_type")
  }
  topic = project.get("topic", "")
  paper_type = project.get("paper_type", "journal")
  template = PAPER_TEMPLATES.get(paper_type, PAPER_TEMPLATES["journal"])
  word_targets = template.get("word_targets", {})

  results: list[dict] = []
  context_snippets: list[str] = []

  for section in sections:
    section_id = section["id"]
    content = section.get("content", "") or ""
    word_count = section.get("word_count") or 0
    outline_section = dict(outline_map.get(section.get("section_type"), {}))
    if not outline_section.get("word_target"):
      outline_section["word_target"] = word_targets.get(section.get("section_type"), "")

    if skip_filled and word_count >= min_existing_words and content.strip():
      results.append({
        "section_id": section_id,
        "section_type": section.get("section_type"),
        "display_title": section_display_title(section),
        "status": "skipped",
        "content": content,
        "word_count": word_count,
      })
      context_snippets.append(_summarize_section(section, content))
      continue

    items = build_section_items(content, outline_section, section)
    section_requirements = global_requirements.strip()
    hints = str(outline_section.get("writing_hints", "")).strip()
    if hints:
      section_requirements = f"{section_requirements}\n{hints}".strip()
    if is_abstract_section(section.get("section_type", "")):
      st = section.get("section_type")
      if st == "abstract_en":
        section_requirements = (
          f"{section_requirements}\n"
          "English Abstract: about 250-300 words, continuous paragraphs, no Markdown headings."
        ).strip()
      else:
        section_requirements = (
          f"{section_requirements}\n"
          "中文摘要须控制在约300字，输出为连贯段落，不要使用任何 Markdown 标题或小节标题。"
        ).strip()
    if context_snippets:
      section_requirements = (
        f"{section_requirements}\n\n前序章节摘要（请保持全文连贯，避免重复论述）：\n"
        + "\n".join(context_snippets[-4:])
      ).strip()

    if items:
      result = await expand_writing_structured(
        _extract_preamble(content),
        section_type=section.get("section_type", "intro"),
        topic=topic,
        global_requirements=section_requirements or "（无）",
        items=items,
      )
    else:
      seed = content.strip() or "\n".join(outline_section.get("outline_points") or []) or section_display_title(section)
      result = await expand_writing(
        seed,
        section_type=section.get("section_type", "intro"),
        topic=topic,
        length="medium",
        mode="free",
      )

    new_content = result.get("expanded_text", "").strip()
    new_words = len(re.sub(r"\s", "", new_content))
    results.append({
      "section_id": section_id,
      "section_type": section.get("section_type"),
      "display_title": section_display_title(section),
      "status": "completed",
      "content": new_content,
      "word_count": new_words,
    })
    context_snippets.append(_summarize_section(section, new_content))

  completed_count = sum(1 for r in results if r["status"] == "completed")
  skipped_count = sum(1 for r in results if r["status"] == "skipped")
  return {
    "results": results,
    "completed_count": completed_count,
    "skipped_count": skipped_count,
    "summary": f"已补全 {completed_count} 个章节" + (
      f"，跳过 {skipped_count} 个已有内容的章节" if skipped_count else ""
    ),
  }
