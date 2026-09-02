"""图表缺失规则检测器单测。"""
import pytest

from backend.writing.figure_hints import (
  count_figures,
  count_tables,
  detect_section_figure_hints,
  detect_text_figure_hints,
  has_visual_element,
  scan_project_figure_hints,
)


def _section(section_type: str = "results", content: str = "", title: str = "") -> dict:
  return {
    "id": f"sec-{section_type}",
    "section_type": section_type,
    "title": title,
    "content": content,
    "sort_order": 0,
  }


class TestCounting:
  def test_count_figures_markdown_images(self):
    content = "![图1](/a.png)\n\n正文\n\n![图2](/b.png)"
    assert count_figures(content) == 2

  def test_count_figures_placeholder_and_cmasset(self):
    content = "![图：待插入](待插入图表)\n\n![图](cmasset://abc)"
    assert count_figures(content) == 2

  def test_count_tables(self):
    content = (
      "| 方法 | 准确率 |\n"
      "| --- | --- |\n"
      "| A | 90% |\n\n"
      "| 模型 | 参数量 |\n"
      "| --- | --- |"
    )
    assert count_tables(content) == 2

  def test_has_visual_element(self):
    assert not has_visual_element("纯文字段落。")
    assert has_visual_element("![x](/a.png)")
    assert has_visual_element("| a | b |\n| --- | --- |")
    assert has_visual_element("<!-- figure: 建议插柱状图 -->")


class TestDetectText:
  def test_empty_input(self):
    assert detect_text_figure_hints("")["issues"] == []

  def test_abstract_never_detected(self):
    result = detect_text_figure_hints(
      "本文提出了一个方法，实验结果表明准确率提升 12.3%，相比基线显著提升。",
      section_type="abstract",
    )
    assert result["issues"] == []

  def test_plain_text_no_hits(self):
    result = detect_text_figure_hints(
      "本章介绍研究背景与相关概念，并说明本文的组织结构。", section_type="intro"
    )
    assert result["issues"] == []

  def test_compare_data_highlights_bar_chart(self):
    result = detect_text_figure_hints(
      "实验结果表明，本文方法准确率达 95.2%，相比基线方法提升 12.3 个百分点。",
      section_type="results",
    )
    assert len(result["issues"]) == 1
    issue = result["issues"][0]
    assert issue["chart_type"] == "柱状图"
    assert issue["severity"] == "high"
    assert issue["line"] == 1
    assert "准确率" in issue["anchor_text"]

  def test_missing_figure_reference_high_severity(self):
    result = detect_text_figure_hints(
      "各方法对比如图 1 所示，可以看出本文方法明显占优。",
      section_type="results",
    )
    assert len(result["issues"]) == 1
    issue = result["issues"][0]
    assert issue["chart_type"] == "图表"
    assert issue["severity"] == "high"
    assert "引用了图" in issue["reason"]

  def test_missing_table_reference(self):
    result = detect_text_figure_hints(
      "实验设置的详细参数如表 2 所示。",
      section_type="methods",
    )
    assert result["issues"][0]["chart_type"] == "表格"

  def test_flow_sentence_suggests_flowchart(self):
    result = detect_text_figure_hints(
      "算法流程分为以下五个步骤，首先对数据进行预处理，然后进入特征提取阶段。",
      section_type="methods",
    )
    assert len(result["issues"]) == 1
    assert result["issues"][0]["chart_type"] == "流程图"

  def test_section_with_figure_suppresses_weak_signal(self):
    content = (
      "实验结果表明，本文方法准确率达 95.2%，相比基线方法提升 12.3%。\n\n"
      "![实验对比](img/fig1.png)"
    )
    result = detect_section_figure_hints(_section("results", content))
    # 章节已有图：弱信号被抑制，仅显式引用类强信号可保留
    assert result == []


class TestScanProject:
  def _project(self):
    return {
      "sections": [
        _section("abstract", "本文提出新方法，结果提升 10%，请勿提醒摘要。", "摘要"),
        _section(
          "results",
          "实验结果表明，本文方法准确率达 95.2%，相比基线提升 12.3%。\n\n"
          "此外在收敛性方面，模型在 50 个 epoch 内快速收敛，损失曲线平稳下降。",
          "结果",
        ),
        _section("methods", "数据处理流程包括清洗、标注与增强三个步骤。", "方法"),
      ],
    }

  def test_project_scan_reports_counts_and_issues(self):
    report = scan_project_figure_hints(self._project())
    assert report["figure_count"] == 0
    assert report["table_count"] == 0
    assert report["section_count"] == 3
    # abstract 不参与；results/methods 各产生提醒
    types = [i["section_type"] for i in report["issues"]]
    assert "abstract" not in types
    assert "results" in types
    assert len(report["issues"]) >= 2
    assert "建议配图" in report["summary"]

  def test_project_with_figures_reports_clean(self):
    project = {
      "sections": [
        _section(
          "results",
          "实验结果表明，本文方法准确率达 95.2%，相比基线提升 12.3%。\n\n"
          "![实验对比](img/fig1.png)",
          "结果",
        ),
      ],
    }
    report = scan_project_figure_hints(project)
    assert report["figure_count"] == 1
    assert report["issues"] == []


class TestDetectSection:
  def test_line_number_is_one_based(self):
    content = "第一段普通内容。\n\n第二段：实验结果表明准确率达 98%，显著高于基线。"
    issues = detect_section_figure_hints(_section("results", content))
    assert issues[0]["line"] == 3

  def test_max_issues_cap(self):
    paragraphs = "\n\n".join(
      f"第{i}段实验结果显示准确率达 9{i}%，相比基线显著提升。"
      for i in range(10)
    )
    issues = detect_section_figure_hints(_section("results", paragraphs), max_issues=3)
    assert len(issues) == 3

  def test_issue_key_stable(self):
    content = "实验结果表明准确率达 98%，相比基线显著提升。"
    issue = detect_section_figure_hints(_section("results", content))[0]
    assert issue["key"].startswith("sec-results:1:")
    assert issue["suggestion"]
