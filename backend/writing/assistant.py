"""学术写作核心功能：扩写、润色、检查"""
import json
import logging
import re

from backend.llm.client import llm_client
from backend.writing.prompts import (
  COHERENCE_CHECK_PROMPT,
  EXPAND_PROMPT,
  FIGURE_CHECK_PROMPT,
  POLISH_PROMPT,
  STRUCTURED_EXPAND_PROMPT,
  STRUCTURED_POLISH_PROMPT,
  STYLE_CHECK_PROMPT,
  TERM_CHECK_PROMPT,
  get_section_label,
)
from backend.writing.templates import is_abstract_section
from backend.writing.figure_hints import scan_project_figure_hints

logger = logging.getLogger(__name__)

LENGTH_LABELS = {
  "short": "短（适度扩展）",
  "medium": "中（重组并充实）",
  "long": "长（全面扩写）",
}
POLISH_LABELS = {"conservative": "保守润色", "moderate": "中等润色", "deep": "深度润色"}

SECTION_TYPE_TO_KEYS: dict[str, list[str]] = {
  "intro": ["introduction", "preamble", "abstract"],
  "methods": ["methods"],
  "results": ["results"],
  "discussion": ["discussion", "results"],
  "conclusion": ["conclusion", "discussion"],
  "related_work": ["introduction", "methods", "discussion"],
}


def _infer_section_keys(section_type: str) -> list[str] | None:
  return SECTION_TYPE_TO_KEYS.get(section_type)


def _fetch_rag_context(
  workspace_id: str | None,
  query: str,
  section_type: str,
) -> tuple[str, int]:
  if not workspace_id:
    return "", 0
  from backend.config import settings as app_settings
  if not app_settings.rag_enabled:
    return "", 0
  try:
    from backend.rag.context_builder import build_rag_context
    from backend.rag.retriever import retrieve
    hits = retrieve(
      workspace_id,
      query,
      section_keys=_infer_section_keys(section_type),
    )
    if not hits:
      return "", 0
    return build_rag_context(hits), len(hits)
  except Exception as e:
    logger.warning("扩写 RAG 检索失败: %s", e)
    return "", 0


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


async def _llm_text(prompt: str, temperature: float = 0.5) -> str:
  response = await llm_client.chat(
    [{"role": "user", "content": prompt}],
    temperature=temperature,
  )
  if hasattr(response, "__aiter__"):
    chunks = []
    async for chunk in response:
      chunks.append(chunk)
    response = "".join(chunks)
  return str(response).strip()


async def _llm_json(prompt: str, temperature: float = 0.3) -> dict:
  return _parse_json_response(await _llm_text(prompt, temperature))


def _format_structured_items(items: list[dict]) -> str:
  parts: list[str] = []
  for index, item in enumerate(items, start=1):
    title = str(item.get("title", "")).strip()
    level = int(item.get("level", 2))
    level = level if level in (2, 3, 4) else 2
    word_target = int(item.get("word_target", 300))
    requirements = str(item.get("requirements", "")).strip() or "（无额外要求）"
    outline_points = item.get("outline_points") or []
    if not isinstance(outline_points, list):
      outline_points = []
    points_text = "\n".join(f"     - {str(point).strip()}" for point in outline_points if str(point).strip())
    if not points_text:
      points_text = "     （无）"
    existing = str(item.get("existing_content", "")).strip() or "（暂无已有内容，请新撰）"
    if len(existing) > 2000:
      existing = existing[:2000] + "\n...(内容已截断)"
    parts.append(
      f"{index}. 【{title}】\n"
      f"   标题格式：{'#' * level} {title}\n"
      f"   目标字数：约 {word_target} 字\n"
      f"   写作要求：{requirements}\n"
      f"   大纲要点：\n{points_text}\n"
      f"   已有内容：\n{existing}"
    )
  return "\n\n".join(parts)


