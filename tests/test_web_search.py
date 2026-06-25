"""web_search 解析与 PubMed 回退"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.web_search import WebSearchTool


class TestParsePubmedXml:
  def test_extracts_title_authors_abstract_year_url(self, sample_pubmed_xml):
    articles = WebSearchTool()._parse_pubmed_xml(sample_pubmed_xml)

    assert len(articles) == 1
    paper = articles[0]
    assert paper["title"] == "Deep Learning for Medical Diagnosis"
    assert "Zhang Wei" in paper["authors"]
    assert "Li Ming" in paper["authors"]
    assert paper["year"] == 2024
    assert "Background: AI methods" in paper["abstract"]
    assert "Methods: We trained" in paper["abstract"]
    assert paper["url"] == "https://pubmed.ncbi.nlm.nih.gov/98765432/"
    assert paper["pmid"] == "98765432"
    assert paper["source"] == "PubMed"

  def test_skips_articles_without_title(self):
    xml = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <ArticleTitle></ArticleTitle>
    <PMID>111</PMID>
  </PubmedArticle>
</PubmedArticleSet>"""
    assert WebSearchTool()._parse_pubmed_xml(xml) == []


class TestSemanticScholarParsing:
  @pytest.mark.asyncio
  async def test_maps_api_response_fields(self):
    tool = WebSearchTool()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "data": [{
        "title": "Transformer Models in Radiology",
        "authors": [{"name": "Alice A"}, {"name": "Bob B"}],
        "year": 2023,
        "abstract": "A" * 700,
        "url": "https://semanticscholar.org/paper/abc",
        "externalIds": {"DOI": "10.1000/test"},
        "citationCount": 15,
        "journal": {"name": "Radiology AI"},
      }],
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("backend.tools.web_search.httpx.AsyncClient") as mock_cls:
      mock_cls.return_value.__aenter__.return_value = mock_client
      results = await tool._search_semantic_scholar("radiology AI", 5)

    assert len(results) == 1
    paper = results[0]
    assert paper["title"] == "Transformer Models in Radiology"
    assert paper["authors"] == "Alice A, Bob B"
    assert paper["year"] == 2023
    assert len(paper["abstract"]) == 600
    assert paper["doi"] == "10.1000/test"
    assert paper["journal"] == "Radiology AI"
    assert paper["source"] == "Semantic Scholar"

  @pytest.mark.asyncio
  async def test_rate_limit_returns_empty_for_fallback(self):
    tool = WebSearchTool()
    mock_response = MagicMock()
    mock_response.status_code = 429

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("backend.tools.web_search.httpx.AsyncClient") as mock_cls:
      mock_cls.return_value.__aenter__.return_value = mock_client
      results = await tool._search_semantic_scholar("query", 3)

    assert results == []


class TestPubMedFallback:
  @pytest.mark.asyncio
  async def test_falls_back_when_semantic_scholar_empty(self, sample_pubmed_xml):
    tool = WebSearchTool()

    esearch_resp = MagicMock()
    esearch_resp.status_code = 200
    esearch_resp.raise_for_status = MagicMock()
    esearch_resp.json.return_value = {"esearchresult": {"idlist": ["98765432"]}}

    efetch_resp = MagicMock()
    efetch_resp.status_code = 200
    efetch_resp.raise_for_status = MagicMock()
    efetch_resp.text = sample_pubmed_xml

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[esearch_resp, efetch_resp])

    with patch.object(tool, "_search_semantic_scholar", AsyncMock(return_value=[])):
      with patch("backend.tools.web_search.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await tool.run(query="medical diagnosis deep learning")

    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert parsed[0]["source"] == "PubMed"
    assert parsed[0]["title"] == "Deep Learning for Medical Diagnosis"

  @pytest.mark.asyncio
  async def test_falls_back_on_semantic_scholar_failure(self, sample_pubmed_xml):
    tool = WebSearchTool()

    esearch_resp = MagicMock()
    esearch_resp.status_code = 200
    esearch_resp.raise_for_status = MagicMock()
    esearch_resp.json.return_value = {"esearchresult": {"idlist": ["98765432"]}}

    efetch_resp = MagicMock()
    efetch_resp.status_code = 200
    efetch_resp.raise_for_status = MagicMock()
    efetch_resp.text = sample_pubmed_xml

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[esearch_resp, efetch_resp])

    with patch.object(
      tool, "_search_semantic_scholar", AsyncMock(side_effect=RuntimeError("network error"))
    ):
      with patch("backend.tools.web_search.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await tool.run(query="medical AI")

    assert "PubMed" in result
    assert "Deep Learning for Medical Diagnosis" in result

  @pytest.mark.asyncio
  async def test_empty_query_returns_error(self):
    result = await WebSearchTool().run(query="")
    assert "错误" in result

  @pytest.mark.asyncio
  async def test_no_results_returns_guidance_message(self):
    tool = WebSearchTool()
    with patch.object(tool, "_search_semantic_scholar", AsyncMock(return_value=[])):
      with patch.object(tool, "_search_pubmed", AsyncMock(return_value=[])):
        result = await tool.run(query="obscure topic xyz")

    assert "未找到" in result
    assert "人工补充引用" in result
