"""辩论模式编排器"""
import logging
from datetime import datetime

from backend.agents.roles import AgentRole
from backend.config import settings
from backend.crew.collaboration import (
  DEBATE_TASK_ID,
  build_debate_critic_prompt,
  build_debate_init_prompt,
  build_debate_judge_prompt,
  build_debate_revision_prompt,
  debate_critic_role,
  debate_judge_role,
  debate_proponent_role,
  format_debate_history,
  format_debate_output,
  parse_judge_decision,
  resolve_debate_proponent_agent_id,
)
from backend.crew.engine import Agent, Crew, CrewSuspended
from backend.tasks.definitions import TaskStatus

logger = logging.getLogger(__name__)


async def run_debate(crew: Crew, *, resume: bool = False) -> dict:
  """执行辩论模式工作流"""
  task_id = DEBATE_TASK_ID
  max_rounds = settings.max_iterations

  if not resume:
    crew._debate_history = []
    crew._debate_round = 0
    crew._debate_phase = "init"
    crew._current_proposal = ""
    result = crew.results.get(task_id)
    if not result:
      result = crew._init_task_result(task_id, "方案辩论", resolve_debate_proponent_agent_id(crew.scenario))
      await crew._emit("task_started", {
        "task_id": task_id,
        "task_name": "方案辩论",
        "agent_id": resolve_debate_proponent_agent_id(crew.scenario),
        "collaboration_mode": "debate",
      })
  else:
    result = crew.results.get(task_id)
    if not result:
      raise ValueError("辩论任务不存在，无法恢复")
    result.status = TaskStatus.RUNNING
    await crew._emit("task_resumed", {
      "task_id": task_id,
      "task_name": "方案辩论",
      "output": result.output,
      "collaboration_mode": "debate",
    })

  try:
    proponent_id = resolve_debate_proponent_agent_id(crew.scenario)
    proponent_base = crew._resolve_agent(proponent_id)
    critic_base = crew._resolve_agent("review_specialist")
    judge_base = crew._resolve_agent("review_specialist")

    if not proponent_base or not critic_base or not judge_base:
      raise ValueError("辩论模式所需 Agent 角色未配置完整")

    if crew._debate_phase == "init" and not crew._current_proposal:
      await _run_debate_phase(
        crew, task_id, "proponent_init", 0, max_rounds,
        proponent_base, debate_proponent_role(proponent_base),
        build_debate_init_prompt(crew.user_input, crew.scenario),
      )
      crew._debate_phase = "critic"

    while crew._debate_round < max_rounds:
      round_num = crew._debate_round + 1

      if crew._debate_phase == "critic":
        await crew._emit("debate_round_started", {
          "round": round_num,
          "max_rounds": max_rounds,
          "task_id": task_id,
        })
        history_text = format_debate_history(crew._debate_history)
        await _run_debate_phase(
          crew, task_id, "critic", round_num, max_rounds,
          critic_base, debate_critic_role(critic_base),
          build_debate_critic_prompt(crew.user_input, crew._current_proposal, history_text),
        )
        crew._debate_phase = "proponent"

      if crew._user_pause_requested:
        crew._debate_checkpoint = "round_end"
        raise CrewSuspended()

      if crew._debate_phase == "proponent":
        last_critic = _last_entry(crew._debate_history, "critic", round_num)
        history_text = format_debate_history(crew._debate_history)
        await _run_debate_phase(
          crew, task_id, "proponent", round_num, max_rounds,
          proponent_base, debate_proponent_role(proponent_base),
          build_debate_revision_prompt(
            crew.user_input,
            crew._current_proposal,
            last_critic.get("content", "") if last_critic else "",
            history_text,
          ),
        )
        crew._current_proposal = _extract_revised_proposal(crew.results[task_id].output)
        crew._debate_phase = "judge"

      if crew._user_pause_requested:
        crew._debate_checkpoint = "round_end"
        raise CrewSuspended()

      if crew._debate_phase == "judge":
        history_text = format_debate_history(crew._debate_history)
        judge_output = await _run_debate_phase(
          crew, task_id, "judge", round_num, max_rounds,
          judge_base, debate_judge_role(judge_base),
          build_debate_judge_prompt(
            crew.user_input, crew._current_proposal, history_text, round_num, max_rounds,
          ),
        )
        decision = parse_judge_decision(judge_output)
        crew._debate_history.append({
          "round": round_num,
          "phase": "judge_decision",
          "content": judge_output,
          "decision": decision,
        })

        crew._debate_round = round_num
        should_continue = decision["should_continue"] and round_num < max_rounds

        await crew._emit("debate_judge_decision", {
          "round": round_num,
          "should_continue": should_continue,
          "reason": decision.get("reason", ""),
          "task_id": task_id,
        })

        if not should_continue:
          break

        crew._debate_phase = "critic"

    final_output = format_debate_output(
      crew._current_proposal,
      crew._debate_history,
      crew._debate_round or 1,
    )
    result = crew.results[task_id]
    result.output = final_output
    result.completed_at = datetime.now()
    result.status = TaskStatus.COMPLETED
    result.metadata = {
      "debate_rounds": crew._debate_round or 1,
      "debate_history": crew._debate_history,
      "final_proposal": crew._current_proposal,
    }

    if crew.status == "running":
      crew.status = "completed"
      await crew._emit("task_completed", {"task_id": task_id, "output": final_output})
      await crew._emit("crew_completed", {"crew_id": crew.id, "results": crew._serialize_results()})

    return crew.results

  except CrewSuspended:
    await crew._handle_suspend(task_id)
    return crew.results
  except Exception as e:
    logger.exception("Debate mode failed")
    await crew._fail_task(task_id, str(e))
    return crew.results


async def _run_debate_phase(
  crew: Crew,
  task_id: str,
  phase: str,
  round_num: int,
  max_rounds: int,
  base_role: AgentRole,
  role: AgentRole,
  prompt: str,
) -> str:
  await crew._emit("debate_phase_started", {
    "task_id": task_id,
    "phase": phase,
    "round": round_num,
    "max_rounds": max_rounds,
    "agent_id": base_role.id,
  })

  result = crew.results[task_id]
  partial = ""
  if result.status == TaskStatus.SUSPENDED:
    partial = result.output

  result.status = TaskStatus.RUNNING
  if not partial:
    result.output = ""

  agent = Agent(role=role)
  output = await crew._execute_agent(
    task_id, agent, prompt, {}, partial_output=partial,
  )

  crew._debate_history.append({
    "round": round_num,
    "phase": phase.replace("_init", ""),
    "content": output,
  })

  if phase in ("proponent_init", "proponent"):
    crew._current_proposal = _extract_revised_proposal(output)

  return output


def _last_entry(history: list[dict], phase: str, round_num: int) -> dict | None:
  for entry in reversed(history):
    if entry.get("phase") == phase and entry.get("round") == round_num:
      return entry
  return None


def _extract_revised_proposal(text: str) -> str:
  marker = "## 修订后的完整方案"
  if marker in text:
    return text.split(marker, 1)[1].strip()
  if "# 修订方案" in text:
    return text
  return text
