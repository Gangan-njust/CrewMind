"""文献与开题报告集成"""
import json
import re
from typing import Literal

from backend.literature.prompts import PROPOSAL_CONTEXT_PROMPT
from backend.storage.literature_store import literature_store
from backend.utils.text import sanitize_unicode

DataSourceMode = Literal["only_library", "library_first", "web_first"]

MODE_DESCRIPTIONS = {
  "only_library": "仅使用用户选定的文献库，不补充网络检索内容。",
  "library_first": "以选定文献为主，必要时可调用网络检索补充背景信息，但正文引用优先标注用户文献。",
  "web_first": "以网络检索为主，选定文献作为辅助参考，需在文献数据库说明中区分来源。",
}

SECTION_MAPPING = {
  "research_background": "研究背景",
  "literature_review": "国内外现状",
  "research_significance": "研究意义",
  "research_goal": "研究目标",
  "research_methods": "研究方法",
}


def map_literature_to_sections(literature_ids: list[str], workspace_id: str) -> dict[str, list[dict]]:
  """按开题报告章节匹配选定文献的分析结果"""
  literatures = literature_store.get_literatures_by_ids(workspace_id, literature_ids)
  sections: dict[str, list[dict]] = {k: [] for k in SECTION_MAPPING}

  for idx, lit in enumerate(literatures, 1):
    analysis = lit.get("analysis") or {}
    ref = {
      "ref_number": idx,
      "literature_id": lit["id"],
      "title": lit.get("title", ""),
      "authors": lit.get("authors", []),
      "year": lit.get("year"),
      "doi": lit.get("doi", ""),
    }

    if analysis.get("research_background"):
      sections["research_background"].append({
        **ref,
        "content": analysis["research_background"],
      })
    if analysis.get("contribution_summary") or analysis.get("conclusion"):
      sections["literature_review"].append({
        **ref,
        "content": analysis.get("contribution_summary") or analysis.get("conclusion", ""),
      })
    if analysis.get("research_goal"):
      sections["research_significance"].append({
        **ref,
        "content": analysis.get("research_goal", ""),
      })
      sections["research_goal"].append({
        **ref,
        "content": analysis["research_goal"],
      })
    if analysis.get("methods_summary"):
      sections["research_methods"].append({
        **ref,
        "content": analysis["methods_summary"],
      })

  return sections


def build_proposal_context(
  workspace_id: str,
  literature_ids: list[str],
  topic: str,
  mode: DataSourceMode,
) -> str:
  """构建注入开题报告 Agent 的文献上下文"""
  sections = map_literature_to_sections(literature_ids, workspace_id)
  parts = []
  for section_key, label in SECTION_MAPPING.items():
    items = sections.get(section_key, [])
    if not items:
      continue
    parts.append(f"### {label}")
    for item in items:
      parts.append(
        f"[{item['ref_number']}] {sanitize_unicode(item['title'])} ({item.get('year', '')}): {sanitize_unicode(item['content'])}"
      )

  literature_context = "\n\n".join(parts) if parts else "（无可用分析结果，请先完成文献分析）"
  return PROPOSAL_CONTEXT_PROMPT.format(
    topic=topic,
    literature_context=literature_context,
    mode_description=MODE_DESCRIPTIONS.get(mode, MODE_DESCRIPTIONS["library_first"]),
  )


def extract_citation_markers(text: str) -> list[int]:
  """从报告正文提取引用标记 [n]"""
  return sorted(set(int(m) for m in re.findall(r"\[(\d+)\]", text)))


def generate_reference_list(
  report_text: str,
  literatures: list[dict],
  web_sources: list[dict] | None = None,
) -> tuple[str, list[str]]:
  """
  匹配正文引用标记生成参考文献列表。
  返回 (参考文献 Markdown, 建议补充文献列表)
  """
  markers = extract_citation_markers(report_text)
  lines = ["## 参考文献", ""]
  suggested: list[str] = []

  for n in markers:
    if 1 <= n <= len(literatures):
      lit = literatures[n - 1]
      authors = ", ".join(lit.get("authors", [])[:3])
      if len(lit.get("authors", [])) > 3:
        authors += ", 等"
      line = f"[{n}] {authors}. {lit.get('title', '')}. {lit.get('journal', '')}, {lit.get('year', '')}."
      if lit.get("doi"):
        line += f" DOI:{lit['doi']}"
      lines.append(line)
    else:
      suggested.append(f"[{n}] 建议补充文献（引用编号 {n} 未在用户文献库中找到对应条目）")

  if web_sources:
    lines.append("")
    lines.append("## 文献数据库说明")
    lines.append("以下条目来自网络检索，建议核实后补充至文献库：")
    for src in web_sources:
      lines.append(f"- {src.get('title', '')} ({src.get('source', '网络检索')})")

  return "\n".join(lines), suggested
