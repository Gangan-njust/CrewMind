"""RAG 文献问答单元测试"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_answer_query_returns_sources():
  mock_hits = [{
    "chunk_id": "chunk-1",
    "literature_id": "lit-1",
    "literature_title": "Test Paper",
    "section_key": "methods",
    "content": "We used deep learning for classification.",
    "excerpt": "We used deep learning for classification.",
    "score": 0.9,
  }]

  with patch("backend.rag.query.settings") as mock_settings:
    mock_settings.rag_enabled = True
    with patch("backend.rag.query.retrieve", return_value=mock_hits):
      with patch("backend.rag.query.llm_client.chat", new=AsyncMock(return_value="该方法采用深度学习。")):
        from backend.rag.query import answer_query
        result = await answer_query(str(uuid.uuid4()), "用了什么方法？")

  assert "answer" in result
  assert result["evidence_count"] == 1
  assert result["sources"][0]["literature_title"] == "Test Paper"
