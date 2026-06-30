"""按用户选择的 Agent 过滤任务流程"""
from dataclasses import replace
from typing import Any

from backend.tasks.definitions import TaskDefinition

REVIEW_AGENT_ID = "review_specialist"


def filter_tasks_by_agents(
  tasks: list[TaskDefinition],
  selected_agents: list[str],
) -> list[TaskDefinition]:
  """保留选中 Agent 对应的任务，并清理无效依赖"""
  if not selected_agents:
    return tasks

  selected = set(selected_agents)
  kept_ids = {t.id for t in tasks if t.agent_id in selected}

  filtered: list[TaskDefinition] = []
  for task in tasks:
    if task.agent_id not in selected:
      continue
    deps = [d for d in task.depends_on if d in kept_ids]
    if deps != task.depends_on:
      filtered.append(replace(task, depends_on=deps))
    else:
      filtered.append(task)

  return filtered


def apply_human_review_policy(
  tasks: list[TaskDefinition],
  selected_agents: list[str],
) -> list[TaskDefinition]:
  """未选终审专家时不暂停；选了终审专家时仅终审任务需要人工审核。"""
  if not selected_agents:
    return tasks

  review_selected = REVIEW_AGENT_ID in selected_agents
  adjusted: list[TaskDefinition] = []
  for task in tasks:
    want_review = review_selected and task.agent_id == REVIEW_AGENT_ID
    if task.requires_human_review != want_review:
      adjusted.append(replace(task, requires_human_review=want_review))
    else:
      adjusted.append(task)
  return adjusted


def serialize_tasks(tasks: list[TaskDefinition]) -> list[dict[str, Any]]:
  return [
    {
      "id": t.id,
      "name": t.name,
      "agent_id": t.agent_id,
      "depends_on": t.depends_on,
      "requires_human_review": t.requires_human_review,
    }
    for t in tasks
  ]