async def expand_writing_structured(
  preamble: str,
  *,
  section_type: str = "intro",
  topic: str = "",
  global_requirements: str = "",
  items: list[dict],
  workspace_id: str | None = None,
) -> dict:
  if is_abstract_section(section_type):
    raise ValueError("摘要章节不支持目录结构扩写")
  enabled_items = [item for item in items if item.get("enabled", True)]
  if not enabled_items:
    raise ValueError("请至少启用一个小节进行扩写")

  rag_context, rag_count = _fetch_rag_context(
    workspace_id,
    f"{topic}\n{preamble}\n{global_requirements}",
    section_type,
  )
  rag_block = rag_context if rag_context else "（未注入文献证据）"

  prompt = STRUCTURED_EXPAND_PROMPT.format(
    section_label=get_section_label(section_type),
    topic=topic or "未指定",
    preamble=preamble.strip() or "（无）",
    global_requirements=global_requirements.strip() or "（无）",
    items_spec=_format_structured_items(enabled_items),
    rag_context=rag_block,
  )
  try:
    text = await _llm_text(prompt, temperature=0.5)
    return {
      "original_text": preamble,
      "expanded_text": text,
      "mode": "structured",
      "items": enabled_items,
      "rag_evidence_count": rag_count,
    }
  except Exception as e:
    logger.error("目录结构扩写失败: %s", e)
    raise ValueError(f"目录结构扩写失败: {e}")


async def expand_writing(
  input_text: str,
  *,
  section_type: str = "intro",
  topic: str = "",
  length: str = "medium",
  mode: str = "free",
  global_requirements: str = "",
  items: list[dict] | None = None,
  workspace_id: str | None = None,
) -> dict:
  if mode == "structured":
    return await expand_writing_structured(
      input_text,
      section_type=section_type,
      topic=topic,
      global_requirements=global_requirements,
      items=items or [],
      workspace_id=workspace_id,
    )

  if not input_text.strip():
    raise ValueError("请先输入章节内容再进行扩写")

  rag_context, rag_count = _fetch_rag_context(
    workspace_id,
    f"{topic}\n{input_text[:2000]}",
    section_type,
  )
  rag_block = rag_context if rag_context else "（未注入文献证据）"

  prompt = EXPAND_PROMPT.format(
    length_label=LENGTH_LABELS.get(length, "中"),
    section_label=get_section_label(section_type),
    topic=topic or "未指定",
    input_text=input_text[:12000],
    rag_context=rag_block,
  )
  if section_type == "abstract":
    prompt += (
      "\n\n补充要求（中文摘要）："
      "控制在约300字；输出为连贯中文段落；禁止使用任何 Markdown 标题（##、### 等）。"
    )
  elif section_type == "abstract_en":
    prompt += (
      "\n\nAdditional requirements (English Abstract): "
      "Write in English, about 250-300 words; continuous paragraphs only; "
      "no Markdown headings (##, ###, etc.)."
    )
  try:
    text = await _llm_text(prompt, temperature=0.5)
    return {
      "original_text": input_text,
      "expanded_text": text,
      "length": length,
      "rag_evidence_count": rag_count,
    }
  except Exception as e:
    logger.error("扩写失败: %s", e)
    raise ValueError(f"扩写失败: {e}")


async def continue_writing(
  prefix: str,
  *,
  section_type: str = "intro",
  topic: str = "",
  context: str = "",
  length: str = "medium",
) -> dict:
  """兼容旧接口，内部转为扩写（使用完整上下文）"""
  full_text = context.strip() if context.strip() else prefix
  result = await expand_writing(
    full_text,
    section_type=section_type,
    topic=topic,
    length=length,
  )
  return {"continued_text": result["expanded_text"], "expanded_text": result["expanded_text"], "length": length}


async def polish_text_structured(
  preamble: str,
  *,
  section_type: str = "intro",
  topic: str = "",
  style: str = "moderate",
  global_requirements: str = "",
  items: list[dict],
  workspace_id: str | None = None,
) -> dict:
  if is_abstract_section(section_type):
    raise ValueError("摘要章节不支持目录结构润色")
  enabled_items = [item for item in items if item.get("enabled", True)]
  if not enabled_items:
    raise ValueError("请至少启用一个小节进行润色")

  rag_context, rag_count = _fetch_rag_context(
    workspace_id,
    f"{topic}\n{preamble}",
    section_type,
  )
  rag_block = rag_context if rag_context else "（未注入文献证据）"

  prompt = STRUCTURED_POLISH_PROMPT.format(
    style_label=POLISH_LABELS.get(style, "中等润色"),
    section_label=get_section_label(section_type),
    topic=topic or "未指定",
    preamble=preamble.strip() or "（无）",
    global_requirements=global_requirements.strip() or "（无）",
    items_spec=_format_structured_items(enabled_items),
    rag_context=rag_block,
  )
  try:
    result = await _llm_json(prompt, temperature=0.4)
    polished = str(result.get("polished_text", "")).strip()
    if not polished:
      raise ValueError("模型未返回润色正文")
    return {
      "original": preamble,
      "polished_text": polished,
      "changes_summary": result.get("changes_summary", []),
      "mode": "structured",
      "style": style,
      "rag_evidence_count": rag_count,
    }
  except Exception as e:
    logger.error("目录结构润色失败: %s", e)
    raise ValueError(f"目录结构润色失败: {e}")


