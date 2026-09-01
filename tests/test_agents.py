"""Agent 注册表与任务过滤测试"""
import pytest

from backend.agents.registry import (
  create_custom_agent,
  delete_custom_agent,
  get_agent_registry,
  is_builtin,
  list_agents,
)
from backend.agents import extractor
from backend.agents.prompt_parser import normalize_pasted_prompt, parse_markdown_agent_prompt
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


class TestAgentExtractor:
  @pytest.mark.asyncio
  async def test_extract_agent_from_freeform_prompt(self, monkeypatch):
    async def fake_chat(messages, **kwargs):
      return (
        '{"name":"数据分析师","title":"统计分析与数据挖掘专家",'
        '"background":"熟悉 Python 与统计建模，擅长实验数据清洗与可视化。",'
        '"goal":"根据研究问题设计分析流程并输出可复现结论。",'
        '"tools":["rag_search","web_search"],"use_reasoning":false}'
      )

    monkeypatch.setattr(extractor.llm_client, "chat", fake_chat)
    result = await extractor.extract_agent_from_prompt(
      "你是一名数据分析师，负责帮课题组做统计分析和文献支撑。"
    )
    assert result["name"] == "数据分析师"
    assert result["tools"] == ["rag_search", "web_search"]
    assert result["use_reasoning"] is False

  @pytest.mark.asyncio
  async def test_reject_short_prompt(self):
    with pytest.raises(ValueError, match="过短"):
      await extractor.extract_agent_from_prompt("太短")


class TestMarkdownPromptParser:
  def test_unwrap_markdown_fence(self):
    raw = "```markdown\n# 专家\n\n## 专业背景\n背景内容足够长。\n```"
    assert normalize_pasted_prompt(raw).startswith("# 专家")

  def test_parse_markdown_sections(self):
    prompt = """# 文献调研专家

你是一位专业的学术文献调研分析师。

## 专业背景
- 精通文献检索策略
- 熟悉 Semantic Scholar 与 PubMed

## 核心目标
基于课题规划检索并分析相关文献，识别研究空白。

## 可用工具
rag_search, web_search
"""
    data = parse_markdown_agent_prompt(prompt)
    assert data["name"] == "文献调研专家"
    assert "文献检索" in data["background"]
    assert "研究空白" in data["goal"]
    assert data["tools"] == ["rag_search", "web_search"]

  @pytest.mark.asyncio
  async def test_extract_merges_markdown_with_llm(self, monkeypatch):
    markdown_prompt = """# 测试角色

## 专业背景
这是 Markdown 背景描述，包含足够的信息用于测试。

## 核心目标
这是 Markdown 目标描述，说明角色的职责与输出要求。
"""

    async def fake_chat(messages, **kwargs):
      return (
        '{"name":"LLM名称","title":"LLM职称",'
        '"background":"短背景","goal":"短目标","tools":["web_search"],"use_reasoning":false}'
      )

    monkeypatch.setattr(extractor.llm_client, "chat", fake_chat)
    result = await extractor.extract_agent_from_prompt(markdown_prompt)
    assert "Markdown 背景" in result["background"]
    assert "Markdown 目标" in result["goal"]
    assert result["tools"] == ["web_search"]
