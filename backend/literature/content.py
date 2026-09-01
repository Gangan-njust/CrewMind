"""文献全文解析：统一从 PDF / 数据库获取完整文本"""
from __future__ import annotations

import logging

from backend.literature.parser import extract_full_text, resolve_pdf_path
from backend.storage.database import get_session
from backend.storage.models import LiteratureRecord
from backend.utils.text import sanitize_unicode

logger = logging.getLogger(__name__)

_SCAN_PDF_HINT = "扫描版 PDF 无法提取文字，请上传文字版 PDF 或先做 OCR"


def extract_text_from_pdf(pdf_path: str) -> tuple[str, str]:
  """从 PDF 路径提取全文，返回 (text, error_message)"""
  if not pdf_path:
    return "", ""
  try:
    resolved = resolve_pdf_path(pdf_path)
    if not resolved.exists():
      return "", "PDF 文件不存在"
    text = sanitize_unicode(extract_full_text(resolved, use_cache=True).strip())
    return text, ""
  except RuntimeError as e:
    logger.warning("PDF 文本提取失败: %s — %s", pdf_path, e)
    return "", str(e)
  except Exception as e:
    logger.warning("PDF 文本提取失败: %s — %s", pdf_path, e)
    return "", str(e)


def resolve_literature_full_text(
  lit: LiteratureRecord,
  *,
  persist: bool = False,
) -> tuple[str, str]:
  """返回 (文献可用全文, 提取错误信息)。优先使用 PDF 完整提取结果。"""
  stored = sanitize_unicode((lit.full_text or "").strip())
  pdf_text, pdf_err = extract_text_from_pdf(lit.pdf_path or "")

  if pdf_text and len(pdf_text) >= len(stored):
    content = pdf_text
  else:
    content = stored or pdf_text

  if persist and content and content != stored:
    with get_session() as session:
      row = session.get(LiteratureRecord, lit.id)
      if row:
        row.full_text = content
        session.commit()

  return content, pdf_err


def empty_content_error(lit: LiteratureRecord, *, pdf_err: str = "") -> str:
  """生成用户可读的空内容错误信息"""
  if pdf_err:
    return f"文献内容为空。{pdf_err}"
  if lit.pdf_path:
    return f"文献内容为空。{_SCAN_PDF_HINT}"
  return "文献内容为空，请重新上传 PDF"