async def polish_text(
  text: str,
  *,
  section_type: str = "intro",
  topic: str = "",
  style: str = "moderate",
  mode: str = "free",
  global_requirements: str = "",
  items: list[dict] | None = None,
  workspace_id: str | None = None,
) -> dict:
  if mode == "structured":
    return await polish_text_structured(
      text,
      section_type=section_type,
      topic=topic,
      style=style,
      global_requirements=global_requirements,
      items=items or [],
      workspace_id=workspace_id,
    )

  if not text.strip():
    raise ValueError("请先输入章节内容再进行润色")

  rag_context, rag_count = _fetch_rag_context(
    workspace_id,
    f"{topic}\n{text[:2000]}",
    section_type,
  )
  rag_block = rag_context if rag_context else "（未注入文献证据）"

  prompt = POLISH_PROMPT.format(
    style_label=POLISH_LABELS.get(style, "中等润色"),
    section_label=get_section_label(section_type),
    text=text,
    rag_context=rag_block,
  )
  try:
    result = await _llm_json(prompt, temperature=0.4)
    return {
      "original": text,
      "polished_text": result.get("polished_text", text),
      "changes_summary": result.get("changes_summary", []),
      "style": style,
      "mode": "free",
      "rag_evidence_count": rag_count,
    }
  except Exception as e:
    logger.error("润色失败: %s", e)
    raise ValueError(f"润色失败: {e}")


async def check_terminology(full_text: str) -> dict:
  prompt = TERM_CHECK_PROMPT.format(full_text=full_text[:12000])
  try:
    return await _llm_json(prompt)
  except Exception as e:
    logger.error("术语检查失败: %s", e)
    return {"terms": [], "suggestions": [], "error": str(e)}


async def apply_term_replacement(full_text: str, replacements: list[dict]) -> dict:
  result = full_text
  applied = []
  for rep in replacements:
    old = rep.get("from", "")
    new = rep.get("to", "")
    if old and old in result:
      result = result.replace(old, new)
      applied.append({"from": old, "to": new})
  return {"text": result, "applied": applied}


async def check_coherence(outline: list, sections: list[dict]) -> dict:
  summary_parts = []
  for sec in sections:
    content = sec.get("content", "")
    preview = content[:500] + ("..." if len(content) > 500 else "")
    summary_parts.append(f"【{get_section_label(sec.get('section_type', ''))}】\n{preview}")

  prompt = COHERENCE_CHECK_PROMPT.format(
    outline=json.dumps(outline, ensure_ascii=False)[:4000],
    sections_summary="\n\n".join(summary_parts),
  )
  try:
    return await _llm_json(prompt)
  except Exception as e:
    logger.error("连贯性检查失败: %s", e)
    return {"issues": [], "overall_score": 0, "summary": str(e)}


async def check_style(text: str, section_type: str = "intro") -> dict:
  prompt = STYLE_CHECK_PROMPT.format(
    section_label=get_section_label(section_type),
    text=text[:8000],
  )
  try:
    return await _llm_json(prompt)
  except Exception as e:
    logger.error("规范性检查失败: %s", e)
    return {"issues": [], "score": 0, "error": str(e)}


