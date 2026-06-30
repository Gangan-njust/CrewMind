"""PDF 解析功能测试"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.literature.parser import extract_full_text, extract_batch, is_pdf_file, clear_text_cache


@pytest.fixture
def sample_pdf(tmp_path):
  path = tmp_path / "test.pdf"
  path.write_bytes(b"%PDF-1.4 fake content")
  return path


def test_is_pdf_file(sample_pdf):
  content = sample_pdf.read_bytes()
  assert is_pdf_file(str(sample_pdf), content) is True
  assert is_pdf_file("test.txt", b"hello") is False


def test_extract_full_text(sample_pdf):
  clear_text_cache()
  mock_page = MagicMock()
  mock_page.extract_text.return_value = "Hello Literature"
  mock_reader = MagicMock()
  mock_reader.pages = [mock_page]

  with patch("backend.literature.parser.PdfReader", return_value=mock_reader):
    text = extract_full_text(sample_pdf, use_cache=False)
  assert "Hello Literature" in text


def test_extract_batch(sample_pdf, tmp_path):
  clear_text_cache()
  other = tmp_path / "missing.pdf"
  mock_page = MagicMock()
  mock_page.extract_text.return_value = "Page text"
  mock_reader = MagicMock()
  mock_reader.pages = [mock_page]

  with patch("backend.literature.parser.PdfReader", return_value=mock_reader):
    results = extract_batch([sample_pdf, other], use_cache=False)
  assert "Page text" in results[str(sample_pdf)]
  assert "[提取失败" in results[str(other)]


def test_text_cache(sample_pdf):
  clear_text_cache()
  mock_page = MagicMock()
  mock_page.extract_text.return_value = "Cached text"
  mock_reader = MagicMock()
  mock_reader.pages = [mock_page]

  with patch("backend.literature.parser.PdfReader", return_value=mock_reader):
    t1 = extract_full_text(sample_pdf, use_cache=True)
    t2 = extract_full_text(sample_pdf, use_cache=True)
  assert t1 == t2 == "Cached text"
