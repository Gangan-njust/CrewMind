"""文献引用智能推荐与格式化"""
import json
import logging
import re

from sqlalchemy import select

from backend.llm.client import llm_client
from backend.storage.database import get_session
from backend.storage.models import LiteratureAnalysisRecord, LiteratureRecord
from backend.writing.prompts import (
  CITATION_COMPLETENESS_PROMPT,
  CITATION_RECOMMEND_PROMPT,
  CITATION_SENTENCE_PROMPT,
)

logger = logging.getLogger(__name__)


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


def _load_authors(authors_json: str) -> list[str]:
  try:
    authors = json.loads(authors_json or "[]")
    return authors if isinstance(authors, list) else []
  except json.JSONDecodeError:
    return []


def _get_workspace_literatures(workspace_id: str) -> list[dict]:
  with get_session() as session:
    rows = session.scalars(
      select(LiteratureRecord)
      .where(LiteratureRecord.workspace_id == workspace_id)
      .order_by(LiteratureRecord.uploaded_at.desc())
    ).all()
    result = []
    for lit in rows:
      analysis = session.scalars(
        select(LiteratureAnalysisRecord).where(
          LiteratureAnalysisRecord.literature_id == lit.id
        )
      ).first()
      result.append({
        "id": lit.id,
        "title": lit.title,
        "authors": _load_authors(lit.authors_json),
        "year": lit.year,
        "journal": lit.journal,
        "abstract": lit.abstract[:500],
        "contribution": analysis.contribution_summary if analysis else "",
        "methods": analysis.methods_summary if analysis else "",
      })
    return result


async def recommend_citations(
  selected_text: str,
  context: str,
  workspace_id: str | None,
) -> dict:
  if not workspace_id:
    return {"recommendations": [], "message": "未关联文献库，请先关联工作空间"}

  literatures = _get_workspace_literatures(workspace_id)
  if not literatures:
    return {"recommendations": [], "message": "文献库为空"}

  lit_list = "\n".join(
    f"- ID:{l['id']} | {l['title']} ({l['year'] or 'n.d.'}) | {', '.join(l['authors'][:3])}"
    for l in literatures[:30]
  )

  prompt = CITATION_RECOMMEND_PROMPT.format(
    selected_text=selected_text,
    context=context[:2000],
    literature_list=lit_list,
  )

  try:
    result = await _llm_json(prompt)
    recs = result.get("recommendations", [])
    lit_map = {l["id"]: l for l in literatures}
    enriched = []
    for rec in recs:
      lit_id = rec.get("literature_id", "")
      if lit_id in lit_map:
        enriched.append({**rec, "literature": lit_map[lit_id]})
    return {"recommendations": enriched}
  except Exception as e:
    logger.error("引用推荐失败: %s", e)
    keyword_matches = _keyword_match(selected_text, literatures)
    return {"recommendations": keyword_matches, "fallback": True}


def _keyword_match(text: str, literatures: list[dict]) -> list[dict]:
  words = set(re.findall(r"[\u4e00-\u9fff]{2,}|\w{4,}", text.lower()))
  scored = []
  for lit in literatures:
    haystack = f"{lit['title']} {lit['abstract']} {lit['contribution']}".lower()
    score = sum(1 for w in words if w in haystack) / max(len(words), 1)
    if score > 0.1:
      scored.append({
        "literature_id": lit["id"],
        "relevance_score": round(min(score, 1.0), 2),
        "reason": "关键词匹配",
        "literature": lit,
      })
  scored.sort(key=lambda x: x["relevance_score"], reverse=True)
  return scored[:5]


async def generate_citation_sentences(literature_id: str, purpose: str = "") -> dict:
  with get_session() as session:
    lit = session.get(LiteratureRecord, literature_id)
    if not lit:
      raise ValueError("文献不存在")

  prompt = CITATION_SENTENCE_PROMPT.format(
    title=lit.title,
    authors=", ".join(_load_authors(lit.authors_json)[:5]) or "Unknown",
    year=lit.year or "n.d.",
    journal=lit.journal or "",
    purpose=purpose or "一般引用",
  )

  try:
    return await _llm_json(prompt)
  except Exception as e:
    logger.error("引用句式生成失败: %s", e)
    authors = _load_authors(lit.authors_json)
    first_author = authors[0] if authors else "Author"
    return {
      "sentences": [
        {"style": "author_prominent", "style_label": "作者突出",
         "text": f"{first_author} 等 ({lit.year or 'n.d.'}) 提出了..."},
        {"style": "idea_prominent", "style_label": "观点突出",
         "text": f"已有研究表明... ({first_author} et al., {lit.year or 'n.d.'})"},
      ]
    }


async def check_citation_completeness(full_text: str) -> dict:
  prompt = CITATION_COMPLETENESS_PROMPT.format(full_text=full_text[:12000])
  try:
    return await _llm_json(prompt)
  except Exception as e:
    logger.error("引用完整性检查失败: %s", e)
    return {"missing_citations": [], "error": str(e)}


def format_reference(lit: dict, fmt: str = "gb7714") -> str:
  authors = lit.get("authors", [])
  title = lit.get("title", "")
  year = lit.get("year", "n.d.")
  journal = lit.get("journal", "")
  doi = lit.get("doi", "")

  if fmt == "apa":
    author_str = ", ".join(authors[:7]) if authors else "Unknown"
    if len(authors) > 7:
      author_str += ", et al."
    ref = f"{author_str} ({year}). {title}."
    if journal:
      ref += f" *{journal}*."
    if doi:
      ref += f" https://doi.org/{doi}"
    return ref

  if fmt == "mla":
    author_str = authors[0] if authors else "Unknown"
    ref = f'{author_str}. "{title}."'
    if journal:
      ref += f" *{journal}*, {year}."
    return ref

  if fmt == "chicago":
    author_str = ", ".join(authors[:3]) if authors else "Unknown"
    ref = f'{author_str}. "{title}."'
    if journal:
      ref += f" *{journal}* ({year})."
    return ref

  author_str = ", ".join(authors[:3]) if authors else "佚名"
  if len(authors) > 3:
    author_str += ", 等"
  ref = f"{author_str}. {title}[J]."
  if journal:
    ref += f" {journal}, {year}."
  else:
    ref += f" {year}."
  if doi:
    ref += f" DOI:{doi}."
  return ref


def format_all_references(literature_ids: list[str], fmt: str = "gb7714") -> list[dict]:
  with get_session() as session:
    refs = []
    for idx, lit_id in enumerate(literature_ids, 1):
      lit = session.get(LiteratureRecord, lit_id)
      if not lit:
        continue
      lit_dict = {
        "id": lit.id,
        "title": lit.title,
        "authors": _load_authors(lit.authors_json),
        "year": lit.year,
        "journal": lit.journal,
        "doi": lit.doi,
      }
      refs.append({
        "index": idx,
        "literature_id": lit.id,
        "formatted": format_reference(lit_dict, fmt),
      })
    return refs
