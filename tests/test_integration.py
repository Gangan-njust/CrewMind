"""文献与开题报告集成测试"""
import uuid
from datetime import datetime

import pytest

from backend.literature.integration import (
  build_literature_review_context,
  build_proposal_context,
  extract_citation_markers,
  generate_reference_list,
  map_literature_to_sections,
)
from backend.storage.database import setup_database, get_session
from backend.storage.models import (
  LiteratureAnalysisRecord,
  LiteratureRecord,
  User,
  WorkspaceRecord,
)


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  setup_database()


@pytest.fixture
def workspace_with_literature():
  user_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  lit_id = str(uuid.uuid4())
  now = datetime.now()
  with get_session() as session:
    session.add(User(id=user_id, username=f"lituser_{uuid.uuid4().hex[:8]}", password_hash="hash", created_at=now))
    session.add(WorkspaceRecord(
      id=ws_id, name="集成测试", description="", user_id=user_id,
      current_selected_ids_json="[]", created_at=now, updated_at=now,
    ))
    session.add(LiteratureRecord(
      id=lit_id, workspace_id=ws_id, title="Deep Learning Survey",
      authors_json='["Smith"]', journal="AI Review", year=2023,
      doi="10.1234/dl", abstract="Survey of deep learning",
      pdf_path="", full_text="", uploaded_at=now, status="done",
    ))
    session.add(LiteratureAnalysisRecord(
      id=str(uuid.uuid4()), literature_id=lit_id,
      tags_json='["深度学习"]',
      contribution_summary="综述了深度学习进展",
      relevance_score=9.0, recommendation_score=9.0,
      key_findings_json='["发现1"]',
      limitations_json='["局限1"]',
      citation_templates_json='[]',
      formulas_json='[]',
      research_background="深度学习背景",
      research_goal="梳理研究现状",
      methods_summary="文献综述方法",
      conclusion="深度学习前景广阔",
      created_at=now, updated_at=now,
    ))
    session.commit()
  return ws_id, [lit_id]


def test_map_literature_to_sections(workspace_with_literature):
  ws_id, lit_ids = workspace_with_literature
  sections = map_literature_to_sections(lit_ids, ws_id)
  assert len(sections["research_background"]) >= 1
  assert sections["research_background"][0]["ref_number"] == 1


def test_build_proposal_context(workspace_with_literature):
  ws_id, lit_ids = workspace_with_literature
  ctx = build_proposal_context(ws_id, lit_ids, "深度学习研究", "library_first")
  assert "优先引用" in ctx
  assert "Deep Learning Survey" in ctx


def test_build_literature_review_context(workspace_with_literature):
  ws_id, lit_ids = workspace_with_literature
  ctx = build_literature_review_context(ws_id, lit_ids, "深度学习研究现状综述", "only_library")
  assert "文献综述" in ctx
  assert "Deep Learning Survey" in ctx
  assert "参考著录" in ctx
  assert "[1]" in ctx
  assert "综述主题" in ctx


def test_generate_reference_list(workspace_with_literature):
  ws_id, lit_ids = workspace_with_literature
  from backend.storage.literature_store import literature_store
  lits = literature_store.get_literatures_by_ids(ws_id, lit_ids)
  report = "本文参考了现有研究 [1] 的成果。"
  refs, suggested = generate_reference_list(report, lits)
  assert "[1]" in refs
  assert "Deep Learning Survey" in refs
  assert suggested == []

  markers = extract_citation_markers("引用 [1] 和 [2] 和 [1]")
  assert markers == [1, 2]
