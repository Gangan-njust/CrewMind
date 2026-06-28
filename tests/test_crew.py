"""Crew 任务依赖、暂停/恢复与人机审核"""
from __future__ import annotations

import pytest

from backend.crew.engine import Crew, CrewSuspended, TaskResult
from backend.tasks.definitions import TaskDefinition, TaskStatus


def _make_tasks() -> list[TaskDefinition]:
  return [
    TaskDefinition(
      id="task_a",
      name="任务 A",
      description="第一个任务",
      agent_id="planner",
      depends_on=[],
    ),
    TaskDefinition(
      id="task_b",
      name="任务 B",
      description="依赖 A",
      agent_id="literature_researcher",
      depends_on=["task_a"],
    ),
    TaskDefinition(
      id="task_c",
      name="任务 C",
      description="依赖 B，需人工审核",
      agent_id="review_specialist",
      depends_on=["task_b"],
      requires_human_review=True,
    ),
  ]


@pytest.fixture
def execution_log():
  return []


@pytest.fixture
def mock_execute_agent(monkeypatch, execution_log):
  async def _mock(self, task_id, agent, prompt, task_context, feedback="", partial_output=""):
    execution_log.append(task_id)
    result = self.results.get(task_id) or TaskResult(
      task_id=task_id, status=TaskStatus.RUNNING,
    )
    self.results[task_id] = result
    if partial_output:
      result.output = partial_output + f" +continued-{task_id}"
    else:
      result.output = f"output-{task_id}"
    return result.output

  monkeypatch.setattr(Crew, "_execute_agent", _mock)
  return execution_log


@pytest.fixture
def crew(mock_execute_agent):
  return Crew(
    scenario="test",
    user_input="测试研究需求描述足够长",
    tasks=_make_tasks(),
  )


class TestTaskDependencies:
  @pytest.mark.asyncio
  async def test_runs_tasks_in_dependency_order(self, crew, execution_log):
    await crew.run()

    assert execution_log == ["task_a", "task_b", "task_c"]
    assert crew.results["task_a"].status == TaskStatus.COMPLETED
    assert crew.results["task_b"].status == TaskStatus.COMPLETED
    assert crew.results["task_c"].status == TaskStatus.WAITING_HUMAN
    assert crew.status == "paused"

  @pytest.mark.asyncio
  async def test_fails_when_dependency_missing(self, monkeypatch):
    tasks = [
      TaskDefinition(
        id="task_a",
        name="A",
        description="",
        agent_id="planner",
        depends_on=[],
      ),
      TaskDefinition(
        id="task_b",
        name="B",
        description="",
        agent_id="planner",
        depends_on=["task_a"],
      ),
    ]
    c = Crew(scenario="test", user_input="需求", tasks=tasks)
    c.status = "running"
    c.results["task_a"] = TaskResult(task_id="task_a", status=TaskStatus.FAILED)

    async def noop_execute(self, task_id, agent, prompt, task_context, feedback="", partial_output=""):
      self.results[task_id] = TaskResult(task_id=task_id, status=TaskStatus.COMPLETED, output="x")
      return "x"

    monkeypatch.setattr(Crew, "_execute_agent", noop_execute)
    await c._execute_from_index(1)

    assert c.results["task_b"].status == TaskStatus.FAILED
    assert "依赖任务 task_a 未完成" in c.results["task_b"].error
    assert c.status == "failed"


