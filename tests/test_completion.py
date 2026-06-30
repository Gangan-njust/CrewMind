from backend.writing.completion import build_section_items


def test_build_section_items_from_outline_points_when_empty_content():
  section = {"section_type": "intro", "title": ""}
  outline = {
    "section_type": "intro",
    "outline_points": ["研究背景", "研究空白与问题"],
    "writing_hints": "突出创新性",
    "word_target": "800-1200",
  }
  items = build_section_items("", outline, section)
  assert len(items) == 2
  assert items[0]["title"] == "研究背景"
  assert items[0]["word_target"] >= 150


def test_build_section_items_merges_existing_headings_and_outline_subsections():
  content = "## 研究背景\n\n已有段落。\n\n## 方法概述\n\n简述。"
  section = {"section_type": "methods", "title": ""}
  outline = {
    "subsections": [
      {"level": 2, "title": "实验设计", "outline_points": ["对照组设置"]},
    ],
  }
  items = build_section_items(content, outline, section)
  titles = [item["title"] for item in items]
  assert "研究背景" in titles
  assert "方法概述" in titles
  assert "实验设计" in titles
  bg = next(item for item in items if item["title"] == "研究背景")
  assert "已有段落" in bg["existing_content"]
