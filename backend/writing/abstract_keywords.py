"""摘要与关键词提取、生成与英文化检查"""
import json
import logging
import re

from backend.llm.client import llm_client
from backend.writing.prompts import (
  ABSTRACT_TRANSLATION_PROMPT,
  KEYWORDS_GENERATION_PROMPT,
  KEYWORDS_TRANSLATION_PROMPT,
)

logger = logging.getLogger(__name__)

KEYWORDS_ZH_PATTERN = re.compile(r"^\s*关键词[：:]\s*(.+)$", re.MULTILINE)
KEYWORDS_EN_PATTERN = re.compile(r"^\s*Keywords[：:]\s*(.+)$", re.MULTILINE | re.IGNORECASE)


def _parse_json_response(text: str) -> dict:
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


async def _llm_text(prompt: str) -> str:
  response = await llm_client.chat(
    [{"role": "user", "content": prompt}],
    temperature=0.3,
  )
  if hasattr(response, "__aiter__"):
    chunks = []
    async for chunk in response:
      chunks.append(chunk)
    response = "".join(chunks)
  return str(response).strip()


def is_primarily_english(text: str) -> bool:
  text = text.strip()
  if not text:
    return False
  chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
  return chinese / max(len(text), 1) < 0.05


def parse_keyword_list(text: str, *, english: bool = False) -> list[str]:
  if not text.strip():
    return []
  sep = r"[;；,，]" if english else r"[;；,，、]"
  parts = re.split(sep, text)
  return [p.strip() for p in parts if p.strip()]


def format_keywords_zh(keywords: list[str]) -> str:
  return "；".join(k.strip() for k in keywords if k.strip())


def format_keywords_en(keywords: list[str]) -> str:
  return "; ".join(k.strip() for k in keywords if k.strip())


def split_abstract_content(content: str, *, english: bool = False) -> tuple[str, list[str]]:
  """分离摘要正文与末尾关键词行，返回 (正文, 关键词列表)。"""
  body = (content or "").strip()
  keywords: list[str] = []
  pattern = KEYWORDS_EN_PATTERN if english else KEYWORDS_ZH_PATTERN
  match = pattern.search(body)
  if match:
    keywords = parse_keyword_list(match.group(1), english=english)
    body = body[: match.start()].strip()
  return body, keywords


def compose_abstract_content(body: str, keywords: list[str], *, english: bool = False) -> str:
  body = body.strip()
  if not keywords:
    return body
  label = "Keywords" if english else "关键词"
  formatted = format_keywords_en(keywords) if english else format_keywords_zh(keywords)
  if not body:
    return f"{label}：{formatted}" if not english else f"{label}: {formatted}"
  sep = "\n\n"
  suffix = f"{label}：{formatted}" if not english else f"{label}: {formatted}"
  return f"{body}{sep}{suffix}"


def get_section_content(sections: list[dict], section_type: str) -> str:
  for sec in sections:
    if sec.get("section_type") == section_type:
      return sec.get("content") or ""
  return ""


async def generate_keywords_from_abstract(abstract_zh: str, topic: str = "") -> dict:
  body, _ = split_abstract_content(abstract_zh, english=False)
  if len(body.strip()) < 20:
    raise ValueError("中文摘要内容过短，请先撰写摘要（至少约 20 字）")

  prompt = KEYWORDS_GENERATION_PROMPT.format(
    abstract=body[:3000],
    topic=topic or "未指定",
  )
  try:
    result = await _llm_json(prompt)
    keywords = result.get("keywords") or []
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    if len(keywords) < 3:
      raise ValueError("生成的关键词数量不足")
    return {"keywords_zh": keywords[:5], "abstract_body": body}
  except Exception as e:
    logger.error("关键词生成失败: %s", e)
    raise ValueError(f"关键词生成失败: {e}")


async def translate_abstract_to_english(abstract_zh: str, topic: str = "") -> str:
  body, _ = split_abstract_content(abstract_zh, english=False)
  if len(body.strip()) < 20:
    raise ValueError("中文摘要内容过短，无法翻译")

  prompt = ABSTRACT_TRANSLATION_PROMPT.format(
    abstract=body[:4000],
    topic=topic or "未指定",
  )
  try:
    text = await _llm_text(prompt)
    return text.strip()
  except Exception as e:
    logger.error("摘要翻译失败: %s", e)
    raise ValueError(f"摘要翻译失败: {e}")


