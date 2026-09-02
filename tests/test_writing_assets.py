"""写作图表素材解析单测（免数据库路径）。"""
import base64

import pytest

from backend.writing.assets import resolve_source_bytes
from backend.storage.writing_store import _is_relative_to


def test_upload_kind_decodes_base64():
  raw = b"fake-png-bytes"
  b64 = base64.b64encode(raw).decode("ascii")
  data, filename, caption, meta = resolve_source_bytes(
    "user-1", "upload", {}, data_base64=b64, caption="测试图表"
  )
  assert data == raw
  assert filename.endswith(".png")
  assert caption == "测试图表"
  assert meta == {}


def test_upload_missing_base64_raises():
  with pytest.raises(ValueError):
    resolve_source_bytes("user-1", "upload", {})


def test_unknown_kind_raises():
  with pytest.raises(ValueError):
    resolve_source_bytes("user-1", "weird_kind", {})


def test_caption_brackets_sanitized():
  raw = b"x"
  b64 = base64.b64encode(raw).decode("ascii")
  _, _, caption, _ = resolve_source_bytes(
    "user-1", "upload", {}, data_base64=b64, caption="含]方[括号的图注"
  )
  assert "]" not in caption and "[" not in caption


def test_experiment_metric_unknown_experiment_raises():
  with pytest.raises(ValueError):
    resolve_source_bytes(
      "no-such-user",
      "experiment_metric",
      {"experiment_id": "missing-exp", "metric_name": "accuracy"},
    )


def test_experiment_chart_missing_analysis_raises():
  with pytest.raises(ValueError):
    resolve_source_bytes(
      "no-such-user",
      "experiment_chart",
      {"analysis_id": "missing-analysis", "chart_index": 0},
    )


def test_is_relative_to_helper(tmp_path):
  root = tmp_path
  inside = root / "a" / "b.txt"
  outside = tmp_path / ".." / "outside.txt"
  assert _is_relative_to(inside, root)
  assert not _is_relative_to(outside.resolve(), root)


def test_list_candidates_empty_without_links():
  """无实验/文献关联时，候选聚合为空且不触发数据库访问。"""
  from backend.writing.assets import list_figure_candidates

  project = {"source_workflow_id": None, "workspace_id": None}
  payload = list_figure_candidates(project, "no-such-user")
  assert payload["total"] == 0
  assert payload["experiment_charts"] == []
  assert payload["experiment_metrics"] == []
  assert payload["experiment_attachments"] == []
  assert payload["literature_images"] == []
  assert payload["linked_experiment"] is False
  assert payload["linked_workspace"] is False

