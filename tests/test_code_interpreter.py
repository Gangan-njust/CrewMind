"""code_interpreter 沙箱与实验参数分析"""
from __future__ import annotations

import pytest

from backend.tools.code_interpreter import CodeInterpreterTool


class TestCodeInterpreterSandbox:
  @pytest.mark.asyncio
  async def test_executes_safe_code_and_returns_result(self):
    code = "result = sum([1, 2, 3])"
    output = await CodeInterpreterTool().run(code=code)
    assert output == "6"

  @pytest.mark.asyncio
  async def test_allows_math_and_statistics(self):
    code = "result = round(statistics.mean([1, 2, 3, 4]), 2)"
    output = await CodeInterpreterTool().run(code=code)
    assert output == "2.5"

  @pytest.mark.asyncio
  async def test_context_vars_available_in_sandbox(self):
    code = "result = context_text.upper()"
    output = await CodeInterpreterTool().run(
      code=code,
      context_vars={"context_text": "hello"},
    )
    assert output == "HELLO"

  @pytest.mark.asyncio
  async def test_blocks_unsafe_import(self):
    code = "import os\nresult = os.getcwd()"
    output = await CodeInterpreterTool().run(code=code)
    assert output.startswith("代码执行错误:")

  @pytest.mark.asyncio
  async def test_blocks_builtins_abuse(self):
    code = "result = __import__('subprocess').getoutput('echo pwned')"
    output = await CodeInterpreterTool().run(code=code)
    assert output.startswith("代码执行错误:")

  @pytest.mark.asyncio
  async def test_no_result_variable_returns_notice(self):
    output = await CodeInterpreterTool().run(code="x = 1 + 1")
    assert "未定义 result" in output

  @pytest.mark.asyncio
  async def test_empty_code_returns_error(self):
    output = await CodeInterpreterTool().run(code="")
    assert "错误" in output


class TestExperimentContextAnalysis:
  @pytest.mark.asyncio
  async def test_extracts_sample_size_budget_and_duration(self):
    user_input = "计划招募 120 人参与随机对照实验，预算约 50 万，周期 18 个月。"
    output = await CodeInterpreterTool().run_for_experiment_context(user_input, {})

    assert "120 人" in output
    assert "50.0 万元" in output
    assert "18 个月" in output
    assert "每组约 60 人" in output
    assert "功效分析" in output

  @pytest.mark.asyncio
  async def test_warns_when_sample_per_group_too_small(self):
    user_input = "样本量约 40 人，分为两组。"
    output = await CodeInterpreterTool().run_for_experiment_context(user_input, {})
    assert "少于 30 人" in output

  @pytest.mark.asyncio
  async def test_merges_task_context_into_analysis(self):
    user_input = "研究深度学习诊断。"
    task_context = {"task_planning": "预计受试者 200 人，预算 80 万。"}
    output = await CodeInterpreterTool().run_for_experiment_context(user_input, task_context)
    assert "200 人" in output
    assert "80.0 万元" in output

  @pytest.mark.asyncio
  async def test_no_numeric_params_returns_fallback_message(self):
    output = await CodeInterpreterTool().run_for_experiment_context(
      "纯理论综述，无实验参数。",
      {},
    )
    assert "未从文本中提取" in output
