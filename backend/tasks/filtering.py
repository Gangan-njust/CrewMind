"""按用户选择的 Agent 过滤任务流程"""
from dataclasses import replace

from backend.tasks.definitions import TaskDefinition


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
