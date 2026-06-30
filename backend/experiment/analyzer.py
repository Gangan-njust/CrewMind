"""实验数据自动分析：统计图表与显著性检验"""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

matplotlib.use("Agg")
logger = logging.getLogger(__name__)

PREVIEW_ROWS = 10
MAX_ROWS = 50000


def _fig_to_base64(fig) -> str:
  buf = io.BytesIO()
  fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
  plt.close(fig)
  buf.seek(0)
  return base64.b64encode(buf.read()).decode("ascii")


def _setup_chinese_font():
  for font in ("SimHei", "Microsoft YaHei", "DejaVu Sans"):
    try:
      plt.rcParams["font.sans-serif"] = [font]
      plt.rcParams["axes.unicode_minus"] = False
      break
    except Exception:
      pass


def load_dataframe(file_path: Path, file_type: str) -> pd.DataFrame:
  if file_type == "csv":
    for enc in ("utf-8", "gbk", "latin-1"):
      try:
        return pd.read_csv(file_path, encoding=enc)
      except UnicodeDecodeError:
        continue
    return pd.read_csv(file_path)
  if file_type in ("xlsx", "xls"):
    return pd.read_excel(file_path)
  raise ValueError(f"不支持的文件类型: {file_type}")


def parse_upload(file_path: Path, file_type: str) -> dict[str, Any]:
  df = load_dataframe(file_path, file_type)
  if len(df) > MAX_ROWS:
    raise ValueError(f"数据行数超过上限 {MAX_ROWS}")
  df = df.dropna(how="all")
  columns = []
  for col in df.columns:
    dtype = str(df[col].dtype)
    is_numeric = pd.api.types.is_numeric_dtype(df[col])
    columns.append({
      "name": str(col),
      "dtype": dtype,
      "is_numeric": bool(is_numeric),
      "unique_count": int(df[col].nunique(dropna=True)),
    })
  preview = df.head(PREVIEW_ROWS).replace({np.nan: None}).to_dict(orient="records")
  return {
    "columns": columns,
    "row_count": len(df),
    "preview": preview,
  }


def _detect_group_column(df: pd.DataFrame, numeric_cols: list[str]) -> str | None:
  for col in df.columns:
    if col in numeric_cols:
      continue
    nunique = df[col].nunique(dropna=True)
    if 2 <= nunique <= 10:
      return str(col)
  return None


def _run_significance_tests(df: pd.DataFrame, value_col: str, group_col: str | None) -> list[dict]:
  results: list[dict] = []
  series = pd.to_numeric(df[value_col], errors="coerce").dropna()
  if series.empty:
    return results

  results.append({
    "test": "descriptive",
    "variable": value_col,
    "n": int(series.count()),
    "mean": round(float(series.mean()), 4),
    "std": round(float(series.std(ddof=1)), 4) if len(series) > 1 else 0.0,
    "median": round(float(series.median()), 4),
    "min": round(float(series.min()), 4),
    "max": round(float(series.max()), 4),
  })

  if not group_col or group_col not in df.columns:
    return results

  groups = []
  group_names = []
  for name, grp in df.groupby(group_col, dropna=True):
    vals = pd.to_numeric(grp[value_col], errors="coerce").dropna()
    if len(vals) >= 2:
      groups.append(vals.values)
      group_names.append(str(name))

  if len(groups) == 2:
    t_stat, p_val = stats.ttest_ind(groups[0], groups[1], equal_var=False)
    results.append({
      "test": "welch_t_test",
      "variable": value_col,
      "group_column": group_col,
      "groups": group_names,
      "statistic": round(float(t_stat), 4),
      "p_value": round(float(p_val), 6),
      "significant_005": bool(p_val < 0.05),
      "interpretation": (
        f"组间差异{'显著' if p_val < 0.05 else '不显著'} (p={p_val:.4f})"
      ),
    })
  elif len(groups) >= 3:
    f_stat, p_val = stats.f_oneway(*groups)
    results.append({
      "test": "one_way_anova",
      "variable": value_col,
      "group_column": group_col,
      "groups": group_names,
      "statistic": round(float(f_stat), 4),
      "p_value": round(float(p_val), 6),
      "significant_005": bool(p_val < 0.05),
      "interpretation": (
        f"多组间差异{'显著' if p_val < 0.05 else '不显著'} (p={p_val:.4f})"
      ),
    })

  return results


