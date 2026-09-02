"""图表完整性 LLM 检查函数单测（mock LLM，不联网）。"""
import pytest

import backend.writing.assistant as assistant


def _section(section_type: str, content: str, title: str = "") -> dict:
  return {
    "id": f"sec-{section_type}",
    "section_type": section_type,
    "title": title,
    "content": content,
    "sort_order": 0,
    "display_title": title or section_type,
  }


def _project():
  return {
    "sections": [
      _section("results", "实验结果表明，本文方法准确率达 95.2%，相比基线提升 12.3 个百分点。", "结果"),
      _section("methods", "算法流程分为数据清洗、特征提取、模型训练三个步骤。", "方法"),
    ],
  }


def test_normalize_chart_and_severity_fallbacks():
  assert assistant._normalize_chart_type("柱状图") == "柱状图"
  assert assistant._normalize_chart_type("不明类型") == "图表"
  assert assistant._normalize_severity("HIGH") == "high"
  assert assistant._normalize_severity("未知") == "medium"


def test_find_line_for_anchor_ignores_whitespace():
  content = "第一行内容。\n\n实验结果表明 准确率 达 98 % ，相比基线提升。"
  # 锚点句内部空白可能与原文不完全一致，应仍能定位
  line = assistant._find_line_for_anchor(content, "实验结果表明准确率达98%，相比基线提升。")
  assert line == 3


def test_normalize_llm_issues_drops_unlocatable():
  issues = assistant._normalize_llm_issues(
    _project(),
    [
      {
        "section_type": "results",
        "anchor_text": "实验结果表明，本文方法准确率达 95.2%，相比基线提升 12.3 个百分点。",
        "chart_type": "柱状图",
        "reason": "对比数据",
        "suggestion": "配图",
        "severity": "high",
      },
      {"section_type": "results", "anchor_text": "正文中根本不存在的句子。", "chart_type": "柱状图"},
    ],
  )
  assert len(issues) == 1
  assert issues[0]["section_id"] == "sec-results"
  assert issues[0]["line"] == 1
  assert issues[0]["key"].startswith("sec-results:1:")


async def test_check_figures_rule_fallback_when_llm_fails(monkeypatch):
  async def boom(prompt, temperature=0.3):
    raise RuntimeError("network down")

  monkeypatch.setattr(assistant, "_llm_json", boom)
  report = await assistant.check_figures(_project())
  assert report["used_llm"] is False
  assert report["issues"]  # 规则结果兜底
  assert report["summary"]


async def test_check_figures_merges_llm_and_rule(monkeypatch):
  llm_anchor = "算法流程分为数据清洗、特征提取、模型训练三个步骤。"

  async def fake_llm_json(prompt, temperature=0.3):
    return {
      "issues": [
        {
          "section_type": "methods",
          "anchor_text": llm_anchor,
          "chart_type": "流程图",
          "reason": "方法流程建议配流程图",
          "suggestion": "绘制流程图",
          "severity": "medium",
        }
      ],
      "summary": "LLM 检查完成",
    }

  monkeypatch.setattr(assistant, "_llm_json", fake_llm_json)
  report = await assistant.check_figures(_project())
  assert report["used_llm"] is True
  types = {i["section_type"] for i in report["issues"]}
  assert "methods" in types and "results" in types  # LLM methods + 规则 results 合并
  llm_items = [i for i in report["issues"] if i["section_type"] == "methods"]
  assert llm_items and llm_items[0]["chart_type"] == "流程图"