def rule_based_style_check(text: str) -> list[dict]:
  """基于规则的快速规范性检查"""
  issues = []
  first_person = re.findall(r"(我|我们|咱们)", text)
  if first_person:
    issues.append({
      "type": "first_person",
      "text": "、".join(set(first_person[:5])),
      "suggestion": "建议使用第三人称或被动语态，如「本研究」「实验结果表明」",
      "severity": "medium",
    })

  bad_data = re.findall(r"(\d+\.?\d*)\s*[+＋]\s*[-−]?\s*(\d+\.?\d*)", text)
  for mean, std in bad_data[:3]:
    issues.append({
      "type": "data_format",
      "text": f"{mean}±{std}",
      "suggestion": f"建议使用规范格式：{mean} ± {std}（均值 ± 标准差，注意空格）",
      "severity": "low",
    })

  return issues


def clean_blank_lines(text: str) -> dict:
  """去除多余空行：修剪行尾空白、合并连续空行、删除首尾空行"""
  if not text:
    return {
      "cleaned_text": "",
      "removed_count": 0,
      "summary": "内容为空，无需处理",
      "changed": False,
    }

  lines = text.split("\n")
  empty_before = sum(1 for line in lines if not line.strip())

  result_lines: list[str] = []
  prev_blank = False
  for line in lines:
    stripped = line.rstrip()
    is_blank = not stripped
    if is_blank:
      if not prev_blank and result_lines:
        result_lines.append("")
      prev_blank = True
    else:
      result_lines.append(stripped)
      prev_blank = False

  while result_lines and result_lines[0] == "":
    result_lines.pop(0)
  while result_lines and result_lines[-1] == "":
    result_lines.pop()

  cleaned = "\n".join(result_lines)
  empty_after = sum(1 for line in cleaned.split("\n") if not line.strip()) if cleaned else 0
  removed = max(empty_before - empty_after, 0)
  # 连续空行合并时，removed 可能为 0；用行数差补充统计
  if removed == 0 and len(lines) != len(cleaned.split("\n")):
    removed = max(len(lines) - len(cleaned.split("\n")), 0)

  changed = cleaned != text
  summary = (
    f"已去除 {removed} 处多余空行"
    if changed
    else "格式规范，未发现多余空行"
  )

  return {
    "cleaned_text": cleaned,
    "removed_count": removed,
    "summary": summary,
    "changed": changed,
  }


# ── 图表完整性检查 ───────────────────────────────────────────

_VALID_CHART_TYPES = frozenset({
  "柱状图", "折线图", "散点图", "箱线图", "直方图", "流程图", "结构图", "表格", "示意图",
})


def _section_anchor_block(sections: list[dict]) -> str:
  """把各章节正文组装为带章节标签的文本（供 LLM 检查）。"""
  parts: list[str] = []
  for sec in sections:
    content = (sec.get("content") or "").strip()
    if not content:
      continue
    label = get_section_label(sec.get("section_type", ""))
    parts.append(f"## {label}（{sec.get('section_type', '')}）\n{content[:4000]}")
  return "\n\n".join(parts)


def _compact(text: str) -> str:
  return re.sub(r"\s+", "", text or "")


def _find_line_for_anchor(content: str, anchor: str) -> int | None:
  """在章节正文中定位锚点句的行号（1 基）。"""
  needle = _compact(anchor)
  if not needle:
    return None
  lines = content.split("\n")
  for idx, raw in enumerate(lines):
    if needle in _compact(raw):
      return idx + 1
  # 退而求其次：锚点前 12 个有效字符匹配到某行
  prefix = needle[:12]
  if prefix:
    for idx, raw in enumerate(lines):
      if prefix in _compact(raw):
        return idx + 1
  return None


def _normalize_chart_type(raw: str | None) -> str:
  value = str(raw or "").strip()
  return value if value in _VALID_CHART_TYPES else "图表"


def _normalize_severity(raw: str | None) -> str:
  value = str(raw or "").strip().lower()
  return value if value in ("high", "medium", "low") else "medium"


