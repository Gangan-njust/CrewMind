"""文献全文解析测试"""
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from backend.storage.database import get_session, setup_database
from backend.storage.models import LiteratureRecord, User, WorkspaceRecord


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  setup_database()


def test_resolve_prefers_longer_pdf_text():
  from backend.literature.content import resolve_literature_full_text

  lit = LiteratureRecord(
    id=str(uuid.uuid4()),
    workspace_id=str(uuid.uuid4()),
    title="Paper",
    authors_json="[]",
    journal="",
    year=None,
    doi="",
    abstract="",
    pdf_path="/tmp/paper.pdf",
    full_text="short preview",
    uploaded_at=datetime.now(),
    status="pending",
  )
  with patch(
    "backend.literature.content.extract_text_from_pdf",
    return_value=("much longer full text from pdf extraction", ""),
  ):
    text, err = resolve_literature_full_text(lit, persist=False)
  assert text == "much longer full text from pdf extraction"
  assert err == ""


def test_empty_content_error_for_scan_pdf():
  from backend.literature.content import empty_content_error

  lit = LiteratureRecord(
    id=str(uuid.uuid4()),
    workspace_id=str(uuid.uuid4()),
    title="Scan",
    authors_json="[]",
    journal="",
    year=None,
    doi="",
    abstract="",
    pdf_path="/data/scan.pdf",
    full_text="",
    uploaded_at=datetime.now(),
    status="pending",
  )
  msg = empty_content_error(lit)
  assert "扫描版" in msg
