"""Crew 任务依赖、暂停/恢复与人机审核"""
from __future__ import annotations

import asyncio

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


class TestParallelExecution:
  @pytest.mark.asyncio
  async def test_runs_independent_tasks_concurrently(self, monkeypatch):
    tasks = [
      TaskDefinition(
        id="task_a",
        name="A",
        description="",
        agent_id="planner",
        depends_on=["task_root"],
      ),
      TaskDefinition(
        id="task_b",
        name="B",
        description="",
        agent_id="planner",
        depends_on=["task_root"],
      ),
      TaskDefinition(
        id="task_c",
        name="C",
        description="",
        agent_id="planner",
        depends_on=["task_root"],
      ),
      TaskDefinition(
        id="task_final",
        name="Final",
        description="",
        agent_id="planner",
        depends_on=["task_a", "task_b", "task_c"],
      ),
    ]
    c = Crew(scenario="test", user_input="需求", tasks=tasks)
    c.results["task_root"] = TaskResult(
      task_id="task_root",
      status=TaskStatus.COMPLETED,
      output="root-output",
    )
    c.status = "running"

    events: list[tuple[str, str]] = []
    gate = asyncio.Event()

    async def delayed_execute(self, task_id, agent, prompt, task_context, feedback="", partial_output=""):
      events.append(("start", task_id))
      await gate.wait()
      events.append(("end", task_id))
      self.results[task_id] = TaskResult(
        task_id=task_id,
        status=TaskStatus.COMPLETED,
        output=f"output-{task_id}",
      )
      return self.results[task_id].output

    monkeypatch.setattr(Crew, "_execute_agent", delayed_execute)

    run_task = asyncio.create_task(c._execute_from_index(0))
    await asyncio.sleep(0.05)
    started = [task_id for kind, task_id in events if kind == "start"]
    assert set(started) == {"task_a", "task_b", "task_c"}
    assert not any(kind == "end" for kind, _ in events)

    gate.set()
    await run_task

    assert c.status == "completed"
    assert c.results["task_final"].status == TaskStatus.COMPLETED
    ended = [task_id for kind, task_id in events if kind == "end"]
    assert set(ended) == {"task_a", "task_b", "task_c", "task_final"}


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


class TestRetryTask:
  @pytest.mark.asyncio
  async def test_retry_reruns_failed_and_downstream_only(self, monkeypatch):
    tasks = [
      TaskDefinition(id="task_a", name="A", description="", agent_id="planner", depends_on=[]),
      TaskDefinition(id="task_b", name="B", description="", agent_id="planner", depends_on=["task_a"]),
      TaskDefinition(id="task_c", name="C", description="", agent_id="planner", depends_on=["task_b"]),
    ]
    c = Crew(scenario="test", user_input="需求", tasks=tasks)
    # 模拟失败现场：task_a 已完成，task_b 失败，task_c 因依赖未满足而失败
    c.results["task_a"] = TaskResult(task_id="task_a", status=TaskStatus.COMPLETED, output="A-output")
    c.results["task_b"] = TaskResult(task_id="task_b", status=TaskStatus.FAILED, output="", error="boom")
    c.results["task_c"] = TaskResult(task_id="task_c", status=TaskStatus.FAILED, output="", error="依赖任务 task_b 未完成")
    c.status = "failed"

    log: list[str] = []

    async def mock_execute(self, task_id, agent, prompt, task_context, feedback="", partial_output="", revision_base=""):
      log.append(task_id)
      result = self.results.get(task_id) or TaskResult(task_id=task_id, status=TaskStatus.RUNNING)
      result.output = f"output-{task_id}"
      self.results[task_id] = result
      return result.output

    monkeypatch.setattr(Crew, "_execute_agent", mock_execute)

    await c.retry_task("task_b")

    assert c.status == "completed"
    assert log == ["task_b", "task_c"]
    # 已完成的上游任务不重复执行、不覆盖
    assert c.results["task_a"].status == TaskStatus.COMPLETED
    assert c.results["task_a"].output == "A-output"
    assert c.results["task_b"].status == TaskStatus.COMPLETED
    assert c.results["task_c"].status == TaskStatus.COMPLETED

  @pytest.mark.asyncio
  async def test_retry_preserves_sibling_tasks(self, monkeypatch):
    """失败任务的重试不影响并行完成的其他任务"""
    tasks = [
      TaskDefinition(id="task_a", name="A", description="", agent_id="planner", depends_on=[]),
      TaskDefinition(id="task_b", name="B", description="", agent_id="planner", depends_on=["task_a"]),
      TaskDefinition(id="task_c", name="C", description="", agent_id="planner", depends_on=["task_a"]),
    ]
    c = Crew(scenario="test", user_input="需求", tasks=tasks)
    c.results["task_a"] = TaskResult(task_id="task_a", status=TaskStatus.COMPLETED, output="A")
    c.results["task_b"] = TaskResult(task_id="task_b", status=TaskStatus.FAILED, output="", error="boom")
    c.results["task_c"] = TaskResult(task_id="task_c", status=TaskStatus.COMPLETED, output="C-output")
    c.status = "failed"

    async def mock_execute(self, task_id, agent, prompt, task_context, feedback="", partial_output="", revision_base=""):
      result = self.results.get(task_id) or TaskResult(task_id=task_id, status=TaskStatus.RUNNING)
      result.output = f"output-{task_id}"
      self.results[task_id] = result
      return result.output

    monkeypatch.setattr(Crew, "_execute_agent", mock_execute)

    await c.retry_task("task_b")

    assert c.status == "completed"
    assert c.results["task_c"].output == "C-output"
    assert c.results["task_b"].output == "output-task_b"

  @pytest.mark.asyncio
  async def test_retry_rejects_non_failed_crew(self, crew, mock_execute_agent):
    with pytest.raises(ValueError, match="仅失败的工作流"):
      await crew.retry_task("task_a")

  @pytest.mark.asyncio
  async def test_retry_rejects_non_failed_task(self):
    tasks = [
      TaskDefinition(id="task_a", name="A", description="", agent_id="planner", depends_on=[]),
      TaskDefinition(id="task_b", name="B", description="", agent_id="planner", depends_on=["task_a"]),
    ]
    c = Crew(scenario="test", user_input="需求", tasks=tasks)
    c.status = "failed"
    c.results["task_a"] = TaskResult(task_id="task_a", status=TaskStatus.COMPLETED, output="A")
    c.results["task_b"] = TaskResult(task_id="task_b", status=TaskStatus.PENDING)

    with pytest.raises(ValueError, match="未处于失败状态"):
      await c.retry_task("task_a")

  @pytest.mark.asyncio
  async def test_retry_emits_resumed_event(self, monkeypatch):
    tasks = [
      TaskDefinition(id="task_a", name="A", description="", agent_id="planner", depends_on=[]),
    ]
    c = Crew(scenario="test", user_input="需求", tasks=tasks)
    c.results["task_a"] = TaskResult(task_id="task_a", status=TaskStatus.FAILED, output="", error="boom")
    c.status = "failed"
    events: list[tuple[str, dict]] = []

    async def capture(event_type, data):
      events.append((event_type, data))

    async def mock_execute(self, task_id, agent, prompt, task_context, feedback="", partial_output="", revision_base=""):
      result = self.results.get(task_id) or TaskResult(task_id=task_id, status=TaskStatus.RUNNING)
      result.output = "ok"
      self.results[task_id] = result
      return result.output

    monkeypatch.setattr(Crew, "_execute_agent", mock_execute)
    c._event_callback = capture

    await c.retry_task("task_a")

    assert any(e[0] == "crew_resumed" for e in events)
    assert any(e[0] == "crew_completed" for e in events)


