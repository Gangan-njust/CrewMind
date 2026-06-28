"""学术文献检索：Semantic Scholar + PubMed 回退"""
import json
import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from backend.config import settings
from backend.tools.base import BaseTool

logger = logging.getLogger(__name__)

SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
PUBMED_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class WebSearchTool(BaseTool):
  name = "web_search"
  description = "搜索学术文献（Semantic Scholar / PubMed），返回标题、作者、摘要与链接"

  async def run(self, query: str = "", max_results: int = 5, **_) -> str:
    if not query:
      return "错误：请提供搜索关键词"

    databases_used: list[str] = []
    results: list[dict[str, Any]] = []
    try:
      results = await self._search_semantic_scholar(query, max_results)
      if results:
        databases_used.append("Semantic Scholar")
    except Exception as e:
      logger.warning("Semantic Scholar 检索失败: %s", e)

    if not results:
      try:
        results = await self._search_pubmed(query, max_results)
        if results:
          databases_used.append("PubMed")
      except Exception as e:
        logger.warning("PubMed 检索失败: %s", e)

    if not results:
      return (
        f"未找到与「{query}」直接相关的文献。"
        "请基于领域知识撰写，并明确标注需人工补充引用的部分；"
        "文末仍须包含「参考文献」与「文献数据库说明」章节。"
      )

    payload = {
      "databases_used": databases_used,
      "query": query,
      "papers": results,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)

  async def _search_semantic_scholar(self, query: str, limit: int) -> list[dict[str, Any]]:
    headers: dict[str, str] = {}
    if settings.semantic_scholar_api_key:
      headers["x-api-key"] = settings.semantic_scholar_api_key

    params = {
      "query": query,
      "limit": limit,
      "fields": "title,authors,year,abstract,url,externalIds,citationCount,journal",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
      resp = await client.get(SEMANTIC_SCHOLAR_URL, params=params, headers=headers)
      if resp.status_code == 429:
        logger.warning("Semantic Scholar 请求限流，将尝试 PubMed")
        return []
      resp.raise_for_status()
      data = resp.json()

    papers = data.get("data") or []
    results: list[dict[str, Any]] = []
    for paper in papers:
      authors = paper.get("authors") or []
      author_names = ", ".join(
        a.get("name", "") for a in authors[:4] if a.get("name")
      )
      external = paper.get("externalIds") or {}
      doi = external.get("DOI", "")
      journal = paper.get("journal") or {}
      journal_name = journal.get("name", "") if isinstance(journal, dict) else ""

      results.append({
        "title": paper.get("title") or "无标题",
        "authors": author_names or "未知",
        "year": paper.get("year"),
        "abstract": (paper.get("abstract") or "")[:600],
        "url": paper.get("url") or (f"https://doi.org/{doi}" if doi else ""),
        "citation_count": paper.get("citationCount"),
        "journal": journal_name,
        "doi": doi,
        "source": "Semantic Scholar",
      })
    return results

  async def _search_pubmed(self, query: str, limit: int) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
      esearch = await client.get(
        f"{PUBMED_EUTILS}/esearch.fcgi",
        params={
          "db": "pubmed",
          "retmode": "json",
          "retmax": limit,
          "term": query,
        },
      )
      esearch.raise_for_status()
      idlist = esearch.json().get("esearchresult", {}).get("idlist", [])
      if not idlist:
        return []

      efetch = await client.get(
        f"{PUBMED_EUTILS}/efetch.fcgi",
        params={
          "db": "pubmed",
          "id": ",".join(idlist),
          "retmode": "xml",
        },
      )
      efetch.raise_for_status()

    return self._parse_pubmed_xml(efetch.text)

  def _parse_pubmed_xml(self, xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    articles: list[dict[str, Any]] = []

    for article in root.findall(".//PubmedArticle"):
      pmid = (article.findtext(".//PMID") or "").strip()
      title = (article.findtext(".//ArticleTitle") or "").strip()
      abstract_parts = article.findall(".//AbstractText")
      abstract = " ".join((p.text or "").strip() for p in abstract_parts).strip()
      year = (article.findtext(".//PubDate/Year") or "").strip()

      authors: list[str] = []
      for author in article.findall(".//Author"):
        last = (author.findtext("LastName") or "").strip()
        fore = (author.findtext("ForeName") or "").strip()
        if last:
          authors.append(f"{last} {fore}".strip())

      if not title:
        continue

      articles.append({
        "title": title,
        "authors": ", ".join(authors[:4]) or "未知",
        "year": int(year) if year.isdigit() else year,
        "abstract": abstract[:600],
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        "pmid": pmid,
        "source": "PubMed",
      })

    return articles
