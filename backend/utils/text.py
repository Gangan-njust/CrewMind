"""文本清理工具"""
import re
from typing import Any

_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def sanitize_unicode(text: str | None) -> str:
  """移除非法 UTF-16 surrogate，避免 encode / JSON / 存储失败"""
  if not text:
    return ""
  return _SURROGATE_RE.sub("\ufffd", text)


def sanitize_deep(value: Any) -> Any:
  """递归清理 dict / list / str 中的 surrogate"""
  if isinstance(value, str):
    return sanitize_unicode(value)
  if isinstance(value, dict):
    return {
      sanitize_unicode(k) if isinstance(k, str) else k: sanitize_deep(v)
      for k, v in value.items()
    }
  if isinstance(value, list):
    return [sanitize_deep(item) for item in value]
  if isinstance(value, tuple):
    return tuple(sanitize_deep(item) for item in value)
  return value