class TestFinalizeCrewPartialSave:
  """工作流失败时自动保存部分结果（防止白跑 token）"""

  def _failed_crew(self) -> Crew:
    c = Crew(scenario="experiment_design", user_input="测试研究需求", user_id="u1", tasks=[])
    c.results["task_a"] = TaskResult(task_id="task_a", status=TaskStatus.COMPLETED, output="A-结果")
    c.results["task_b"] = TaskResult(task_id="task_b", status=TaskStatus.FAILED, output="", error="boom")
    c.status = "failed"
    return c

  @pytest.mark.asyncio
  async def test_failure_saves_partial_results_once(self, monkeypatch):
    from backend import main

    calls: list[dict] = []

    def fake_save(**kwargs):
      calls.append(kwargs)
      return "record-1"

    monkeypatch.setattr(main.result_store, "save", fake_save)
    crew = self._failed_crew()

    await main._finalize_crew(crew)
    await main._finalize_crew(crew)  # 重复调用不应重复保存

    assert crew._saved_partial is True
    assert len(calls) == 1
    assert calls[0]["metadata"]["partial"] is True
    assert calls[0]["metadata"]["status"] == "failed"
    assert calls[0]["results"]["task_a"]["output"] == "A-结果"

  @pytest.mark.asyncio
  async def test_retry_completion_saves_final_after_partial(self, monkeypatch):
    from backend import main

    calls: list[dict] = []

    def fake_save(**kwargs):
      calls.append(kwargs)
      return "record-1"

    monkeypatch.setattr(main.result_store, "save", fake_save)
    crew = self._failed_crew()

    await main._finalize_crew(crew)
    assert len(calls) == 1

    # 重试成功后以完整结果保存
    crew.status = "completed"
    crew.results["task_b"].status = TaskStatus.COMPLETED
    crew.results["task_b"].output = "B-结果"
    await main._finalize_crew(crew)

    assert crew._saved_complete is True
    assert len(calls) == 2
    assert "partial" not in calls[1]["metadata"]

  @pytest.mark.asyncio
  async def test_completed_crew_saves_normal(self, monkeypatch):
    from backend import main

    calls: list[dict] = []

    def fake_save(**kwargs):
      calls.append(kwargs)
      return "record-1"

    monkeypatch.setattr(main.result_store, "save", fake_save)
    crew = Crew(scenario="experiment_design", user_input="测试研究需求", user_id="u1", tasks=[])
    crew.results["task_a"] = TaskResult(task_id="task_a", status=TaskStatus.COMPLETED, output="A")
    crew.status = "completed"

    await main._finalize_crew(crew)

    assert crew._saved_complete is True
    assert len(calls) == 1
    assert "partial" not in calls[0]["metadata"]
