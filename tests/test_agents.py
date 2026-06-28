"""Agent 注册表与任务过滤测试"""
import pytest

from backend.agents.registry import (
  create_custom_agent,
  delete_custom_agent,
  get_agent_registry,
  is_builtin,
  list_agents,
)
from backend.auth import get_user_by_username
from backend.storage.database import setup_database
from backend.tasks.definitions import TaskDefinition
from backend.tasks.filtering import filter_tasks_by_agents


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  setup_database()


@pytest.fixture
def test_user_id():
  admin = get_user_by_username("admin")
  assert admin is not None
  return admin.id


@pytest.fixture(autouse=True)
def cleanup_custom_agents(test_user_id):
  registry = get_agent_registry(test_user_id)
  for aid in list(registry.keys()):
    if not is_builtin(aid):
      try:
        delete_custom_agent(aid, test_user_id)
      except ValueError:
        pass
  yield
  registry = get_agent_registry(test_user_id)
  for aid in list(registry.keys()):
    if not is_builtin(aid):
      try:
        delete_custom_agent(aid, test_user_id)
      except ValueError:
        pass


class TestAgentRegistry:
  def test_builtin_agents_present(self, test_user_id):
    agents = list_agents(test_user_id)
    builtin = [a for a in agents if a["is_builtin"]]
    assert len(builtin) == 8
    assert any(a["id"] == "planner" for a in builtin)

  def test_create_and_delete_custom_agent(self, test_user_id):
    created = create_custom_agent(
      user_id=test_user_id,
      agent_id="test_analyst",
      name="测试分析师",
      title="测试职称",
      background="拥有丰富的测试经验，擅长各类测试场景分析。",
      goal="在测试中提供专业的分析输出与建议方案。",
      tools=["web_search"],
    )
    assert created["id"] == "test_analyst"
    assert created["is_builtin"] is False

    registry = get_agent_registry(test_user_id)
    assert "test_analyst" in registry

    delete_custom_agent("test_analyst", test_user_id)
    registry = get_agent_registry(test_user_id)
    assert "test_analyst" not in registry

  def test_cannot_delete_builtin(self, test_user_id):
    with pytest.raises(ValueError, match="内置角色"):
      delete_custom_agent("planner", test_user_id)


class TestTaskFiltering:
  def test_filters_tasks_by_selected_agents(self):
    tasks = [
      TaskDefinition(id="t1", name="A", description="", agent_id="planner", depends_on=[]),
      TaskDefinition(id="t2", name="B", description="", agent_id="literature_researcher", depends_on=["t1"]),
      TaskDefinition(id="t3", name="C", description="", agent_id="review_specialist", depends_on=["t2"]),
    ]
    filtered = filter_tasks_by_agents(tasks, ["planner", "review_specialist"])
    assert [t.id for t in filtered] == ["t1", "t3"]
    assert filtered[1].depends_on == []

  def test_empty_selection_returns_all(self):
    tasks = [
      TaskDefinition(id="t1", name="A", description="", agent_id="planner", depends_on=[]),
    ]
    assert filter_tasks_by_agents(tasks, []) == tasks
