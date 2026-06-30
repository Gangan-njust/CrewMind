"""预期数据 vs 实际数据对比"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backend.experiment.analyzer import load_dataframe
from backend.storage.experiment_store import experiment_store


def _match_column(columns: list[str], metric: dict) -> str | None:
  name = metric.get("name") or metric.get("label") or ""
  for col in columns:
    if name and name.lower() in str(col).lower():
      return str(col)
  label = metric.get("label", "")
  for col in columns:
    if label and label in str(col):
      return str(col)
  return None


def compare_expected_vs_actual(
  experiment_id: str,
  user_id: str,
  *,
  dataset_id: str | None = None,
  value_column: str | None = None,
) -> dict[str, Any]:
  exp = experiment_store.get_experiment(experiment_id, user_id)
  expected = exp.get("expected_metrics", [])
  datasets = exp.get("datasets", [])

  if not expected:
    return {
      "experiment_id": experiment_id,
      "has_expected": False,
      "has_actual": bool(datasets),
      "comparisons": [],
      "summary": "未关联方案预期指标，请从历史方案创建实验或手动添加预期值",
    }

  if not datasets:
    return {
      "experiment_id": experiment_id,
      "has_expected": True,
      "has_actual": False,
      "expected_metrics": expected,
      "comparisons": [],
      "summary": "尚无实验数据，请上传 CSV/Excel 数据集",
    }

  ds = None
  if dataset_id:
    ds = next((d for d in datasets if d["id"] == dataset_id), None)
    if not ds:
      raise ValueError("数据集不存在")
  else:
    ds = datasets[0]

  _, file_path = experiment_store.get_dataset_file(ds["id"], user_id)
  df = load_dataframe(file_path, ds["file_type"])
  columns = [str(c) for c in df.columns]

  comparisons: list[dict] = []

  for metric in expected:
    mtype = metric.get("type", "")
    expected_val = metric.get("expected_value")
    if expected_val is None:
      continue

    item: dict = {
      "metric": metric,
      "status": "unknown",
    }

    if mtype == "sample_size":
      actual_n = len(df)
      item["actual_value"] = actual_n
      item["expected_value"] = expected_val
      item["deviation"] = actual_n - expected_val
      item["deviation_percent"] = round((actual_n - expected_val) / expected_val * 100, 2) if expected_val else None
      item["status"] = "match" if actual_n >= expected_val * 0.9 else "below"
      item["interpretation"] = (
        f"实际样本量 {actual_n}，方案预期 {int(expected_val)}，"
        f"{'达标' if item['status'] == 'match' else '不足'}"
      )
      comparisons.append(item)
      continue

    col = value_column or _match_column(columns, metric)
    if not col:
      numeric_cols = [c for c in columns if pd.to_numeric(df[c], errors="coerce").notna().any()]
      col = numeric_cols[0] if numeric_cols else None

    if not col:
      item["status"] = "no_data"
      item["interpretation"] = "无法匹配数据列"
      comparisons.append(item)
      continue

    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if series.empty:
      item["status"] = "no_data"
      comparisons.append(item)
      continue

    actual_mean = float(series.mean())
    tolerance = metric.get("tolerance")
    item["actual_value"] = round(actual_mean, 4)
    item["expected_value"] = expected_val
    item["column"] = col
    item["n"] = int(series.count())

    if tolerance is not None:
      low, high = expected_val - tolerance, expected_val + tolerance
      in_range = low <= actual_mean <= high
      item["expected_range"] = [low, high]
      item["status"] = "match" if in_range else "mismatch"
      item["interpretation"] = (
        f"{col} 实测均值 {actual_mean:.4f}，预期 {expected_val}±{tolerance}，"
        f"{'在预期范围内' if in_range else '超出预期范围'}"
      )
    elif mtype in ("expected_percent", "target_percent", "accuracy", "recovery_rate"):
      item["deviation"] = round(actual_mean - expected_val, 4)
      item["status"] = "match" if abs(actual_mean - expected_val) <= max(5, expected_val * 0.1) else "mismatch"
      item["interpretation"] = (
        f"{col} 实测 {actual_mean:.2f}%，预期 {expected_val}%，偏差 {item['deviation']:+.2f}%"
      )
    else:
      rel = abs(actual_mean - expected_val) / expected_val if expected_val else 0
      item["deviation_percent"] = round(rel * 100, 2)
      item["status"] = "match" if rel <= 0.15 else "mismatch"
      item["interpretation"] = (
        f"{col} 实测 {actual_mean:.4f}，预期 {expected_val}，"
        f"相对偏差 {item['deviation_percent']:.1f}%"
      )

    comparisons.append(item)

  matched = sum(1 for c in comparisons if c.get("status") == "match")
  total = len(comparisons)
  return {
    "experiment_id": experiment_id,
    "dataset_id": ds["id"],
    "has_expected": True,
    "has_actual": True,
    "expected_metrics": expected,
    "comparisons": comparisons,
    "summary": f"共 {total} 项对比，{matched} 项达标，{total - matched} 项需关注",
  }
