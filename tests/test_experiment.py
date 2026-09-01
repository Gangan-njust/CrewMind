"""实验数据管理模块测试"""
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from backend.experiment.analyzer import analyze_dataset, parse_upload
from backend.experiment.comparison import compare_expected_vs_actual
from backend.experiment.integration import extract_expected_metrics
from backend.experiment.metrics import generate_metric_chart, generate_multi_metric_chart
from backend.experiment.reproduce import build_reproduce_manifest
from backend.experiment.compare_multi import compare_experiments


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


def test_generate_metric_chart():
  points = [{"step": 1, "value": 0.9, "unit": "acc"}, {"step": 2, "value": 0.92}, {"step": 3, "value": 0.95}]
  chart = generate_metric_chart("accuracy", points, unit="acc")
  assert chart["type"] == "line"
  assert not chart.get("empty")
  assert chart["image_base64"].startswith("iVBOR")


def test_generate_metric_chart_empty():
  chart = generate_metric_chart("loss", [])
  assert chart["empty"] is True
  assert chart["image_base64"] == ""


def test_generate_multi_metric_chart():
  series = [
    {"label": "A", "points": [{"step": 1, "value": 0.8}, {"step": 2, "value": 0.9}]},
    {"label": "B", "points": [{"step": 1, "value": 0.7}, {"step": 2, "value": 0.85}]},
  ]
  chart = generate_multi_metric_chart("accuracy", series)
  assert chart["type"] == "multi_line"
  assert not chart.get("empty")
  assert chart["image_base64"].startswith("iVBOR")


def test_compare_experiments_multi(monkeypatch):
  def fake_get_experiment(exp_id, uid):
    return {
      "id": exp_id,
      "title": f"实验-{exp_id}",
      "status": "completed",
      "progress": 100,
      "entry_count": 1,
      "dataset_count": 1,
      "metric_count": 2,
      "file_count": 1,
      "config": {"hyperparameters": {"lr": 0.01}, "environment": {"python_version": "3.12"}},
      "metrics": [
        {"metric_name": "accuracy", "step": 1, "value": 0.8, "unit": "%"},
        {"metric_name": "accuracy", "step": 2, "value": 0.9, "unit": "%"},
      ],
    }

  monkeypatch.setattr("backend.experiment.compare_multi.experiment_store.get_experiment", fake_get_experiment)
  result = compare_experiments(["exp1", "exp2"], "user1", metric_names=["accuracy"])
  assert len(result["experiments"]) == 2
  assert result["experiments"][0]["metric_summaries"]["accuracy"]["last"] == 0.9
  assert len(result["charts"]) >= 1
  assert "共对比 2 个实验" in result["summary"]


def test_compare_experiments_multi_requires_ids():
  with pytest.raises(ValueError):
    compare_experiments([], "user1")


def test_build_reproduce_manifest(monkeypatch, tmp_path):
  monkeypatch.setattr(
    "backend.experiment.reproduce._reproduce_dir",
    lambda eid: tmp_path / "reproduce",
  )

  def fake_get_experiment(exp_id, uid):
    return {
      "id": exp_id,
      "title": "催化剂活性测试",
      "status": "completed",
      "progress": 100,
      "config": {
        "hyperparameters": {"temperature": 25, "batch_size": 32},
        "environment": {"python_version": "3.12"},
        "code_version": {"git_commit": "abc123", "repo": "my-lab"},
      },
      "expected_metrics": [{"type": "sample_size", "label": "样本量", "expected_value": 30}],
      "datasets": [{"filename": "data.csv", "file_type": "csv", "row_count": 25}],
      "files": [],
      "metrics": [{"metric_name": "accuracy", "step": 1, "value": 0.9}],
    }

  monkeypatch.setattr("backend.experiment.reproduce.experiment_store.get_experiment", fake_get_experiment)
  result = build_reproduce_manifest("exp1", "user1", entrypoint="python train.py")
  names = {f["filename"] for f in result["files"]}
  assert {"reproduce.json", "config.yaml", "requirements.txt", "reproduce.sh", "README.md"} == names
  assert result["manifest"]["config"]["code_version"]["git_commit"] == "abc123"
  assert (tmp_path / "reproduce" / "reproduce.json").exists()
  assert "python train.py" in (tmp_path / "reproduce" / "reproduce.sh").read_text(encoding="utf-8")
