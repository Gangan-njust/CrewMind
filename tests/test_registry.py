"""run_agent_tools 工具调度逻辑"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.agents.roles import (
  EXPERIMENT_DESIGNER,
  LITERATURE_RESEARCHER,
  PLANNER,
  RESOURCE_ANALYST,
)
from backend.tools.registry import run_agent_tools


@pytest.fixture
def mock_tools():
  """替换 TOOL_REGISTRY 为可控 mock，隔离外部 HTTP"""
  file_parser = AsyncMock()
  file_parser.run_for_files = AsyncMock(return_value="### 文件: notes.md\n\n参考内容")

  web_search = AsyncMock()
  web_search.run = AsyncMock(return_value='[{"title": "Mock Paper", "source": "Test"}]')

  code_interpreter = AsyncMock()
  code_interpreter.run_for_experiment_context = AsyncMock(
    return_value="检测到人数相关描述: 100 人"
  )

  registry = {
    "file_parser": file_parser,
    "web_search": web_search,
    "code_interpreter": code_interpreter,
  }

  with patch("backend.tools.registry.TOOL_REGISTRY", registry):
    yield registry


class TestRunAgentToolsDispatch:
  @pytest.mark.asyncio
  async def test_planner_runs_file_parser_only(self, mock_tools, tmp_path):
    ref_file = tmp_path / "ref.md"
    ref_file.write_text("notes", encoding="utf-8")

    messages = await run_agent_tools(
      PLANNER,
      task_prompt="规划课题",
      user_input="研究深度学习医学影像",
      context_outputs={},
      reference_files=[str(ref_file)],
      partial_output="",
    )

    mock_tools["file_parser"].run_for_files.assert_awaited_once()
    mock_tools["web_search"].run.assert_not_called()
    mock_tools["code_interpreter"].run_for_experiment_context.assert_not_called()
    assert len(messages) == 1
    assert "参考文件内容" in messages[0]["content"]

  @pytest.mark.asyncio
  async def test_literature_researcher_runs_search_and_file_parser(self, mock_tools, tmp_path):
    ref_file = tmp_path / "ref.md"
    ref_file.write_text("notes", encoding="utf-8")

    messages = await run_agent_tools(
      LITERATURE_RESEARCHER,
      task_prompt="撰写文献综述",
      user_input="研究深度学习在医学影像诊断中的应用",
      context_outputs={"task_planning": "规划输出"},
      reference_files=[str(ref_file)],
      partial_output="",
    )

    mock_tools["file_parser"].run_for_files.assert_awaited_once()
    mock_tools["web_search"].run.assert_awaited_once()
    mock_tools["code_interpreter"].run_for_experiment_context.assert_not_called()
    assert len(messages) == 2
    assert any("学术文献检索结果" in m["content"] for m in messages)
    assert any("参考文件内容" in m["content"] for m in messages)

  @pytest.mark.asyncio
  async def test_experiment_designer_runs_code_interpreter(self, mock_tools):
    messages = await run_agent_tools(
      EXPERIMENT_DESIGNER,
      task_prompt="设计实验方案",
      user_input="随机对照实验，样本 100 人",
      context_outputs={"task_planning": "已有规划"},
      reference_files=[],
      partial_output="",
    )

    mock_tools["code_interpreter"].run_for_experiment_context.assert_awaited_once()
    mock_tools["web_search"].run.assert_not_called()
    mock_tools["file_parser"].run_for_files.assert_not_called()
    assert len(messages) == 1
    assert "实验参数计算结果" in messages[0]["content"]

  @pytest.mark.asyncio
  async def test_agent_without_tools_returns_empty(self, mock_tools):
    messages = await run_agent_tools(
      RESOURCE_ANALYST,
      task_prompt="编制预算",
      user_input="预算分析",
      context_outputs={},
      reference_files=["/any/path.md"],
      partial_output="",
    )

    mock_tools["file_parser"].run_for_files.assert_not_called()
    mock_tools["web_search"].run.assert_not_called()
    mock_tools["code_interpreter"].run_for_experiment_context.assert_not_called()
    assert messages == []

  @pytest.mark.asyncio
  async def test_partial_output_skips_all_tools(self, mock_tools, tmp_path):
    ref_file = tmp_path / "ref.md"
    ref_file.write_text("notes", encoding="utf-8")

    messages = await run_agent_tools(
      LITERATURE_RESEARCHER,
      task_prompt="续写综述",
      user_input="研究课题",
      context_outputs={},
      reference_files=[str(ref_file)],
      partial_output="已有部分内容...",
    )

    mock_tools["file_parser"].run_for_files.assert_not_called()
    mock_tools["web_search"].run.assert_not_called()
    assert messages == []

  @pytest.mark.asyncio
  async def test_emits_tool_events(self, mock_tools):
    events: list[tuple[str, str, str]] = []

    async def on_event(tool: str, status: str, detail: str) -> None:
      events.append((tool, status, detail))

    await run_agent_tools(
      EXPERIMENT_DESIGNER,
      task_prompt="设计实验",
      user_input="样本 80 人",
      context_outputs={},
      reference_files=[],
      partial_output="",
      on_tool_event=on_event,
    )

    assert ("code_interpreter", "started", "样本量与预算估算") in events
    assert ("code_interpreter", "completed", "计算完成") in events

  @pytest.mark.asyncio
  async def test_file_parser_failure_emits_failed_event(self, mock_tools):
    mock_tools["file_parser"].run_for_files = AsyncMock(side_effect=RuntimeError("parse error"))
    events: list[tuple[str, str, str]] = []

    async def on_event(tool: str, status: str, detail: str) -> None:
      events.append((tool, status, detail))

    messages = await run_agent_tools(
      PLANNER,
      task_prompt="规划",
      user_input="研究需求描述足够长",
      context_outputs={},
      reference_files=["/tmp/ref.md"],
      partial_output="",
      on_tool_event=on_event,
    )

    assert ("file_parser", "failed", "parse error") in events
    assert messages == []

  @pytest.mark.asyncio
  async def test_no_reference_files_skips_file_parser(self, mock_tools):
    await run_agent_tools(
      PLANNER,
      task_prompt="规划",
      user_input="研究深度学习",
      context_outputs={},
      reference_files=[],
      partial_output="",
    )
    mock_tools["file_parser"].run_for_files.assert_not_called()
