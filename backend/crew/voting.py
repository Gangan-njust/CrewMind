"""投票模式编排器"""
import asyncio
import logging
from datetime import datetime

from backend.crew.collaboration import (
  VOTING_AGGREGATE_TASK_ID,
  VOTING_SOLVER_CONFIGS,
  build_aggregator_prompt,
  build_solver_prompt,
  format_voting_output,
)
from backend.crew.engine import Agent, Crew, CrewSuspended
from backend.tasks.definitions import TaskStatus

logger = logging.getLogger(__name__)

SOLVER_NAMES = {
  "task_vote_planner": "求解者·规划师",
  "task_vote_designer": "求解者·设计师",
  "task_vote_analyst": "求解者·分析师",
}


async def run_voting(crew: Crew, *, resume: bool = False) -> dict:
  """执行投票模式工作流"""
  if not resume:
    crew._voting_solver_outputs = {}
    crew._voting_phase = "solvers"

  try:
    if crew._voting_phase == "solvers":
      await crew._emit("voting_solvers_started", {
        "count": len(VOTING_SOLVER_CONFIGS),
        "task_ids": [cfg[0] for cfg in VOTING_SOLVER_CONFIGS],
      })

      pending = [
        cfg for cfg in VOTING_SOLVER_CONFIGS
        if cfg[0] not in crew._voting_solver_outputs
        or crew.results.get(cfg[0], None) and crew.results[cfg[0]].status != TaskStatus.COMPLETED
      ]

      if pending:
        await asyncio.gather(*[
          _run_solver(crew, task_id, agent_id, focus)
          for task_id, agent_id, focus in pending
        ])

      incomplete = [
        cfg[0] for cfg in VOTING_SOLVER_CONFIGS
        if crew.results.get(cfg[0], None) is None
        or crew.results[cfg[0]].status != TaskStatus.COMPLETED
      ]
      if incomplete:
        return crew.results

      if crew._user_pause_requested:
        crew._voting_phase = "aggregator"
        raise CrewSuspended()

      crew._voting_phase = "aggregator"

    if crew._voting_phase == "aggregator":
      await _run_aggregator(crew)

    if crew.status == "running":
      crew.status = "completed"
      await crew._emit("crew_completed", {"crew_id": crew.id, "results": crew._serialize_results()})

    return crew.results

  except CrewSuspended:
    suspended_id = _find_suspended_solver(crew) or VOTING_AGGREGATE_TASK_ID
    await crew._handle_suspend(suspended_id)
    return crew.results
  except Exception as e:
    logger.exception("Voting mode failed")
    task_id = _find_suspended_solver(crew) or VOTING_AGGREGATE_TASK_ID
    await crew._fail_task(task_id, str(e))
    return crew.results


async def _run_solver(crew: Crew, task_id: str, agent_id: str, focus: str) -> None:
  existing = crew.results.get(task_id)
  if existing and existing.status == TaskStatus.COMPLETED:
    crew._voting_solver_outputs[task_id] = existing.output
    return

  resume_partial = ""
  if existing and existing.status == TaskStatus.SUSPENDED:
    resume_partial = existing.output
    existing.status = TaskStatus.RUNNING
    await crew._emit("task_resumed", {
      "task_id": task_id,
      "task_name": SOLVER_NAMES.get(task_id, task_id),
      "output": resume_partial,
      "collaboration_mode": "voting",
    })
  else:
    crew._init_task_result(task_id, SOLVER_NAMES.get(task_id, task_id), agent_id)
    await crew._emit("task_started", {
      "task_id": task_id,
      "task_name": SOLVER_NAMES.get(task_id, task_id),
      "agent_id": agent_id,
      "collaboration_mode": "voting",
      "parallel": True,
    })

  agent_role = crew._resolve_agent(agent_id)
  if not agent_role:
    raise ValueError(f"未找到求解者 Agent: {agent_id}")

  prompt = build_solver_prompt(crew.user_input, focus, crew.scenario)
  agent = Agent(role=agent_role)

  try:
    output = await crew._execute_agent(
      task_id, agent, prompt, {}, partial_output=resume_partial,
    )
  except CrewSuspended:
    raise

  result = crew.results[task_id]
  result.output = output
  result.completed_at = datetime.now()
  result.status = TaskStatus.COMPLETED
  result.metadata = {"solver_focus": focus}
  crew._voting_solver_outputs[task_id] = output

  await crew._emit("voting_solver_completed", {
    "task_id": task_id,
    "agent_id": agent_id,
    "output_preview": output[:200],
  })
  await crew._emit("task_completed", {"task_id": task_id, "output": output})


async def _run_aggregator(crew: Crew) -> None:
  task_id = VOTING_AGGREGATE_TASK_ID
  agent_id = "review_specialist"

  existing = crew.results.get(task_id)
  resume_partial = ""
  if existing and existing.status == TaskStatus.SUSPENDED:
    resume_partial = existing.output
    existing.status = TaskStatus.RUNNING
    await crew._emit("task_resumed", {
      "task_id": task_id,
      "task_name": "方案聚合评审",
      "output": resume_partial,
      "collaboration_mode": "voting",
    })
  else:
    crew._init_task_result(task_id, "方案聚合评审", agent_id)
    await crew._emit("task_started", {
      "task_id": task_id,
      "task_name": "方案聚合评审",
      "agent_id": agent_id,
      "collaboration_mode": "voting",
    })

  agent_role = crew._resolve_agent(agent_id)
  if not agent_role:
    raise ValueError("未找到聚合者 Agent")

  prompt = build_aggregator_prompt(
    crew.user_input,
    crew._voting_solver_outputs,
    SOLVER_NAMES,
  )
  agent = Agent(role=agent_role)

  aggregator_report = await crew._execute_agent(
    task_id, agent, prompt, {}, partial_output=resume_partial,
  )

  winner_proposal = _extract_winner_proposal(aggregator_report, crew._voting_solver_outputs)
  final_output = format_voting_output(
    winner_proposal,
    aggregator_report,
    crew._voting_solver_outputs,
    SOLVER_NAMES,
  )

  result = crew.results[task_id]
  result.output = final_output
  result.completed_at = datetime.now()
  result.status = TaskStatus.COMPLETED
  result.metadata = {
    "aggregator_result": aggregator_report,
    "solver_results": crew._voting_solver_outputs,
    "winner_proposal": winner_proposal,
  }

  await crew._emit("task_completed", {"task_id": task_id, "output": final_output})


def _extract_winner_proposal(aggregator_report: str, solver_outputs: dict[str, str]) -> str:
  marker = "## 最优方案正文"
  if marker in aggregator_report:
    body = aggregator_report.split(marker, 1)[1].strip()
    json_idx = body.find("```json")
    if json_idx >= 0:
      body = body[:json_idx].strip()
    if body:
      return body

  if solver_outputs:
    return next(iter(solver_outputs.values()))
  return aggregator_report


def _find_suspended_solver(crew: Crew) -> str | None:
  for task_id, _, _ in VOTING_SOLVER_CONFIGS:
    result = crew.results.get(task_id)
    if result and result.status in (TaskStatus.SUSPENDED, TaskStatus.RUNNING):
      return task_id
  if crew.results.get(VOTING_AGGREGATE_TASK_ID):
    return VOTING_AGGREGATE_TASK_ID
  return VOTING_SOLVER_CONFIGS[0][0]
