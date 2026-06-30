from backend.writing.assistant import _format_structured_items


def test_format_structured_items_includes_word_target_and_requirements():
  spec = _format_structured_items([
    {
      "title": "研究背景",
      "level": 2,
      "word_target": 500,
      "requirements": "引用近五年文献",
      "outline_points": ["领域现状", "研究空白"],
      "existing_content": "已有草稿内容",
      "enabled": True,
    },
  ])
  assert "研究背景" in spec
  assert "约 500 字" in spec
  assert "引用近五年文献" in spec
  assert "领域现状" in spec
  assert "已有草稿内容" in spec
