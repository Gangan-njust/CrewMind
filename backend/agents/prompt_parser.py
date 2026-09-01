"""从 Markdown 格式角色提示词中提取结构化字段（规则解析，作为 LLM 提取补充）"""
import json
import re

from backend.agents.registry import VALID_TOOLS

_TOOL_LABELS: dict[str, str] = {
  "web_search": "学术文献检索",
  "file_parser": "参考文件解析",
  "code_interpreter": "样本量与预算计算",
  "rag_search": "本地文献库检索",
}

_LABEL_TO_TOOL = {label: tool_id for tool_id, label in _TOOL_LABELS.items()}


def normalize_pasted_prompt(text: str) -> str:
  """规范化粘贴内容：去 BOM、解开外层 Markdown 代码围栏。"""
  cleaned = (text or "").strip().lstrip("\ufeff")
  if not cleaned:
    return cleaned

  fence_match = re.match(
    r"^```(?:markdown|md|text)?\s*\r?\n([\s\S]*?)\r?\n```$",
    cleaned,
    flags=re.IGNORECASE,
  )
  if fence_match:
    return fence_match.group(1).strip()

  return cleaned


def _strip_inline_markdown(text: str) -> str:
  value = text.strip()
  value = re.sub(r"^\s*[-*+]\s+", "", value, flags=re.MULTILINE)
  value = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
  value = re.sub(r"__(.+?)__", r"\1", value)
  value = re.sub(r"`([^`]+)`", r"\1", value)
  return value.strip()


def _extract_section(text: str, headers: list[str]) -> str | None:
  if not headers:
    return None
  escaped = [re.escape(header) for header in headers]
  header_group = "|".join(escaped)
  pattern = re.compile(
    rf"(?:^|\n)\s*(?:#{{1,6}}\s*)?(?:{header_group})\s*\r?\n+"
    rf"([\s\S]*?)"
    rf"(?=\n\s*(?:#{{1,6}}\s*)?(?:{header_group}|可用工具|工具|tools|工作原则|role|goal|backstory|background|专业背景|核心目标|名称|name)\s*(?:\r?\n|$)|\Z)",
    flags=re.IGNORECASE,
  )
  match = pattern.search(text)
  if not match:
    return None
  body = match.group(1).strip()
  return body or None


def _parse_tools(raw: str) -> list[str]:
  cleaned = _strip_inline_markdown(raw)
  if not cleaned or cleaned in {"无", "none", "None", "N/A"}:
    return []

  found: list[str] = []
  for token in re.split(r"[,，、\s]+", cleaned):
    token = token.strip()
    if not token:
      continue
    lower = token.lower()
    if lower in VALID_TOOLS:
      found.append(lower)
      continue
    if token in _LABEL_TO_TOOL:
      found.append(_LABEL_TO_TOOL[token])
      continue
    for tool_id, label in _TOOL_LABELS.items():
      if label in token:
        found.append(tool_id)
        break

  return list(dict.fromkeys(found))


def _parse_labeled_lines(text: str) -> dict:
  result: dict = {}
  labels = {
    "name": ["角色名称", "名称", "name", "role name", "role"],
    "title": ["职称", "头衔", "职称/头衔", "title", "job title"],
    "background": ["专业背景", "背景", "backstory", "background", "角色描述"],
    "goal": ["核心目标", "目标", "goal", "任务目标", "职责"],
    "id": ["角色 id", "角色id", "id", "agent id", "agent_id"],
  }

  for line in text.splitlines():
    for field, names in labels.items():
      for label in names:
        match = re.match(rf"^\s*(?:[-*+]\s*)?(?:#{{1,6}}\s*)?{re.escape(label)}\s*[:：]\s*(.+)$", line, flags=re.I)
        if not match:
          continue
        value = _strip_inline_markdown(match.group(1))
        if value:
          result[field] = value

    tools_match = re.match(r"^\s*(?:[-*+]\s*)?(?:#{1,6}\s*)?(?:可用工具|工具|tools)\s*[:：]\s*(.+)$", line, flags=re.I)
    if tools_match:
      result["tools"] = _parse_tools(tools_match.group(1))

    reasoning_match = re.match(
      r"^\s*(?:[-*+]\s*)?(?:#{1,6}\s*)?(?:推理增强|use_reasoning|reasoning)\s*[:：]\s*(.+)$",
      line,
      flags=re.I,
    )
    if reasoning_match:
      flag = _strip_inline_markdown(reasoning_match.group(1)).lower()
      result["use_reasoning"] = flag in {"true", "1", "yes", "是", "启用", "开启"}

  return result


def parse_markdown_agent_prompt(text: str) -> dict:
  """从 Markdown 提示词中提取字段；无法识别时返回空 dict。"""
  normalized = normalize_pasted_prompt(text)
  if not normalized:
    return {}

  result: dict = {}

  try:
    json_data = json.loads(normalized)
    if isinstance(json_data, dict):
      result.update(json_data)
  except json.JSONDecodeError:
    pass

  result.update(_parse_labeled_lines(normalized))

  title_match = re.search(r"你(?:是一)?位(?:专业的)?(.+?)[。.\n]", normalized)
  if title_match and not result.get("title"):
    result["title"] = _strip_inline_markdown(title_match.group(1))

  first_heading = re.search(r"^#\s+(.+)$", normalized, flags=re.MULTILINE)
  if first_heading and not result.get("name"):
    result["name"] = _strip_inline_markdown(first_heading.group(1))

  section_map = {
    "background": ["专业背景", "背景", "backstory", "background"],
    "goal": ["核心目标", "目标", "goal"],
  }
  for field, headers in section_map.items():
    if not result.get(field):
      section = _extract_section(normalized, headers)
      if section:
        result[field] = section.strip()

  if "tools" not in result:
    tools_section = _extract_section(normalized, ["可用工具", "工具", "tools"])
    if tools_section:
      result["tools"] = _parse_tools(tools_section.replace("\n", " "))

  if not result.get("name") and result.get("title"):
    result["name"] = str(result["title"])[:20]

  cleaned = {}
  for key, value in result.items():
    if value is None:
      continue
    if key == "tools" and isinstance(value, list):
      cleaned[key] = value
    elif key == "use_reasoning":
      cleaned[key] = bool(value)
    elif isinstance(value, str) and value.strip():
      cleaned[key] = value.strip()
    elif key in {"name", "title", "background", "goal", "id"} and value:
      cleaned[key] = str(value).strip()
  return cleaned


def merge_extracted_fields(*parts: dict) -> dict:
  merged: dict = {}
  for part in parts:
    for key, value in part.items():
      if value is None:
        continue
      if key == "tools" and isinstance(value, list):
        merged[key] = list(dict.fromkeys([*(merged.get(key) or []), *value]))
      elif key in {"background", "goal"} and isinstance(value, str):
        current = merged.get(key)
        if not current or len(value.strip()) > len(str(current).strip()):
          merged[key] = value.strip()
      elif value != "" and value is not False:
        merged[key] = value
  return merged
