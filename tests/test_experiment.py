"""实验数据管理模块测试"""
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from backend.experiment.analyzer import analyze_dataset, parse_upload
from backend.experiment.comparison import compare_expected_vs_actual
from backend.experiment.integration import extract_expected_metrics


def test_extract_expected_metrics_sample_size():
  text = "本实验计划样本量：30，预期准确率≥95%"
  metrics = extract_expected_metrics(text)
  types = {m["type"] for m in metrics}
  assert "sample_size" in types
  assert "accuracy" in types


def test_extract_expected_metrics_value_with_error():
  text = "温度：25.0 ± 0.5 °C"
  metrics = extract_expected_metrics(text)
  assert any(m.get("type") == "temperature" for m in metrics)


def test_parse_upload_csv():
  with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8") as f:
    f.write("group,value\nA,10\nA,12\nB,15\nB,18\n")
    path = Path(f.name)
  try:
    result = parse_upload(path, "csv")
    assert result["row_count"] == 4
    assert len(result["columns"]) == 2
    assert result["columns"][1]["is_numeric"]
  finally:
    path.unlink()


def test_analyze_dataset_generates_charts_and_stats():
  with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8") as f:
    f.write("group,value\nA,10\nA,12\nA,11\nB,20\nB,22\nB,21\n")
    path = Path(f.name)
  try:
    result = analyze_dataset(path, "csv")
    assert result["summary"]["row_count"] == 6
    assert len(result["charts"]) >= 1
    assert any(s.get("test") == "welch_t_test" for s in result["stats"])
  finally:
    path.unlink()


def test_compare_expected_vs_actual_no_metrics(monkeypatch):
  monkeypatch.setattr(
    "backend.experiment.comparison.experiment_store.get_experiment",
    lambda eid, uid: {
      "id": eid,
      "expected_metrics": [],
      "datasets": [],
    },
  )
  result = compare_expected_vs_actual("exp1", "user1")
  assert result["has_expected"] is False


def test_compare_sample_size(monkeypatch, tmp_path):
  csv_path = tmp_path / "data.csv"
  pd.DataFrame({"value": range(25)}).to_csv(csv_path, index=False)

  class FakeDs:
    id = "ds1"
    file_type = "csv"
    file_path = str(csv_path)

  monkeypatch.setattr(
    "backend.experiment.comparison.experiment_store.get_experiment",
    lambda eid, uid: {
      "id": eid,
      "expected_metrics": [{"type": "sample_size", "label": "样本量", "expected_value": 30}],
      "datasets": [{"id": "ds1", "filename": "data.csv", "file_type": "csv"}],
    },
  )
  monkeypatch.setattr(
    "backend.experiment.comparison.experiment_store.get_dataset_file",
    lambda dsid, uid: (FakeDs(), csv_path),
  )
  result = compare_expected_vs_actual("exp1", "user1")
  assert result["has_expected"] is True
  assert result["comparisons"][0]["actual_value"] == 25
