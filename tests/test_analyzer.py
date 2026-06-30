"""文献分析功能测试（Mock LLM）"""
import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.storage.database import setup_database, get_session
from backend.storage.models import LiteratureRecord, User, WorkspaceRecord


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  setup_database()


@pytest.fixture
def sample_literature():
  user_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  lit_id = str(uuid.uuid4())
  with get_session() as session:
    session.add(User(id=user_id, username=f"testuser_{uuid.uuid4().hex[:8]}", password_hash="hash", created_at=datetime.now()))
    session.add(WorkspaceRecord(
      id=ws_id, name="测试空间", description="", user_id=user_id,
      current_selected_ids_json="[]",
      created_at=datetime.now(), updated_at=datetime.now(),
    ))
    session.add(LiteratureRecord(
      id=lit_id, workspace_id=ws_id, title="Test Paper",
      authors_json='["Alice", "Bob"]', journal="Test Journal", year=2024,
      doi="10.1234/test", abstract="Test abstract",
      pdf_path="", full_text="Introduction\nThis is a test paper about AI.",
      uploaded_at=datetime.now(), status="pending",
    ))
    session.commit()
  return lit_id


@pytest.mark.asyncio
async def test_analyze_single_literature_mock(sample_literature):
  mock_responses = [
    json.dumps({
      "research_background": "背景",
      "research_goal": "目标",
      "methods_summary": "方法",
      "key_findings": ["发现1"],
      "conclusion": "结论",
      "limitations": ["局限1"],
      "contribution_summary": "贡献",
    }),
    json.dumps({"innovations": ["创新"], "novelty_score": 8}),
    json.dumps({"method_tags": ["深度学习"], "domain_tags": ["AI"]}),
    json.dumps({
      "formulas": [{
        "name": "交叉熵损失",
        "latex": "L=-\\sum_i y_i\\log\\hat{y}_i",
        "variables": ["y_i: 真实标签", "\\hat{y}_i: 预测概率"],
        "explanation": "交叉熵损失用于衡量预测分布与真实分布的差异。",
        "context": "用于训练分类模型。",
      }],
    }),
    json.dumps({"citations": [{"zh": "中文引用", "en": "English cite"}]}),
    json.dumps({"relevance_score": 8.5, "recommendation_score": 9.0, "reason": "相关"}),
  ]
  call_count = 0

  async def mock_chat(*args, **kwargs):
    nonlocal call_count
    result = mock_responses[min(call_count, len(mock_responses) - 1)]
    call_count += 1
    return result

  with patch("backend.literature.analyzer.llm_client.chat", new=AsyncMock(side_effect=mock_chat)):
    from backend.literature.analyzer import analyze_single_literature
    result = await analyze_single_literature(sample_literature, user_topic="人工智能")

  assert result["literature_id"] == sample_literature
  assert result["contribution_summary"] == "贡献"
  assert result["relevance_score"] == 8.5
  assert len(result["formulas"]) == 1
  assert result["formulas"][0]["name"] == "交叉熵损失"

  with get_session() as session:
    lit = session.get(LiteratureRecord, sample_literature)
    assert lit.status == "done"
