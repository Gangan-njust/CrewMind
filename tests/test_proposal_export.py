"""开题报告 / 纯综述·纯文章导出提取逻辑"""
from backend.storage.results import (
  extract_proposal_output,
  extract_pure_output,
  PROPOSAL_TASK_ID,
)


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


REVIEW_INTEGRATED_TASK = """# 综述终审报告

## 1 质量评估（8/10分）
综述整体质量较好。

## 2 主要优点
- 结构完整

## 3 存在问题
- 个别小节引用可更充分

## 4 改进建议
- 补充近三年文献

## 5 完整文献综述（整合版）

# 文献综述

## 1 引言
综述背景与意义...

## 2 文献检索与筛选说明
使用 PubMed 与 CNKI，限定近十年...

## 3 国内外研究现状
按主题维度综述：方法一、方法二、方法三...

## 4 主要研究方法与技术对比
对比了各方法的优劣。

## 5 现有研究存在的问题与争论
存在数据集不统一等问题。

## 6 研究空白与未来展望
展望...

## 7 结论
综上，...

## 8 参考文献
[1] Smith. Deep Learning Survey. 2023.
"""


def test_extract_pure_review_from_integrated_section():
  tasks = {PROPOSAL_TASK_ID: {"output": REVIEW_INTEGRATED_TASK, "status": "completed"}}
  result = extract_pure_output(tasks, "literature_based_review")
  assert result is not None
  # 不含审稿过程
  assert "质量评估" not in result
  assert "主要优点" not in result
  assert "改进建议" not in result
  # 不含检索/筛选等过程性章节
  assert "检索与筛选说明" not in result
  assert "检索" not in result
  # 保留综述正文
  assert "引言" in result
  assert "国内外研究现状" in result
  assert "参考文献" in result
  assert "[1]" in result


def test_extract_pure_review_uses_direct_doc():
  doc = "# 文献综述\n\n## 1 引言\n背景\n\n## 2 检索策略\n数据库检索词说明\n\n## 3 结论\n结语"
  tasks = {PROPOSAL_TASK_ID: {"output": doc, "status": "completed"}}
  result = extract_pure_output(tasks, "literature_based_review")
  assert result is not None
  assert "引言" in result
  assert "结论" in result
  assert "检索策略" not in result


def test_extract_pure_review_falls_back_to_literature_task():
  tasks = {
    "task_planning": {"output": "# 综述框架规划\n\n过程内容", "status": "completed"},
    "task_literature": {
      "output": "# 文献综述\n\n## 1 引言\n正文\n\n## 2 检索策略\n过程\n\n## 3 结论\n结语",
      "status": "completed",
    },
  }
  result = extract_pure_output(tasks, "literature_based_review")
  assert result is not None
  assert "引言" in result
  assert "正文" in result
  assert "检索策略" not in result


def test_extract_pure_review_removes_database_section():
  doc = (
    "# 文献综述\n\n## 1 引言\n背景\n\n"
    "## 2 文献检索与筛选说明\n检索过程\n\n## 3 国内外研究现状\n现状\n\n"
    "## 9 文献数据库说明\nSemantic Scholar / PubMed\n"
  )
  result = extract_pure_output({"task_literature": {"output": doc}}, "literature_review")
  assert result is not None
  assert "文献检索与筛选说明" not in result
  assert "文献数据库说明" not in result
  assert "国内外研究现状" in result


def test_extract_pure_for_proposal_matches_proposal_scope():
  tasks = {PROPOSAL_TASK_ID: {"output": REVIEW_OUTPUT, "status": "completed"}}
  assert extract_pure_output(tasks, "literature_based_proposal") == extract_proposal_output(
    tasks, "literature_based_proposal"
  )


def test_build_pure_markdown_from_workflow_omits_process():
  from backend.storage.results import result_store

  results = {
    "task_planning": {"output": "# 综述框架规划\n\n框架过程内容", "status": "completed"},
    "task_literature": {
      "output": "# 文献综述\n\n## 1 引言\n正文内容\n\n## 2 检索策略\n检索过程\n\n## 3 结论\n结语",
      "status": "completed",
    },
  }
  md = result_store.build_pure_markdown_from_workflow(
    "literature_based_review", "深度学习综述", results
  )
  assert "检索策略" not in md
  assert "正文内容" in md
  assert "结语" in md


def test_build_pure_latex_from_workflow():
  from backend.storage.results import result_store

  results = {
    "task_literature": {
      "output": "# 文献综述\n\n## 1 引言\n正文\n\n## 2 文献数据库说明\n来源",
      "status": "completed",
    },
  }
  tex = result_store.build_pure_latex_from_workflow(
    "literature_based_review", "主题", results, title="纯综述测试"
  )
  assert "\\begin{document}" in tex
  assert "纯综述测试" in tex
  assert "数据库说明" not in tex
