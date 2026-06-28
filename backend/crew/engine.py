"""步骤4-6：Agent 实例、Task 执行与 Crew 编排"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable

from backend.agents.roles import AgentRole
from backend.llm.client import DeepSeekClient
from backend.tasks.definitions import TaskDefinition, TaskStatus
from backend.tools.registry import run_agent_tools

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class CrewSuspended(Exception):
  """用户请求中止（暂停）工作流"""


@dataclass
class TaskResult:
  task_id: str
  status: TaskStatus
  output: str = ""
  error: str = ""
  started_at: datetime | None = None
  completed_at: datetime | None = None
  human_feedback: str = ""
  metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Agent:
  """智能体实例"""
  role: AgentRole
  llm: DeepSeekClient = field(default_factory=DeepSeekClient)

  async def execute(
    self,
    task_prompt: str,
    context_outputs: dict[str, str] | None = None,
    human_feedback: str = "",
    partial_output: str = "",
    revision_base: str = "",
    user_input: str = "",
    reference_files: list[str] | None = None,
    on_chunk: Callable[[str], Awaitable[None]] | None = None,
    on_tool_event: Callable[[str, str, str], Awaitable[None]] | None = None,
  ) -> str:
    """执行任务，支持工具调用、人工反馈注入、断点续写与流式输出"""
    messages = [{"role": "system", "content": self.role.system_prompt()}]

    user_content = task_prompt
    if human_feedback and not revision_base:
      user_content += f"\n\n## 人工审核反馈\n\n请根据以下反馈意见修改和完善你的输出：\n{human_feedback}"

    messages.append({"role": "user", "content": user_content})

    tool_messages = await run_agent_tools(
      self.role,
      task_prompt,
      user_input,
      context_outputs,
      reference_files or [],
      partial_output,
      on_tool_event=on_tool_event,
    )
    messages.extend(tool_messages)

    if revision_base and human_feedback:
      messages.append({"role": "assistant", "content": revision_base})
      messages.append({
        "role": "user",
        "content": (
          "以上是你在上一阶段的输出。请根据以下人工审核意见进行修改和完善，"
          "输出修改后的完整内容（不要只输出修改部分，不要重复解释修改过程）：\n\n"
          f"{human_feedback}"
        ),
      })
    elif partial_output:
      messages.append({"role": "assistant", "content": partial_output})
      messages.append({
        "role": "user",
        "content": (
          "上述内容因用户中止而中断。请从中断处无缝续写，"
          "不要重复已有内容，不要重新开头，直接输出剩余部分。"
        ),
      })

    if on_chunk:
      stream = await self.llm.chat(
        messages,
        use_reasoning=self.role.use_reasoning,
        stream=True,
      )
      parts: list[str] = []
      async for chunk in stream:
        parts.append(chunk)
        await on_chunk(chunk)
      return "".join(parts)

    return await self.llm.chat(
      messages,
      use_reasoning=self.role.use_reasoning,
    )


@dataclass
class Crew:
  """多智能体编排引擎"""
  id: str = field(default_factory=lambda: str(uuid.uuid4()))
  scenario: str = ""
  user_input: str = ""
  user_id: str = ""
  topic_id: str | None = None
  reference_files: list[str] = field(default_factory=list)
  tasks: list[TaskDefinition] = field(default_factory=list)
  agent_registry: dict[str, AgentRole] = field(default_factory=dict)
  results: dict[str, TaskResult] = field(default_factory=dict)
  collaboration_mode: str = "sequential"
  status: str = "idle"  # idle | running | paused | suspended | completed | failed
  _event_callback: EventCallback | None = field(default=None, repr=False)
  _human_feedback_queue: dict[str, str] = field(default_factory=dict, repr=False)
  _user_pause_requested: bool = field(default=False, repr=False)
  _suspended_task_id: str | None = field(default=None, repr=False)
  _debate_history: list[dict[str, Any]] = field(default_factory=list, repr=False)
  _debate_round: int = field(default=0, repr=False)
  _debate_phase: str = field(default="init", repr=False)
  _debate_checkpoint: str = field(default="", repr=False)
  _current_proposal: str = field(default="", repr=False)
  _voting_solver_outputs: dict[str, str] = field(default_factory=dict, repr=False)
  _voting_phase: str = field(default="solvers", repr=False)

  def _resolve_agent(self, agent_id: str) -> AgentRole | None:
    if self.agent_registry:
      return self.agent_registry.get(agent_id)
    from backend.agents.roles import ALL_AGENTS
    return ALL_AGENTS.get(agent_id)

  async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
    if self._event_callback:
      await self._event_callback(event_type, data)

  async def _execute_agent(
    self,
    task_id: str,
    agent: Agent,
    prompt: str,
    task_context: dict[str, str],
    feedback: str = "",
    partial_output: str = "",
    revision_base: str = "",
  ) -> str:
    """执行 Agent 并通过 WebSocket 流式推送输出片段"""
    if self._user_pause_requested:
      raise CrewSuspended()

    result = self.results.get(task_id)
    if result:
      if revision_base or not partial_output:
        result.output = ""

    async def on_chunk(chunk: str) -> None:
      if self._user_pause_requested:
        raise CrewSuspended()
      if result:
        result.output += chunk
      await self._emit("task_output_chunk", {"task_id": task_id, "chunk": chunk})

    async def on_tool_event(tool_name: str, status: str, detail: str) -> None:
      await self._emit("tool_invoked", {
        "task_id": task_id,
        "tool": tool_name,
        "status": status,
        "detail": detail,
      })

    await agent.execute(
      prompt,
      task_context,
      feedback,
      partial_output=partial_output,
      revision_base=revision_base,
      user_input=self.user_input,
      reference_files=self.reference_files,
      on_chunk=on_chunk,
      on_tool_event=on_tool_event,
    )
    return result.output if result else ""

  async def request_suspend(self) -> None:
    """请求中止当前工作流（可在任务间隙或流式输出中生效）"""
    if self.status != "running":
      raise ValueError("只有运行中的工作流可以中止")
    self._user_pause_requested = True

  async def _handle_suspend(self, task_id: str) -> None:
    self._user_pause_requested = False
    self.status = "suspended"
    self._suspended_task_id = task_id
    result = self.results.get(task_id)
    if result and result.status == TaskStatus.RUNNING:
      result.status = TaskStatus.SUSPENDED
    await self._emit("crew_suspended", {
      "crew_id": self.id,
      "task_id": task_id,
      "output": result.output if result else "",
    })

  def _init_task_result(self, task_id: str, task_name: str, agent_id: str) -> TaskResult:
    result = TaskResult(
      task_id=task_id,
      status=TaskStatus.RUNNING,
      started_at=datetime.now(),
    )
    self.results[task_id] = result
    return result

  async def resume_execution(self) -> dict[str, TaskResult]:
    """从中止状态继续执行"""
    if self.status != "suspended":
      raise ValueError("工作流未处于中止状态，无法继续")
    if not self._suspended_task_id:
      raise ValueError("无法确定恢复点")

    suspended_task_id = self._suspended_task_id
    self._suspended_task_id = None
    self.status = "running"
    await self._emit("crew_resumed", {"crew_id": self.id})

    if self.collaboration_mode == "debate":
      from backend.crew.debate import run_debate
      return await run_debate(self, resume=True)

    if self.collaboration_mode == "voting":
      from backend.crew.voting import run_voting
      return await run_voting(self, resume=True)

    start_idx = next(
      (i for i, t in enumerate(self.tasks) if t.id == suspended_task_id),
      None,
    )
    if start_idx is None:
      raise ValueError(f"恢复任务不存在: {suspended_task_id}")

    return await self._execute_from_index(start_idx)

  async def run(self) -> dict[str, TaskResult]:
    """按协作模式执行任务流程"""
    self.status = "running"
    await self._emit("crew_started", {
      "crew_id": self.id,
      "scenario": self.scenario,
      "collaboration_mode": self.collaboration_mode,
    })

    if self.collaboration_mode == "debate":
      from backend.crew.debate import run_debate
      return await run_debate(self)

    if self.collaboration_mode == "voting":
      from backend.crew.voting import run_voting
      return await run_voting(self)

    return await self._execute_from_index(0)

  async def _execute_from_index(self, start_idx: int) -> dict[str, TaskResult]:
    context: dict[str, str] = {
      tid: r.output
      for tid, r in self.results.items()
      if r.status == TaskStatus.COMPLETED
    }

    for task_def in self.tasks[start_idx:]:
      if self._user_pause_requested:
        await self._handle_suspend(task_def.id)
        return self.results

      if task_def.id in self.results and self.results[task_def.id].status == TaskStatus.COMPLETED:
        continue

      for dep in task_def.depends_on:
        dep_result = self.results.get(dep)
        if not dep_result or dep_result.status != TaskStatus.COMPLETED:
          await self._fail_task(task_def.id, f"依赖任务 {dep} 未完成")
          break
      else:
        existing = self.results.get(task_def.id)
        resume = existing is not None and existing.status == TaskStatus.SUSPENDED
        outcome = await self._run_task(task_def, context, resume=resume)
        if outcome in ("suspended", "paused", "failed"):
          return self.results

    if self.status == "running":
      self.status = "completed"
      await self._emit("crew_completed", {"crew_id": self.id, "results": self._serialize_results()})
    return self.results

  async def _run_task(
    self,
    task_def: TaskDefinition,
    context: dict[str, str],
    *,
    resume: bool = False,
  ) -> str:
    """执行单个任务，返回: completed | suspended | paused | failed"""
    task_context = {dep: context[dep] for dep in task_def.depends_on if dep in context}

    partial_output = ""
    existing = self.results.get(task_def.id)
    if resume and existing and existing.status == TaskStatus.SUSPENDED:
      result = existing
      partial_output = existing.output
      result.status = TaskStatus.RUNNING
      await self._emit("task_resumed", {
        "task_id": task_def.id,
        "task_name": task_def.name,
        "output": partial_output,
      })
    else:
      result = TaskResult(
        task_id=task_def.id,
        status=TaskStatus.RUNNING,
        started_at=datetime.now(),
      )
      self.results[task_def.id] = result
      await self._emit("task_started", {
        "task_id": task_def.id,
        "task_name": task_def.name,
        "agent_id": task_def.agent_id,
      })

    try:
      agent_role = self._resolve_agent(task_def.agent_id)
      if not agent_role:
        raise ValueError(f"未找到 Agent: {task_def.agent_id}")

      agent = Agent(role=agent_role)
      prompt = task_def.build_prompt(self.user_input, task_context)
      feedback = self._human_feedback_queue.pop(task_def.id, "")

      output = await self._execute_agent(
        task_def.id, agent, prompt, task_context, feedback,
        partial_output=partial_output,
      )
      result.output = output
      result.completed_at = datetime.now()
      context[task_def.id] = output

      if task_def.requires_human_review:
        result.status = TaskStatus.WAITING_HUMAN
        self.status = "paused"
        await self._emit("human_review_required", {
          "task_id": task_def.id,
          "task_name": task_def.name,
          "output": output,
        })
        return "paused"

      result.status = TaskStatus.COMPLETED
      await self._emit("task_completed", {"task_id": task_def.id, "output": output})
      return "completed"

    except CrewSuspended:
      await self._handle_suspend(task_def.id)
      return "suspended"
    except Exception as e:
      logger.exception("Task %s failed", task_def.id)
      await self._fail_task(task_def.id, str(e))
      return "failed"

  async def resume_with_feedback(self, task_id: str, feedback: str, approved: bool = True) -> dict[str, TaskResult]:
    """人工审核后恢复执行"""
    result = self.results.get(task_id)
    if not result:
      raise ValueError(f"任务不存在: {task_id}")
    if self.status != "paused":
      raise ValueError("工作流未处于待审核状态")
    if result.status != TaskStatus.WAITING_HUMAN:
      raise ValueError("该任务不在待审核状态")

    result.human_feedback = feedback

    if not approved:
      result.status = TaskStatus.FAILED
      self.status = "failed"
      await self._emit("crew_failed", {"reason": f"人工驳回任务 {task_id}: {feedback}"})
      return self.results

    self.status = "running"

    if feedback:
      task_def = next((t for t in self.tasks if t.id == task_id), None)
      if task_def:
        agent_role = self._resolve_agent(task_def.agent_id)
        if agent_role:
          result.status = TaskStatus.RUNNING
          await self._emit("task_started", {
            "task_id": task_id,
            "task_name": task_def.name,
            "agent_id": task_def.agent_id,
          })
          agent = Agent(role=agent_role)
          context = {
            dep: self.results[dep].output
            for dep in task_def.depends_on
            if dep in self.results
          }
          prompt = task_def.build_prompt(self.user_input, context)
          original_output = result.output
          try:
            result.output = await self._execute_agent(
              task_id, agent, prompt, context, feedback,
              revision_base=original_output,
            )
            result.completed_at = datetime.now()
          except CrewSuspended:
            await self._handle_suspend(task_id)
            return self.results

    result.status = TaskStatus.COMPLETED
    if not result.completed_at:
      result.completed_at = datetime.now()
    await self._emit("task_completed", {"task_id": task_id, "output": result.output})

    start_idx = next(i for i, t in enumerate(self.tasks) if t.id == task_id) + 1
    if start_idx < len(self.tasks):
      return await self._execute_from_index(start_idx)

    self.status = "completed"
    await self._emit("crew_completed", {"crew_id": self.id, "results": self._serialize_results()})
    return self.results

  async def _fail_task(self, task_id: str, error: str) -> None:
    result = self.results.get(task_id) or TaskResult(task_id=task_id, status=TaskStatus.FAILED)
    result.status = TaskStatus.FAILED
    result.error = error
    result.completed_at = datetime.now()
    self.results[task_id] = result
    self.status = "failed"
    await self._emit("task_failed", {"task_id": task_id, "error": error})

  def _serialize_results(self) -> dict:
    serialized: dict[str, dict[str, Any]] = {}
    for tid, r in self.results.items():
      entry: dict[str, Any] = {
        "status": r.status.value,
        "output": r.output,
        "error": r.error,
        "human_feedback": r.human_feedback,
      }
      if r.metadata:
        entry["metadata"] = r.metadata
      serialized[tid] = entry
    return serialized
