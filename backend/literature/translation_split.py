"""原文切分：按段落（超长段落退化到句子）切分为可翻译片段

独立成模块，供版式布局（translation_layout）与翻译主流程（translator）共用。
"""
from __future__ import annotations

import re

from backend.utils.text import sanitize_unicode

DEFAULT_SEGMENT_CHARS = 4000


def split_for_translation(text: str, max_chars: int = DEFAULT_SEGMENT_CHARS) -> list[str]:
  """按段落边界切分原文，超长段落退化到句子边界，尽量不切断句子"""
  normalized = sanitize_unicode(text or "").replace("\r\n", "\n").strip()
  if not normalized:
    return []

  paragraphs = [p.strip() for p in re.split(r"\n\s*\n", normalized) if p.strip()]
  segments: list[str] = []
  buffer = ""
  for paragraph in paragraphs:
    if len(paragraph) > max_chars:
      if buffer:
        segments.append(buffer)
        buffer = ""
      segments.extend(_split_long_paragraph(paragraph, max_chars))
      continue
    if not buffer:
      buffer = paragraph
    elif len(buffer) + len(paragraph) + 2 <= max_chars:
      buffer = f"{buffer}\n\n{paragraph}"
    else:
      segments.append(buffer)
      buffer = paragraph
  if buffer:
    segments.append(buffer)
  return segments


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
  """超长段落按句末标点切分，仍超限时硬切"""
  sentences = re.split(r"(?<=[.!?。！？])\s+", paragraph)
  chunks: list[str] = []
  buffer = ""
  for sentence in sentences:
    if len(sentence) > max_chars:
      if buffer:
        chunks.append(buffer)
        buffer = ""
      chunks.extend(
        sentence[i:i + max_chars] for i in range(0, len(sentence), max_chars)
      )
      continue
    if not buffer:
      buffer = sentence
    elif len(buffer) + len(sentence) + 1 <= max_chars:
      buffer = f"{buffer} {sentence}"
    else:
      chunks.append(buffer)
      buffer = sentence
  if buffer:
    chunks.append(buffer)
  return chunks
