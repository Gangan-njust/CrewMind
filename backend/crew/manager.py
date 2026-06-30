"""工作流管理器：管理 Crew 实例的生命周期"""
import logging
from typing import Any

from backend.agents.registry import get_agent_registry, list_agents
from backend.utils.text import sanitize_unicode
from backend.agents.roles import ScenarioType, SCENARIO_LABELS, SCENARIO_AGENTS
from backend.crew.engine import Crew
from backend.storage.results import result_store
from backend.storage.uploads import upload_store
from backend.tasks.definitions import TASK_FLOWS
from backend.tasks.filtering import apply_human_review_policy, filter_tasks_by_agents

logger = logging.getLogger(__name__)


class WorkflowManager:
  """全局工作流管理器"""

  def __init__(self):
    self._active_crews: dict[str, Crew] = {}
    self._event_subscribers: dict[str, list] = {}

  def get_scenarios(self, user_id: str) -> list[dict]:
    registry = get_agent_registry(user_id)
    return [
      {
        "id": s.value,
        "label": SCENARIO_LABELS[s],
        "agents": [
          {
            "id": aid,
            "name": registry[aid].name,
            "title": registry[aid].title,
            "category": registry[aid].category,
          }
          for aid in SCENARIO_AGENTS[s]
          if aid in registry
        ],
        "tasks": [
          {
            "id": t.id,
            "name": t.name,
            "agent_id": t.agent_id,
            "depends_on": t.depends_on,
            "requires_human_review": t.requires_human_review,
          }
          for t in TASK_FLOWS[s]
        ],
      }
      for s in ScenarioType
    ]

  def get_agents(self, user_id: str) -> list[dict]:
    return list_agents(user_id)

  async def start_workflow(
    self,
    scenario: str,
    user_input: str,
    user_id: str,
    reference_file_ids: list[str] | None = None,
    selected_agents: list[str] | None = None,
    topic_id: str | None = None,
    collaboration_mode: str = "sequential",
    event_callback=None,
  ) -> Crew:
    from backend.crew.collaboration import (
      CollaborationMode,
      get_debate_tasks,
      get_voting_tasks,
    )

    scenario_type = ScenarioType(scenario)
    mode = CollaborationMode(collaboration_mode)

    if mode == CollaborationMode.DEBATE:
      tasks = get_debate_tasks()
    elif mode == CollaborationMode.VOTING:
      tasks = get_voting_tasks()
    else:
      tasks = list(TASK_FLOWS[scenario_type])
      if selected_agents:
        unknown = [aid for aid in selected_agents if aid not in get_agent_registry(user_id)]
        if unknown:
          raise ValueError(f"未知 Agent 角色: {', '.join(unknown)}")
        tasks = filter_tasks_by_agents(tasks, selected_agents)
        tasks = apply_human_review_policy(tasks, selected_agents)
        if not tasks:
          raise ValueError("所选 Agent 角色无法组成有效任务流程，请至少保留一个相关角色")

    registry = get_agent_registry(user_id)
    reference_files = upload_store.resolve_paths(reference_file_ids or [])

    crew = Crew(
      scenario=scenario,
      user_input=sanitize_unicode(user_input),
      user_id=user_id,
      topic_id=topic_id,
      reference_files=reference_files,
      tasks=tasks,
      agent_registry=registry,
      collaboration_mode=mode.value,
      _event_callback=event_callback,
    )
    self._active_crews[crew.id] = crew
    return crew

  def get_crew(self, crew_id: str, user_id: str | None = None) -> Crew | None:
    crew = self._active_crews.get(crew_id)
    if not crew:
      return None
    if user_id is not None and crew.user_id != user_id:
      return None
    return crew

  async def suspend_workflow(self, crew_id: str, user_id: str) -> dict[str, Any]:
    crew = self.get_crew(crew_id, user_id)
    if not crew:
      raise ValueError(f"工作流不存在: {crew_id}")
    await crew.request_suspend()
    return {"status": crew.status, "message": "中止请求已发送"}

  async def resume_workflow(self, crew_id: str, user_id: str) -> dict[str, Any]:
    crew = self.get_crew(crew_id, user_id)
    if not crew:
      raise ValueError(f"工作流不存在: {crew_id}")
    await crew.resume_execution()
    if crew.status == "completed":
      record_id = result_store.save(
        crew_id=crew.id,
        scenario=crew.scenario,
        user_input=crew.user_input,
        user_id=crew.user_id,
        results=crew._serialize_results(),
        topic_id=crew.topic_id,
        metadata={"collaboration_mode": crew.collaboration_mode},
      )
      return {"status": crew.status, "record_id": record_id, "results": crew._serialize_results()}
    return {"status": crew.status, "results": crew._serialize_results()}


workflow_manager = WorkflowManager()
