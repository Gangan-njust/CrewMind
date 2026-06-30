"""DOI/PMID 元数据自动获取"""
import logging
import re

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
PMID_PATTERN = re.compile(r"\b(\d{7,8})\b")


async def fetch_by_doi(doi: str) -> dict:
  """通过 CrossRef API 获取文献元数据"""
  doi = doi.strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
  url = f"https://api.crossref.org/works/{doi}"
  async with httpx.AsyncClient(timeout=30.0) as client:
    resp = await client.get(url, headers={"Accept": "application/json"})
    resp.raise_for_status()
    data = resp.json().get("message", {})

  authors = []
  for author in data.get("author", []):
    given = author.get("given", "")
    family = author.get("family", "")
    name = f"{given} {family}".strip()
    if name:
      authors.append(name)

  year = None
  for date_field in ("published-print", "published-online", "created"):
    parts = data.get(date_field, {}).get("date-parts", [[]])
    if parts and parts[0]:
      year = parts[0][0]
      break

  return {
    "title": (data.get("title") or [""])[0],
    "authors": authors,
    "journal": (data.get("container-title") or [""])[0],
    "year": year,
    "doi": data.get("DOI", doi),
    "abstract": data.get("abstract", "") or "",
  }


async def fetch_by_pmid(pmid: str) -> dict:
  """通过 PubMed E-utilities 获取文献元数据"""
  base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
  async with httpx.AsyncClient(timeout=30.0) as client:
    summary_resp = await client.get(
      f"{base}/esummary.fcgi",
      params={"db": "pubmed", "id": pmid, "retmode": "json"},
    )
    summary_resp.raise_for_status()
    summary = summary_resp.json().get("result", {}).get(pmid, {})

    abstract_resp = await client.get(
      f"{base}/efetch.fcgi",
      params={"db": "pubmed", "id": pmid, "retmode": "xml"},
    )
    abstract_resp.raise_for_status()
    abstract_match = re.search(r"<AbstractText[^>]*>(.*?)</AbstractText>", abstract_resp.text, re.S)
    abstract = re.sub(r"<[^>]+>", " ", abstract_match.group(1)).strip() if abstract_match else ""

  authors = summary.get("authors", [])
  author_names = [a.get("name", "") for a in authors if a.get("name")]

  return {
    "title": summary.get("title", ""),
    "authors": author_names,
    "journal": summary.get("fulljournalname") or summary.get("source", ""),
    "year": int(summary.get("pubdate", "0")[:4] or 0) or None,
    "doi": summary.get("elocationid", "").replace("doi: ", "") if summary.get("elocationid") else "",
    "abstract": abstract,
    "pmid": pmid,
  }


async def fetch_by_semantic_scholar(query: str) -> dict | None:
  """通过 Semantic Scholar 按 DOI 或标题检索"""
  headers = {}
  if settings.semantic_scholar_api_key:
    headers["x-api-key"] = settings.semantic_scholar_api_key

  async with httpx.AsyncClient(timeout=30.0) as client:
    resp = await client.get(
      "https://api.semanticscholar.org/graph/v1/paper/search",
      params={"query": query, "limit": 1, "fields": "title,authors,year,venue,abstract,externalIds"},
      headers=headers,
    )
    if resp.status_code != 200:
      return None
    papers = resp.json().get("data", [])
    if not papers:
      return None
    paper = papers[0]
    ext = paper.get("externalIds") or {}
    return {
      "title": paper.get("title", ""),
      "authors": [a.get("name", "") for a in paper.get("authors", [])],
      "journal": paper.get("venue", ""),
      "year": paper.get("year"),
      "doi": ext.get("DOI", ""),
      "abstract": paper.get("abstract", "") or "",
    }


async def fetch_metadata(identifier: str) -> dict:
  """输入 DOI 或 PMID，自动选择 API 获取元数据"""
  identifier = identifier.strip()
  if not identifier:
    raise ValueError("标识符不能为空")

  doi_match = DOI_PATTERN.search(identifier)
  if doi_match or identifier.lower().startswith("10."):
    doi = doi_match.group(0) if doi_match else identifier
    try:
      return await fetch_by_doi(doi)
    except Exception as e:
      logger.warning("CrossRef 查询失败: %s", e)
      ss = await fetch_by_semantic_scholar(doi)
      if ss:
        return ss
      raise ValueError(f"无法获取 DOI 元数据: {doi}") from e

  pmid_match = PMID_PATTERN.search(identifier)
  if pmid_match or identifier.isdigit():
    pmid = pmid_match.group(1) if pmid_match else identifier
    try:
      return await fetch_by_pmid(pmid)
    except Exception as e:
      raise ValueError(f"无法获取 PMID 元数据: {pmid}") from e

  ss = await fetch_by_semantic_scholar(identifier)
  if ss:
    return ss
  raise ValueError(f"无法识别标识符: {identifier}")


def extract_doi_from_text(text: str) -> str | None:
  match = DOI_PATTERN.search(text)
  return match.group(0) if match else None
