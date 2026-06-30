from backend.writing.outline import _normalize_subsections


def test_normalize_subsections_filters_invalid_levels():
  raw = [
    {"level": 2, "title": "研究背景", "outline_points": ["要点 A"]},
    {"level": 1, "title": "无效"},
    {"level": 5, "title": "无效"},
    {"level": 3, "title": "", "outline_points": []},
    {"level": "4", "title": "细节", "outline_points": "ignored"},
  ]
  result = _normalize_subsections(raw)
  assert result == [
    {"level": 2, "title": "研究背景", "outline_points": ["要点 A"]},
    {"level": 4, "title": "细节", "outline_points": []},
  ]


def test_normalize_subsections_empty_input():
  assert _normalize_subsections(None) == []
  assert _normalize_subsections([]) == []