async def translate_keywords_to_english(keywords_zh: list[str]) -> list[str]:
  if not keywords_zh:
    raise ValueError("请先设置中文关键词")

  prompt = KEYWORDS_TRANSLATION_PROMPT.format(
    keywords=format_keywords_zh(keywords_zh),
  )
  try:
    result = await _llm_json(prompt)
    keywords = result.get("keywords") or []
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    if not keywords:
      raise ValueError("英文关键词翻译结果为空")
    return keywords[:5]
  except Exception as e:
    logger.error("关键词翻译失败: %s", e)
    raise ValueError(f"关键词翻译失败: {e}")


async def check_abstract_and_keywords(project: dict) -> dict:
  sections = project.get("sections", [])
  topic = project.get("topic", "")

  abstract_zh_raw = get_section_content(sections, "abstract")
  abstract_en_raw = get_section_content(sections, "abstract_en")

  abstract_zh_body, inline_kw_zh = split_abstract_content(abstract_zh_raw, english=False)
  abstract_en_body, inline_kw_en = split_abstract_content(abstract_en_raw, english=True)

  keywords_zh = project.get("keywords_zh") or inline_kw_zh
  keywords_en = project.get("keywords_en") or inline_kw_en

  issues: list[dict] = []
  abstract_en_ok = is_primarily_english(abstract_en_body)
  keywords_en_ok = bool(keywords_en) and all(is_primarily_english(k) for k in keywords_en)

  abstract_en_suggested = ""
  keywords_en_suggested: list[str] = []

  if not abstract_zh_body.strip():
    issues.append({
      "severity": "high",
      "description": "缺少中文摘要",
      "suggestion": "请先在「摘要」章节撰写中文摘要",
    })
  elif not abstract_en_body.strip():
    issues.append({
      "severity": "high",
      "description": "英文 Abstract 为空",
      "suggestion": "将根据中文摘要自动翻译生成",
    })
    abstract_en_suggested = await translate_abstract_to_english(abstract_zh_raw, topic)
    abstract_en_ok = False
  elif not abstract_en_ok:
    issues.append({
      "severity": "medium",
      "description": "Abstract 未使用规范英文（含中文或非英文学术表述）",
      "suggestion": "将根据中文摘要重新翻译为英文",
    })
    abstract_en_suggested = await translate_abstract_to_english(abstract_zh_raw, topic)

  if not keywords_zh:
    issues.append({
      "severity": "medium",
      "description": "未设置中文关键词",
      "suggestion": "可使用「从摘要生成关键词」自动生成 3–5 个关键词",
    })
  elif not keywords_en:
    issues.append({
      "severity": "medium",
      "description": "未设置英文 Keywords",
      "suggestion": "将根据中文关键词自动翻译",
    })
    keywords_en_suggested = await translate_keywords_to_english(keywords_zh)
    keywords_en_ok = False
  elif not keywords_en_ok:
    issues.append({
      "severity": "medium",
      "description": "英文 Keywords 不规范（含中文或非英文词条）",
      "suggestion": "将根据中文关键词重新翻译",
    })
    keywords_en_suggested = await translate_keywords_to_english(keywords_zh)

  needs_fix = bool(abstract_en_suggested or keywords_en_suggested)
  summary_parts = []
  if abstract_en_ok and keywords_en_ok and keywords_zh:
    summary = "摘要与关键词检查通过：Abstract 为英文，Keywords 格式规范。"
  else:
    if not abstract_en_ok:
      summary_parts.append("Abstract 需修正")
    if not keywords_en_ok:
      summary_parts.append("英文 Keywords 需修正")
    if not keywords_zh:
      summary_parts.append("缺少中文关键词")
    summary = "检查完成：" + "；".join(summary_parts) + "。"

  return {
    "abstract_zh_body": abstract_zh_body,
    "abstract_en_body": abstract_en_body,
    "keywords_zh": keywords_zh,
    "keywords_en": keywords_en,
    "abstract_en_ok": abstract_en_ok,
    "keywords_en_ok": keywords_en_ok,
    "abstract_en_suggested": abstract_en_suggested,
    "keywords_en_suggested": keywords_en_suggested,
    "needs_fix": needs_fix,
    "issues": issues,
    "summary": summary,
  }
