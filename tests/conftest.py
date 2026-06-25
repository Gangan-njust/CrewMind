"""共享 pytest fixtures"""
from __future__ import annotations

import pytest

from backend.config import settings


@pytest.fixture(autouse=True)
def isolated_uploads_dir(tmp_path, monkeypatch):
  """每个测试使用独立的上传目录，避免污染 data/uploads"""
  uploads = tmp_path / "uploads"
  uploads.mkdir()
  monkeypatch.setattr(settings, "uploads_dir", uploads)
  yield uploads


@pytest.fixture
def sample_pubmed_xml() -> str:
  return """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>98765432</PMID>
      <Article>
        <ArticleTitle>Deep Learning for Medical Diagnosis</ArticleTitle>
        <Abstract>
          <AbstractText>Background: AI methods show promise.</AbstractText>
          <AbstractText>Methods: We trained a CNN model.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Zhang</LastName><ForeName>Wei</ForeName></Author>
          <Author><LastName>Li</LastName><ForeName>Ming</ForeName></Author>
        </AuthorList>
        <Journal><Title>Lancet Digital Health</Title></Journal>
        <ArticleDate><PubDate><Year>2024</Year></PubDate></ArticleDate>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">98765432</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""
