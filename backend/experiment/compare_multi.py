"""多实验对比分析"""
from __future__ import annotations

from typing import Any

from backend.experiment.metrics import generate_multi_metric_chart
from backend.storage.experiment_store import experiment_store

STATUS_LABELS = {
  "active": "进行中",
  "planned": "已计划",
  "paused": "已暂停",
  "completed": "已完成",
  "archived": "已归档",
  "failed": "失败",
}


def _metric_summary(points: list[dict]) -> dict[str, Any]:
  """对单实验某指标序列做摘要统计"""
  values = []
  for p in points:
    v = p.get("value")
    if v is None:
      continue
    try:
      values.append(float(v))
    except (TypeError, ValueError):
      continue
  if not values:
    return {"count": 0}
  return {
    "count": len(values),
    "first": values[0],
    "last": values[-1],
    "min": min(values),
    "max": max(values),
    "mean": round(sum(values) / len(values), 4),
  }


def compare_experiments(
  experiment_ids: list[str],
  user_id: str,
  metric_names: list[str] | None = None,
) -> dict[str, Any]:
  """横向对比多个实验：配置、状态、进度与指标摘要，并生成对比曲线。"""
  if not experiment_ids:
    raise ValueError("请至少选择一个实验进行对比")

  rows = []
  metric_series: dict[str, list[dict]] = {}

  for exp_id in experiment_ids:
    exp = experiment_store.get_experiment(exp_id, user_id)
    metrics = exp.get("metrics", [])
    config = exp.get("config", {}) or {}

    # 按指标名分组
    by_name: dict[str, list[dict]] = {}
    for m in metrics:
      by_name.setdefault(m["metric_name"], []).append(m)
    summaries = {name: _metric_summary(points) for name, points in by_name.items()}

    row: dict[str, Any] = {
      "experiment_id": exp["id"],
      "title": exp["title"],
      "status": exp.get("status", ""),
      "status_label": STATUS_LABELS.get(exp.get("status", ""), exp.get("status", "")),
      "progress": exp.get("progress", 0),
      "entry_count": exp.get("entry_count", 0),
      "dataset_count": exp.get("dataset_count", 0),
      "metric_count": exp.get("metric_count", 0),
      "file_count": exp.get("file_count", 0),
      "config": config,
      "metric_summaries": summaries,
    }
    rows.append(row)

    # 收集对比曲线数据
    for name, points in by_name.items():
      if metric_names and name not in metric_names:
        continue
      metric_series.setdefault(name, []).append(
        {"label": exp["title"], "points": points}
      )

  if metric_names:
    names = metric_names
  else:
    # 取出现次数最多的指标名，最多 4 个
    name_counts: dict[str, int] = {}
    for name, series in metric_series.items():
      name_counts[name] = len(series)
    names = [n for n, _ in sorted(name_counts.items(), key=lambda kv: kv[1], reverse=True)][:4]

  charts = []
  for name in names:
    series = metric_series.get(name, [])
    if not series:
      continue
    unit = ""
    for s in series:
      for p in s.get("points", []):
        if p.get("unit"):
          unit = p["unit"]
          break
      if unit:
        break
    chart = generate_multi_metric_chart(name, series, unit=unit)
    if not chart.get("empty"):
      charts.append(chart)

  return {
    "experiments": rows,
    "metric_names": names,
    "charts": charts,
    "summary": f"共对比 {len(rows)} 个实验",
  }