def _chart_histogram(df: pd.DataFrame, col: str) -> dict | None:
  series = pd.to_numeric(df[col], errors="coerce").dropna()
  if series.empty:
    return None
  _setup_chinese_font()
  fig, ax = plt.subplots(figsize=(6, 4))
  ax.hist(series, bins=min(20, max(5, len(series) // 5)), color="#6c5ce7", edgecolor="white")
  ax.set_title(f"{col} 分布")
  ax.set_xlabel(col)
  ax.set_ylabel("频数")
  return {"type": "histogram", "title": f"{col} 分布直方图", "image_base64": _fig_to_base64(fig)}


def _chart_boxplot(df: pd.DataFrame, value_col: str, group_col: str | None) -> dict | None:
  _setup_chinese_font()
  fig, ax = plt.subplots(figsize=(6, 4))
  if group_col and group_col in df.columns:
    data = []
    labels = []
    for name, grp in df.groupby(group_col, dropna=True):
      vals = pd.to_numeric(grp[value_col], errors="coerce").dropna()
      if len(vals):
        data.append(vals.values)
        labels.append(str(name))
    if not data:
      plt.close(fig)
      return None
    ax.boxplot(data, tick_labels=labels)
    ax.set_title(f"{value_col} 按 {group_col} 分组箱线图")
  else:
    vals = pd.to_numeric(df[value_col], errors="coerce").dropna()
    if vals.empty:
      plt.close(fig)
      return None
    ax.boxplot(vals.values)
    ax.set_title(f"{value_col} 箱线图")
  ax.set_ylabel(value_col)
  return {"type": "boxplot", "title": f"{value_col} 箱线图", "image_base64": _fig_to_base64(fig)}


def _chart_bar_means(df: pd.DataFrame, value_col: str, group_col: str) -> dict | None:
  if group_col not in df.columns:
    return None
  grouped = df.groupby(group_col)[value_col]
  means = grouped.mean()
  stds = grouped.std(ddof=1).reindex(means.index).fillna(0)
  means = pd.to_numeric(means, errors="coerce").dropna()
  if means.empty:
    return None
  _setup_chinese_font()
  fig, ax = plt.subplots(figsize=(6, 4))
  x = range(len(means))
  ax.bar(x, means.values, yerr=stds.values, capsize=4, color="#00b894", edgecolor="white")
  ax.set_xticks(list(x))
  ax.set_xticklabels([str(i) for i in means.index], rotation=15, ha="right")
  ax.set_title(f"{value_col} 各组均值 ± SD")
  ax.set_ylabel(value_col)
  return {"type": "bar", "title": f"{value_col} 组间均值对比", "image_base64": _fig_to_base64(fig)}


def analyze_dataset(
  file_path: Path,
  file_type: str,
  *,
  value_column: str | None = None,
  group_column: str | None = None,
) -> dict[str, Any]:
  df = load_dataframe(file_path, file_type)
  numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
  if not numeric_cols:
    numeric_cols = [
      str(c) for c in df.columns
      if pd.to_numeric(df[c], errors="coerce").notna().sum() > len(df) * 0.5
    ]

  if not numeric_cols:
    raise ValueError("未检测到可分析的数值列")

  value_col = value_column or numeric_cols[0]
  if value_col not in df.columns:
    raise ValueError(f"列不存在: {value_col}")

  group_col = group_column or _detect_group_column(df, numeric_cols)

  stats_results: list[dict] = []
  for col in numeric_cols[:5]:
    stats_results.extend(_run_significance_tests(df, col, group_col if col == value_col else None))

  charts: list[dict] = []
  hist = _chart_histogram(df, value_col)
  if hist:
    charts.append(hist)
  box = _chart_boxplot(df, value_col, group_col)
  if box:
    charts.append(box)
  if group_col:
    bar = _chart_bar_means(df, value_col, group_col)
    if bar:
      charts.append(bar)

  summary = {
    "row_count": len(df),
    "numeric_columns": numeric_cols,
    "value_column": value_col,
    "group_column": group_col,
    "column_count": len(df.columns),
  }

  return {
    "config": {"value_column": value_col, "group_column": group_col},
    "summary": summary,
    "charts": charts,
    "stats": stats_results,
  }
