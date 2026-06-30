"""文本清理工具测试"""
import json

from backend.utils.text import sanitize_deep, sanitize_unicode


def test_sanitize_unicode_removes_lone_surrogate():
  bad = "hello\udc43world"
  cleaned = sanitize_unicode(bad)
  assert "\udc43" not in cleaned
  cleaned.encode("utf-8")


def test_sanitize_deep_nested():
  data = {"text": "a\udc43b", "items": ["x\udc44y"]}
  cleaned = sanitize_deep(data)
  json.dumps(cleaned, ensure_ascii=False).encode("utf-8")
  assert "\udc43" not in cleaned["text"]