def _normalize_llm_issues(project: dict, raw_issues: list | None) -> list[dict]:
  """把 LLM 返回的 issue 定位到具体章节与行号，无法锚定的丢弃。"""
  if not raw_issues:
    return []
  sections = project.get("sections", [])
  issues: list[dict] = []
  seen: set[str] = set()
  for issue in raw_issues:
    if not isinstance(issue, dict):
      continue
    st = str(issue.get("section_type", "")).strip()
    anchor = str(issue.get("anchor_text", "")).strip()
    if not anchor:
      continue
    target_sections = [s for s in sections if s.get("section_type") == st and (s.get("content") or "").strip()]
    if not target_sections:
      target_sections = [s for s in sections if (s.get("content") or "").strip()]
      if not target_sections:
        continue
      st = target_sections[0].get("section_type", "")
    matched: tuple[dict, int] | None = None
    for sec in target_sections:
      line = _find_line_for_anchor(sec.get("content", ""), anchor)
      if line is not None:
        matched = (sec, line)
        break
    if not matched:
      continue
    sec, line = matched
    chart_type = _normalize_chart_type(issue.get("chart_type"))
    key = f"{sec.get('id', '')}:{line}:{chart_type}"
    if key in seen:
      continue
    seen.add(key)
    issues.append({
      "section_id": sec.get("id", ""),
      "section_type": st,
      "display_title": sec.get("display_title", sec.get("title", ""))
      or get_section_label(st),
      "line": line,
      "anchor_text": _compact(anchor)[:120],
      "chart_type": chart_type,
      "reason": str(issue.get("reason", "")).strip() or "按学术规范此处应配图表",
      "suggestion": str(issue.get("suggestion", "")).strip() or "建议插入对应图表并补充图注与编号。",
      "severity": _normalize_severity(issue.get("severity")),
      "key": key,
    })
  return issues


async def check_figures(project: dict, *, use_llm: bool = True) -> dict:
  """图表完整性检查：规则预检 + LLM 语义细化（use_llm=False 时仅规则）。

  返回与 scan_project_figure_hints 兼容的 payload，并附 used_llm / llm_issue_count。
  LLM 不可用时自动降级为规则结果。
  """
  rule_report = scan_project_figure_hints(project)
  sections = sorted(
    project.get("sections", []),
    key=lambda s: (s.get("sort_order", 0) if s.get("sort_order") is not None else 999,),
  )
  rule_issues = rule_report.get("issues", [])
  summary = str(rule_report.get("summary", ""))
  used_llm = False

  llm_issues: list[dict] = []
  if use_llm:
    full_text = _section_anchor_block(sections)
    if full_text.strip():
      candidates_preview = [
        {
          "section_type": i.get("section_type", ""),
          "line": i.get("line", 0),
          "anchor_text": i.get("anchor_text", ""),
          "chart_type": i.get("chart_type", ""),
        }
        for i in rule_issues[:10]
      ]
      prompt = FIGURE_CHECK_PROMPT.format(
        full_text=full_text[:16000],
        candidates=json.dumps(candidates_preview, ensure_ascii=False) or "（无）",
      )
      try:
        data = await _llm_json(prompt)
        llm_issues = _normalize_llm_issues(project, data.get("issues") if isinstance(data, dict) else None)
        llm_summary = str((data or {}).get("summary", "")).strip()
        used_llm = True
        if llm_summary:
          summary = llm_summary
      except Exception as e:
        logger.error("图表完整性 LLM 检查失败，降级为规则结果: %s", e)

  # 合并：LLM 结果优先，规则结果中未被 LLM 覆盖的补充进去
  merged: list[dict] = list(llm_issues)
  covered_rule_indices: list[int] = []
  for idx, rule in enumerate(rule_issues):
    rule_sec = rule.get("section_id", "")
    rule_line = rule.get("line", 0)
    rule_compact = _compact(rule.get("anchor_text", ""))
    covered = False
    for llm in llm_issues:
      if llm.get("section_id") != rule_sec:
        continue
      if abs(int(llm.get("line", 0)) - int(rule_line)) <= 2:
        covered = True
        break
      llm_compact = _compact(llm.get("anchor_text", ""))
      if rule_compact and llm_compact and (
        rule_compact[:12] in llm_compact or llm_compact[:12] in rule_compact
      ):
        covered = True
        break
    if covered:
      covered_rule_indices.append(idx)
  for idx, rule in enumerate(rule_issues):
    if idx not in covered_rule_indices:
      merged.append(rule)

  issue_count = len(merged)
  return {
    "issues": merged,
    "figure_count": rule_report.get("figure_count", 0),
    "table_count": rule_report.get("table_count", 0),
    "section_count": rule_report.get("section_count", 0),
    "summary": summary or f"全文共发现 {issue_count} 处建议配图位置。",
    "used_llm": used_llm,
    "llm_issue_count": len(llm_issues),
  }

