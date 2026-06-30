"""开题报告导出提取逻辑"""
from backend.storage.results import extract_proposal_output, PROPOSAL_TASK_ID


REVIEW_OUTPUT = """# 终审报告

## 1. 质量评估（8/10分）
整体方案质量较好。

## 2. 主要优点
- 目标明确
- 方法可行

## 3. 存在问题
- 样本量需补充说明

## 4. 改进建议
- 增加对照组设计

## 5. 完整工作方案（整合版）

# 开题报告（完整版）

## 1. 研究背景
基于文献 A 的研究背景...

## 2. 研究方法
采用实验对照设计...
"""

PLANNING = "# 开题报告 · 课题规划\n\n## 1. 研究背景\n规划内容"
LITERATURE = "# 文献整合报告\n\n## 1. 用户文献库综述\n文献内容"
EXPERIMENT = "# 研究方法设计\n\n## 1. 方法\n实验方案"


def test_extract_proposal_from_review_integrated_section():
  tasks = {PROPOSAL_TASK_ID: {"output": REVIEW_OUTPUT, "status": "completed"}}
  result = extract_proposal_output(tasks, "literature_based_proposal")
  assert result is not None
  assert "质量评估" not in result
  assert "主要优点" not in result
  assert "研究背景" in result
  assert "研究方法" in result


def test_extract_proposal_uses_full_review_when_already_proposal():
  tasks = {
    PROPOSAL_TASK_ID: {
      "output": "# 开题报告（完整版）\n\n## 1. 研究背景\n正文",
      "status": "completed",
    },
  }
  assert extract_proposal_output(tasks, "literature_based_proposal") == (
    "# 开题报告（完整版）\n\n## 1. 研究背景\n正文"
  )


def test_extract_proposal_composes_when_review_is_opinion_only():
  tasks = {
    "task_planning": {"output": PLANNING, "status": "completed"},
    "task_literature": {"output": LITERATURE, "status": "completed"},
    "task_experiment": {"output": EXPERIMENT, "status": "completed"},
    PROPOSAL_TASK_ID: {
      "output": "# 终审报告\n\n## 1. 质量评估\n8分\n\n## 2. 主要优点\n很好",
      "status": "completed",
    },
  }
  order = ["task_planning", "task_literature", "task_experiment", PROPOSAL_TASK_ID]
  result = extract_proposal_output(tasks, "literature_based_proposal", order)
  assert result is not None
  assert "质量评估" not in result
  assert PLANNING in result
  assert LITERATURE in result
  assert EXPERIMENT in result


def test_extract_proposal_composes_without_review_specialist():
  tasks = {
    "task_planning": {"output": PLANNING, "status": "completed"},
    "task_experiment": {"output": EXPERIMENT, "status": "completed"},
  }
  order = ["task_planning", "task_experiment"]
  result = extract_proposal_output(tasks, "literature_based_proposal", order)
  assert result == f"{PLANNING}\n\n---\n\n{EXPERIMENT}"


def test_extract_proposal_skips_domain_review_tasks():
  tasks = {
    "task_planning": {"output": PLANNING, "status": "completed"},
    "task_cs_review": {"output": "# 计算机学科评审\n\n拒稿", "status": "completed"},
  }
  order = ["task_planning", "task_cs_review"]
  result = extract_proposal_output(tasks, "literature_based_proposal", order)
  assert result == PLANNING


def test_extract_proposal_returns_none_when_empty():
  tasks = {"task_planning": {"output": "", "status": "completed"}}
  assert extract_proposal_output(tasks, "literature_based_proposal") is None
