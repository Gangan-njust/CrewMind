"""论文大纲生成"""
import json
import logging

from backend.llm.client import llm_client
from backend.writing.prompts import OUTLINE_GENERATION_PROMPT
from backend.writing.templates import DEFAULT_SECTIONS, PAPER_TEMPLATES, SECTION_LABELS, is_abstract_section

logger = logging.getLogger(__name__)


def _parse_json_response(text: str) -> dict:
  import re
  text = text.strip()
  if text.startswith("```"):
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
  try:
    return json.loads(text)
  except json.JSONDecodeError:
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
      return json.loads(match.group(0))
    raise ValueError(f"无法解析 LLM JSON 输出: {text[:200]}")


async def _llm_json(prompt: str) -> dict:
  response = await llm_client.chat(
    [{"role": "user", "content": prompt}],
    temperature=0.3,
  )
  if hasattr(response, "__aiter__"):
    chunks = []
    async for chunk in response:
      chunks.append(chunk)
    response = "".join(chunks)
  return _parse_json_response(str(response))


def _truncate(text: str, max_len: int = 8000) -> str:
  if len(text) <= max_len:
    return text
  return text[:max_len] + "\n...(内容已截断)"


async def generate_outline(
  topic: str,
  paper_type: str = "journal",
  target_journal: str = "",
  source_content: str = "",
) -> dict:
  template = PAPER_TEMPLATES.get(paper_type, PAPER_TEMPLATES["journal"])
  section_types = DEFAULT_SECTIONS.get(paper_type, DEFAULT_SECTIONS["journal"])

  prompt = OUTLINE_GENERATION_PROMPT.format(
    paper_type_label=template["label"],
    topic=topic or "待定",
    target_journal=target_journal or "未指定",
    source_content=_truncate(source_content) or "无",
    section_types=", ".join(section_types),
  )

  try:
    result = await _llm_json(prompt)
  except Exception as e:
    logger.warning("LLM 大纲生成失败，使用默认模板: %s", e)
    result = _default_outline(topic, paper_type, section_types)

  sections = result.get("sections", [])
  normalized = []
  for sec in sections:
    st = sec.get("section_type", "")
    if st not in section_types:
      continue
    normalized.append({
      "section_type": st,
      "title": sec.get("title", SECTION_LABELS.get(st, st)),
      "outline_points": sec.get("outline_points", []),
      "subsections": [] if is_abstract_section(st) else _normalize_subsections(sec.get("subsections", [])),
      "writing_hints": sec.get("writing_hints", ""),
      "word_target": template.get("word_targets", {}).get(st, ""),
    })

  if not normalized:
    normalized = _default_outline(topic, paper_type, section_types)["sections"]

  return {
    "title_suggestion": result.get("title_suggestion", topic or "未命名论文"),
    "paper_type": paper_type,
    "sections": normalized,
  }


def _normalize_subsections(raw: list | None) -> list[dict]:
  if not raw:
    return []
  normalized = []
  for item in raw:
    if not isinstance(item, dict):
      continue
    try:
      level = int(item.get("level", 0))
    except (TypeError, ValueError):
      continue
    title = str(item.get("title", "")).strip()
    if not title or level not in (2, 3, 4):
      continue
    points = item.get("outline_points", [])
    if not isinstance(points, list):
      points = []
    normalized.append({
      "level": level,
      "title": title,
      "outline_points": [str(p).strip() for p in points if str(p).strip()],
    })
  return normalized


def _default_outline(topic: str, paper_type: str, section_types: list[str]) -> dict:
  template = PAPER_TEMPLATES.get(paper_type, PAPER_TEMPLATES["journal"])
  sections = []
  for st in section_types:
    label = SECTION_LABELS.get(st, st)
    sections.append({
      "section_type": st,
      "title": label,
      "outline_points": [f"{label}要点 {i + 1}" for i in range(3)],
      "writing_hints": f"围绕「{topic}」撰写{label}",
      "word_target": template.get("word_targets", {}).get(st, ""),
    })
  return {"title_suggestion": topic or "未命名论文", "sections": sections}
