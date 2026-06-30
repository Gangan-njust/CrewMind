"""实验方案与数据联动：从工作方案提取预期指标"""
from __future__ import annotations

import re

from backend.storage.experiment_store import experiment_store
from backend.storage.results import result_store

_METRIC_PATTERNS = [
  (r"样本量[：:\s]*(\d+)", "sample_size", "样本量"),
  (r"样本数[：:\s]*(\d+)", "sample_size", "样本数"),
  (r"n\s*[=＝]\s*(\d+)", "sample_size", "样本量"),
  (r"预期[：:\s]*([\d.]+)\s*%", "expected_percent", "预期百分比"),
  (r"目标[：:\s]*([\d.]+)\s*%", "target_percent", "目标百分比"),
  (r"准确率[：:\s]*(?:≥|>=|>)?\s*([\d.]+)\s*%", "accuracy", "准确率"),
  (r"回收率[：:\s]*(?:≥|>=|>)?\s*([\d.]+)\s*%", "recovery_rate", "回收率"),
  (r"检出限[：:\s]*([\d.]+)\s*([a-zA-Zμ%/]+)?", "detection_limit", "检出限"),
  (r"温度[：:\s]*([\d.]+)\s*(?:±|\+/-)?\s*[\d.]*\s*°?C", "temperature", "温度"),
  (r"浓度[：:\s]*([\d.]+)\s*([a-zA-Zμ%/]+)?", "concentration", "浓度"),
  (r"(\w+)[：:\s]*([\d.]+)\s*±\s*([\d.]+)", "value_with_error", "测量值±误差"),
]


def extract_expected_metrics(experiment_text: str) -> list[dict]:
  """从实验方案文本中规则提取预期指标"""
  if not experiment_text:
    return []

  metrics: list[dict] = []
  seen: set[str] = set()

  for pattern, metric_type, label in _METRIC_PATTERNS:
    for match in re.finditer(pattern, experiment_text, re.IGNORECASE):
      key = f"{metric_type}:{match.group(0)}"
      if key in seen:
        continue
      seen.add(key)
      entry: dict = {
        "type": metric_type,
        "label": label,
        "source_text": match.group(0).strip(),
      }
      groups = match.groups()
      if metric_type == "value_with_error":
        entry["name"] = groups[0]
        entry["expected_value"] = float(groups[1])
        entry["tolerance"] = float(groups[2])
      elif metric_type in ("detection_limit", "concentration") and len(groups) >= 2 and groups[1]:
        entry["expected_value"] = float(groups[0])
        entry["unit"] = groups[1]
      else:
        entry["expected_value"] = float(groups[0])
      metrics.append(entry)

  return metrics[:30]


def get_workflow_experiment_output(workflow_record_id: str, user_id: str) -> dict:
  record = result_store.get(workflow_record_id, user_id)
  if not record:
    raise ValueError("工作方案不存在或无权访问")
  tasks = record.get("tasks", {})
  experiment_output = tasks.get("task_experiment", {}).get("output", "")
  planning_output = tasks.get("task_planning", {}).get("output", "")
  combined = f"{planning_output}\n\n{experiment_output}"
  metrics = extract_expected_metrics(combined)
  return {
    "workflow_id": workflow_record_id,
    "workflow_title": record.get("title", ""),
    "scenario": record.get("scenario", ""),
    "experiment_output": experiment_output,
    "expected_metrics": metrics,
  }


def create_from_workflow(
  user_id: str,
  workflow_record_id: str,
  *,
  title: str = "",
  description: str = "",
) -> dict:
  info = get_workflow_experiment_output(workflow_record_id, user_id)
  exp_title = title or f"实验：{info['workflow_title']}" or "未命名实验"
  return experiment_store.create_experiment(
    user_id,
    title=exp_title,
    description=description or info.get("experiment_output", "")[:500],
    source_workflow_id=workflow_record_id,
    expected_metrics=info["expected_metrics"],
  )
