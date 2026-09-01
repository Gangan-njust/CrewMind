"""训练指标曲线可视化"""
from __future__ import annotations

import base64
import io
from typing import Any

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")


def _setup_chinese_font() -> None:
  for font in ("SimHei", "Microsoft YaHei", "DejaVu Sans"):
    try:
      plt.rcParams["font.sans-serif"] = [font]
      plt.rcParams["axes.unicode_minus"] = False
      break
    except Exception:
      pass


def _fig_to_base64(fig) -> str:
  buf = io.BytesIO()
  fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
  plt.close(fig)
  buf.seek(0)
  return base64.b64encode(buf.read()).decode("ascii")


def _normalize_points(points: list[dict]) -> tuple[list[float], list[float]]:
  """points: [{step, value, ...}] -> (steps, values)"""
  pairs = []
  for p in points:
    step = p.get("step")
    value = p.get("value")
    if step is None or value is None:
      continue
    try:
      pairs.append((float(step), float(value)))
    except (TypeError, ValueError):
      continue
  pairs.sort(key=lambda x: x[0])
  if not pairs:
    return [], []
  return [s for s, _ in pairs], [v for _, v in pairs]


def generate_metric_chart(metric_name: str, points: list[dict], unit: str = "") -> dict[str, Any]:
  """生成单个指标的学习曲线图（base64 PNG）"""
  steps, values = _normalize_points(points)
  if not values:
    return {"type": "line", "title": f"{metric_name} 曲线", "image_base64": "", "empty": True}

  _setup_chinese_font()
  fig, ax = plt.subplots(figsize=(8, 4.5))
  ax.plot(steps, values, marker="o", markersize=3, linewidth=1.6, color="#6c5ce7")
  ax.set_title(f"{metric_name} 曲线")
  ax.set_xlabel("step")
  ylabel = metric_name if not unit else f"{metric_name} ({unit})"
  ax.set_ylabel(ylabel)
  ax.grid(True, alpha=0.3)
  fig.tight_layout()
  return {"type": "line", "title": f"{metric_name} 曲线", "image_base64": _fig_to_base64(fig)}


def generate_multi_metric_chart(
  metric_name: str,
  series: list[dict[str, Any]],
  unit: str = "",
) -> dict[str, Any]:
  """多实验同一指标曲线对比。

  series: [{label, points: [{step, value}]}]
  """
  _setup_chinese_font()
  colors = ["#6c5ce7", "#00b894", "#e17055", "#0984e3", "#e84393", "#fdcb6e", "#00cec9", "#636e72"]
  fig, ax = plt.subplots(figsize=(8, 4.5))
  plotted = False
  for idx, item in enumerate(series):
    steps, values = _normalize_points(item.get("points") or [])
    if not values:
      continue
    plotted = True
    ax.plot(
      steps, values, marker="o", markersize=3, linewidth=1.6,
      color=colors[idx % len(colors)], label=str(item.get("label") or f"实验{idx + 1}"),
    )
  if not plotted:
    plt.close(fig)
    return {"type": "multi_line", "title": f"{metric_name} 多实验对比", "image_base64": "", "empty": True}

  ax.set_title(f"{metric_name} 多实验对比")
  ax.set_xlabel("step")
  ylabel = metric_name if not unit else f"{metric_name} ({unit})"
  ax.set_ylabel(ylabel)
  ax.grid(True, alpha=0.3)
  ax.legend(loc="best", fontsize=8)
  fig.tight_layout()
  return {"type": "multi_line", "title": f"{metric_name} 多实验对比", "image_base64": _fig_to_base64(fig)}
