"""协作模式：辩论 / 投票"""
import pytest

from backend.crew.collaboration import (
  CollaborationMode,
  get_debate_tasks,
  get_voting_tasks,
  parse_judge_decision,
)
from backend.crew.engine import Crew
from backend.crew.manager import WorkflowManager


class TestCollaborationDefinitions:
  def test_debate_task_single(self):
    tasks = get_debate_tasks()
    assert len(tasks) == 1
    assert tasks[0].id == "task_debate"

  def test_voting_tasks_include_solvers_and_aggregator(self):
    tasks = get_voting_tasks()
    ids = [t.id for t in tasks]
    assert "task_vote_planner" in ids
    assert "task_vote_aggregate" in ids
    agg = next(t for t in tasks if t.id == "task_vote_aggregate")
    assert set(agg.depends_on) == {"task_vote_planner", "task_vote_designer", "task_vote_analyst"}

  def test_parse_judge_decision_json_block(self):
    text = """# 评估报告

方案已完善。

```json
{"should_continue": false, "reason": "已充分回应", "scores": {"completeness": 9}}
```
"""
    decision = parse_judge_decision(text)
    assert decision["should_continue"] is False
    assert "已充分回应" in decision["reason"]

  def test_parse_judge_decision_fallback(self):
    decision = parse_judge_decision("无结构化输出")
    assert decision["should_continue"] is False


class TestWorkflowManagerCollaboration:
  @pytest.mark.asyncio
  async def test_start_debate_workflow(self):
    wm = WorkflowManager()
    crew = await wm.start_workflow(
      scenario="experiment_design",
      user_input="测试研究需求描述足够长用于辩论模式",
      user_id="test-user",
      collaboration_mode=CollaborationMode.DEBATE.value,
    )
    assert crew.collaboration_mode == "debate"
    assert len(crew.tasks) == 1
    assert crew.tasks[0].id == "task_debate"

  @pytest.mark.asyncio
  async def test_start_voting_workflow(self):
    wm = WorkflowManager()
    crew = await wm.start_workflow(
      scenario="full_proposal",
      user_input="测试研究需求描述足够长用于投票模式",
      user_id="test-user",
      collaboration_mode=CollaborationMode.VOTING.value,
    )
    assert crew.collaboration_mode == "voting"
    assert len(crew.tasks) == 4

  @pytest.mark.asyncio
  async def test_debate_run_with_mock(self, monkeypatch):
    wm = WorkflowManager()
    crew = await wm.start_workflow(
      scenario="experiment_design",
      user_input="测试研究需求描述足够长",
      user_id="test-user",
      collaboration_mode="debate",
    )

    call_count = {"n": 0}

    async def mock_execute(self, task_id, agent, prompt, task_context, feedback="", partial_output=""):
      call_count["n"] += 1
      result = self.results.get(task_id)
      if not result:
        result = self._init_task_result(task_id, "方案辩论", "experiment_designer")
      if "裁判" in prompt or "should_continue" in prompt:
        output = '评估完成\n```json\n{"should_continue": false, "reason": "ok"}\n```'
      elif "反方" in prompt or "质疑" in prompt:
        output = "# 反方质疑\n\n1. **逻辑** 样本量不足"
      else:
        output = "# 修订方案\n\n## 修订后的完整方案\n\n完整方案正文"
      result.output = output
      return output

    monkeypatch.setattr(Crew, "_execute_agent", mock_execute)
    await crew.run()

    assert crew.status == "completed"
    assert crew.results["task_debate"].status.value == "completed"
    assert "完整方案正文" in crew.results["task_debate"].output
    assert call_count["n"] >= 3
