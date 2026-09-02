"""任务过滤与人工审核策略"""
from backend.tasks.definitions import TASK_FLOWS, TaskDefinition
from backend.agents.roles import ScenarioType
from backend.tasks.filtering import (
  REVIEW_AGENT_ID,
  apply_human_review_policy,
  filter_tasks_by_agents,
)


def _literature_tasks() -> list[TaskDefinition]:
  return list(TASK_FLOWS[ScenarioType.LITERATURE_BASED_PROPOSAL])


def _review_tasks() -> list[TaskDefinition]:
  return list(TASK_FLOWS[ScenarioType.LITERATURE_BASED_REVIEW])


def test_filter_removes_unselected_agents():
  tasks = filter_tasks_by_agents(
    _literature_tasks(),
    ["planner", "literature_researcher"],
  )
  agent_ids = {t.agent_id for t in tasks}
  assert agent_ids == {"planner", "literature_researcher"}
  assert all(t.id != "task_review" for t in tasks)


def test_human_review_only_when_review_specialist_selected():
  selected = ["planner", "literature_researcher", "resource_analyst", "review_specialist"]
  tasks = apply_human_review_policy(filter_tasks_by_agents(_literature_tasks(), selected), selected)
  review = next(t for t in tasks if t.agent_id == REVIEW_AGENT_ID)
  budget = next(t for t in tasks if t.id == "task_budget")
  assert review.requires_human_review is True
  assert budget.requires_human_review is False


def test_no_human_review_when_review_specialist_not_selected():
  selected = ["planner", "literature_researcher", "resource_analyst"]
  tasks = apply_human_review_policy(filter_tasks_by_agents(_literature_tasks(), selected), selected)
  assert all(not t.requires_human_review for t in tasks)


def test_literature_review_flow_review_task_requires_human_review():
  review = next(t for t in _review_tasks() if t.id == "task_review")
  assert review.requires_human_review is True
  assert "task_planning" in review.depends_on
  assert "task_literature" in review.depends_on


def test_literature_review_flow_filters_domain_reviewers():
  selected = ["planner", "literature_researcher", "review_specialist"]
  tasks = filter_tasks_by_agents(_review_tasks(), selected)
  agent_ids = {t.agent_id for t in tasks}
  assert agent_ids == set(selected)
  review = next(t for t in tasks if t.id == "task_review")
  assert all(d not in review.depends_on for d in ("task_cs_review", "task_bio_review", "task_material_review"))