class TestSuspendAndResume:
  @pytest.mark.asyncio
  async def test_suspend_during_task(self, monkeypatch):
    c = Crew(
      scenario="test",
      user_input="需求",
      tasks=[TaskDefinition(
        id="task_a", name="A", description="", agent_id="planner", depends_on=[],
      )],
    )

    async def suspending_execute(self, task_id, agent, prompt, task_context, feedback="", partial_output=""):
      raise CrewSuspended()

    monkeypatch.setattr(Crew, "_execute_agent", suspending_execute)
    await c.run()

    assert c.status == "suspended"
    assert c._suspended_task_id == "task_a"
    assert c.results["task_a"].status == TaskStatus.SUSPENDED

  @pytest.mark.asyncio
  async def test_resume_continues_suspended_task(self, monkeypatch, execution_log):
    c = Crew(
      scenario="test",
      user_input="需求",
      tasks=[
        TaskDefinition(
          id="task_a", name="A", description="", agent_id="planner", depends_on=[],
        ),
        TaskDefinition(
          id="task_b", name="B", description="", agent_id="planner", depends_on=["task_a"],
        ),
      ],
    )
    c.status = "suspended"
    c._suspended_task_id = "task_a"
    c.results["task_a"] = TaskResult(
      task_id="task_a",
      status=TaskStatus.SUSPENDED,
      output="partial-output",
    )

    async def track_execute(self, task_id, agent, prompt, task_context, feedback="", partial_output=""):
      execution_log.append((task_id, partial_output))
      result = self.results.get(task_id) or TaskResult(task_id=task_id, status=TaskStatus.RUNNING)
      result.status = TaskStatus.RUNNING
      result.output = partial_output or f"done-{task_id}"
      self.results[task_id] = result
      return result.output

    monkeypatch.setattr(Crew, "_execute_agent", track_execute)
    await c.resume_execution()

    assert c.status == "completed"
    assert execution_log[0] == ("task_a", "partial-output")
    assert execution_log[1] == ("task_b", "")
    assert c.results["task_b"].status == TaskStatus.COMPLETED

  @pytest.mark.asyncio
  async def test_request_suspend_only_when_running(self, crew, mock_execute_agent):
    with pytest.raises(ValueError, match="只有运行中的工作流"):
      await crew.request_suspend()

  @pytest.mark.asyncio
  async def test_resume_rejects_non_suspended_crew(self, crew):
    with pytest.raises(ValueError, match="未处于中止状态"):
      await crew.resume_execution()


class TestHumanReview:
  @pytest.mark.asyncio
  async def test_resume_with_feedback_approved_continues(self, crew, mock_execute_agent, execution_log):
    await crew.run()
    assert crew.status == "paused"

    await crew.resume_with_feedback("task_c", feedback="", approved=True)

    assert crew.status == "completed"
    assert crew.results["task_c"].status == TaskStatus.COMPLETED

  @pytest.mark.asyncio
  async def test_resume_with_feedback_regenerates_on_comments(self, monkeypatch):
    c = Crew(
      scenario="test",
      user_input="需求",
      tasks=[
        TaskDefinition(
          id="task_a",
          name="A",
          description="",
          agent_id="planner",
          depends_on=[],
          requires_human_review=True,
        ),
      ],
    )
    c.status = "paused"
    c.results["task_a"] = TaskResult(
      task_id="task_a",
      status=TaskStatus.WAITING_HUMAN,
      output="original",
    )

    regen_calls: list[tuple[str, str]] = []

    async def regen_execute(self, task_id, agent, prompt, task_context, feedback="", partial_output="", revision_base=""):
      regen_calls.append((feedback, revision_base))
      self.results[task_id].output = f"revised-{feedback}"
      return self.results[task_id].output

    monkeypatch.setattr(Crew, "_execute_agent", regen_execute)
    await c.resume_with_feedback("task_a", feedback="请补充方法细节", approved=True)

    assert regen_calls == [("请补充方法细节", "original")]
    assert c.results["task_a"].output == "revised-请补充方法细节"
    assert c.status == "completed"

  @pytest.mark.asyncio
  async def test_resume_with_feedback_rejected_fails_crew(self, crew, mock_execute_agent):
    await crew.run()

    await crew.resume_with_feedback("task_c", feedback="方案不可行", approved=False)

    assert crew.status == "failed"
    assert crew.results["task_c"].status == TaskStatus.FAILED
    assert crew.results["task_c"].human_feedback == "方案不可行"

  @pytest.mark.asyncio
  async def test_resume_with_feedback_validates_state(self, crew, mock_execute_agent):
    await crew.run()
    crew.status = "running"
    with pytest.raises(ValueError, match="未处于待审核状态"):
      await crew.resume_with_feedback("task_c", feedback="", approved=True)

  @pytest.mark.asyncio
  async def test_events_emitted_during_run(self, crew, mock_execute_agent):
    events: list[tuple[str, dict]] = []

    async def capture(event_type, data):
      events.append((event_type, data))

    crew._event_callback = capture
    await crew.run()

    event_types = [e[0] for e in events]
    assert "crew_started" in event_types
    assert "task_started" in event_types
    assert "human_review_required" in event_types
