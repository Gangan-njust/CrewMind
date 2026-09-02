"""学术写作图表缺失提醒：基于规则的启发式检测。

用于在写作全流程中定位"按学术规范应配图表、但正文缺失"的位置，
防止通篇只有文字。规则检测是 LLM 语义检查的前置候选源与降级兜底，
全部函数保持纯函数、无 IO，便于单元测试。

检测约定：
- 段落（连续非空行组成的块）为单位，每段最多输出一条提醒，锚点为段内信号最强的行；
- 摘要类章节（abstract / abstract_en）不提醒；
- 已含图片/表格的章节对弱信号降噪，避免打扰；
- 输出字段与现有 check 检查保持兼容（severity / description 语义对齐前端卡片）。
"""
import re

from backend.writing.templates import SECTION_LABELS, is_abstract_section

# ── 文本特征正则 ──────────────────────────────────────────────

_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_TABLE_SEPARATOR_RE = re.compile(
  r"(?m)^[ \t]*\|?[ \t]*:?-{1,}:?[ \t]*(?:\|[ \t]*:?-{1,}:?[ \t]*)+[ \t]*\|?[ \t]*$"
)
_PLACEHOLDER_RE = re.compile(r"<!--[ \t]*figure(?::|\s|--)", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s")
_CODE_FENCE_RE = re.compile(r"^[ \t]*```")

# 正文引用了"图/表 + 编号 + 所示"但对应视觉元素缺失（最强信号）
_FIG_MENTION_RE = re.compile(
  r"(?:如图|见图|由图|如(?:下)?图)[ \t]*[0-9一二三四五六七八九十]*[ \t]*所示?"
  r"|(?:图)[ \t]*[0-9一二三四五六七八九十]+[ \t]*所示"
)
_TABLE_MENTION_RE = re.compile(
  r"(?:如表|见表|由表|如(?:下)?表)[ \t]*[0-9一二三四五六七八九十]*[ \t]*所示?"
  r"|(?:表)[ \t]*[0-9一二三四五六七八九十]+[ \t]*所示"
)

# 定量数据令牌：百分比 / 带单位数值 / 均值±误差
_DATA_TOKEN_RE = re.compile(
  r"\d+(?:\.\d+)?\s*%"
  r"|\d+(?:\.\d+)?\s*[±]\s*\d+(?:\.\d+)?"
  r"|\d+(?:\.\d+)?\s*(?:ms|MB|GB|KB|TB|FPS|Hz|kHz|dB|nm|μm|um|mm|cm|m|kg|mg|mL|ml|mol|epoch|step)s?"
)

_COMPARE_WORDS = (
  "相比", "相较于", "相对于", "对比", "优于", "高于", "低于",
  "显著提升", "显著提高", "显著降低", "显著减少", "下降", "提升", "高出",
  "超过", "最好", "最佳", "领先",
)
_FLOW_WORDS = (
  "流程", "步骤", "处理流程", "算法流程", "工作流", "pipeline",
  "总体流程", "分为以下", "实施流程", "技术路线",
)
_STRUCT_WORDS = (
  "整体框架", "总体框架", "系统框架", "算法框架", "模型框架", "技术框架",
  "网络结构", "系统结构", "整体结构", "层次结构", "组成结构", "框架结构",
  "总体设计", "系统架构", "整体架构", "模块组成", "系统组成", "模块划分",
)
_TREND_WORDS = (
  "收敛", "训练过程", "迭代", "epoch", "step", "学习曲线", "损失曲线",
  "训练损失", "验证损失", "随迭代", "随步数",
)
_STATS_WORDS = (
  "p<", "p值", "p 值", "显著性", "t检验", "T检验", "方差分析", "ANOVA",
  "置信区间", "统计检验", "标准差",
)
_RESULT_WORDS = (
  "实验结果表明", "结果表明", "实验发现", "结果显示", "实验验证",
  "测试结果表明", "验证了",
)
# 图类型 → 通用建议文案
_SUGGESTIONS = {
  "柱状图": "建议插入柱状图对比各组/各方法数值，并补充误差棒与显著性标注（如 *、**），图注说明样本量。",
  "折线图": "建议以折线图展示数据随自变量（如迭代轮数）的变化趋势，横纵轴标注单位。",
  "箱线图": "建议用箱线图展示组间分布、中位数与离群点，图注说明分组与样本量。",
  "流程图": "建议绘制流程图/泳道图清晰展示方法步骤与数据流向，图中标注关键环节。",
  "结构图": "建议用框图示意模块结构与数据流，帮助读者理解整体设计。",
  "表格": "建议将关键数据整理为三线表，表注说明单位、样本量与统计方法。",
  "图表": "建议补充示意图/统计图并配上图编号（图1…）与图注；如需对照文献请注明来源。",
}

# 信号等级：rank 越高越值得提醒；章节已有视觉元素时忽略 rank<70 的弱信号
_RANK_REF = 100
_RANK_COMPARE = 90
_RANK_TREND = 75
_RANK_STATS = 70
_RANK_FLOW = 60
_RANK_STRUCT = 60
_RANK_NUMERIC = 45
_RANK_RESULT = 30


def count_figures(content: str) -> int:
  """统计 Markdown 图片数量（含 cmasset 引用与待插入占位）。"""
  if not content:
    return 0
  return len(_IMAGE_MD_RE.findall(content))


def count_tables(content: str) -> int:
  """统计 GFM 表格数量（以分隔行 |---| 计数）。"""
  if not content:
    return 0
  return len(_TABLE_SEPARATOR_RE.findall(content))


def count_placeholders(content: str) -> int:
  """统计 figure 占位注释数量。"""
  if not content:
    return 0
  return len(_PLACEHOLDER_RE.findall(content))


def has_visual_element(content: str) -> bool:
  return count_figures(content) > 0 or count_tables(content) > 0 or count_placeholders(content) > 0


def _truncate_anchor(text: str, max_len: int = 120) -> str:
  text = re.sub(r"\s+", " ", text.strip())
  return text[:max_len] + ("…" if len(text) > max_len else "")


def _line_has(line: str, words) -> bool:
  lowered = line.lower()
  for word in words:
    if word in lowered:
      return True
  return False


def _classify_line(line: str) -> tuple[str, str, str, int] | None:
  """返回 (chart_type, reason, severity, rank)；无法判定时返回 None。"""
  has_data = _DATA_TOKEN_RE.search(line)
  if has_data and _line_has(line, _COMPARE_WORDS):
    return (
      "柱状图",
      "段落包含定量数据与对比结论，建议配对比图增强表达",
      "high", _RANK_COMPARE,
    )
  if _line_has(line, _TREND_WORDS) and (has_data or _line_has(line, _RESULT_WORDS)):
    return (
      "折线图",
      "段落描述指标随过程的变化趋势，建议以折线图展示",
      "medium", _RANK_TREND,
    )
  if _line_has(line, _STATS_WORDS) and has_data:
    return (
      "箱线图",
      "段落报告统计量/显著性结果，建议以箱线图或统计图呈现组间分布",
      "medium", _RANK_STATS,
    )
  if has_data and _line_has(line, _RESULT_WORDS):
    return (
      "柱状图",
      "段落给出结果数值，建议配图/表更直观地呈现数据",
      "medium", _RANK_NUMERIC,
    )
  if _line_has(line, _FLOW_WORDS):
    return (
      "流程图",
      "段落描述方法步骤/流程，建议绘制流程图辅助说明",
      "medium", _RANK_FLOW,
    )
  if _line_has(line, _STRUCT_WORDS):
    return (
      "结构图",
      "段落介绍系统/方法框架结构，建议配结构示意图",
      "medium", _RANK_STRUCT,
    )
  if _line_has(line, _RESULT_WORDS):
    return (
      "图表",
      "段落给出结果性陈述，建议就近补充图表数据支撑",
      "medium", _RANK_RESULT,
    )
  return None


def _detect_block_issue(
  block_lines: list[tuple[int, str]],
  has_figure: bool,
  has_table: bool,
  section: dict,
) -> dict | None:
  """在单个段落块中寻找最强信号，输出一条 issue。"""
  candidates: list[tuple[int, str, str, str, str, int]] = []
  for line_no, raw in block_lines:
    line = raw.strip()
    if not line or _HEADING_RE.match(line):
      continue

    # 引用图/表却缺失（按被引用的对象区分是否真正缺失）
    if _FIG_MENTION_RE.search(line) and not has_figure:
      candidates.append((
        line_no, line,
        "图表", "正文引用了图，但该章节未检测到任何图片",
        "high", _RANK_REF,
      ))
      continue
    if _TABLE_MENTION_RE.search(line) and not has_table:
      candidates.append((
        line_no, line,
        "表格", "正文引用了表，但该章节未检测到任何表格",
        "high", _RANK_REF,
      ))
      continue

    result = _classify_line(line)
    if result:
      chart_type, reason, severity, rank = result
      # 章节已含图/表时，仅保留"显式引用却缺失"的强提醒，避免反复打扰
      if (has_figure or has_table) and rank < _RANK_REF:
        continue
      candidates.append((line_no, line, chart_type, reason, severity, rank))

  if not candidates:
    return None
  # 取 rank 最高者；同 rank 取靠前行
  candidates.sort(key=lambda c: (-c[5], c[0]))
  line_no, anchor, chart_type, reason, severity, _ = candidates[0]
  return {
    "section_id": section.get("id", ""),
    "section_type": section.get("section_type", ""),
    "display_title": section.get("display_title", section.get("title", ""))
    or SECTION_LABELS.get(section.get("section_type", ""), ""),
    "line": line_no + 1,  # 转为 1 基行号
    "anchor_text": _truncate_anchor(anchor),
    "chart_type": chart_type,
    "reason": reason,
    "suggestion": _SUGGESTIONS.get(chart_type, _SUGGESTIONS["图表"]),
    "severity": severity,
  }


def detect_section_figure_hints(section: dict, *, max_issues: int = 4) -> list[dict]:
  """对单个章节做规则检测，返回图表缺失提醒列表。

  section 需包含 content / section_type；id、title 可选。
  仅处理非摘要章节；章节内容为空时返回 []。
  """
  content = (section.get("content") or "").strip()
  if not content or is_abstract_section(section.get("section_type", "")):
    return []

  has_figure = count_figures(content) > 0
  has_table = count_tables(content) > 0

  # 将正文按空行切为段落块，保留每行原始行号（0 基）
  blocks: list[list[tuple[int, str]]] = []
  current: list[tuple[int, str]] = []
  in_fence = False
  for idx, raw in enumerate(content.split("\n")):
    if _CODE_FENCE_RE.match(raw):
      in_fence = not in_fence
    stripped = raw.strip()
    if not stripped and not in_fence:
      if current:
        blocks.append(current)
        current = []
      continue
    current.append((idx, raw))
  if current:
    blocks.append(current)

  issues: list[dict] = []
  for block in blocks:
    issue = _detect_block_issue(block, has_figure, has_table, section)
    if issue:
      issue["key"] = f"{issue['section_id']}:{issue['line']}:{issue['chart_type']}"
      issues.append(issue)
    if len(issues) >= max_issues:
      break
  return issues


def scan_project_figure_hints(project: dict) -> dict:
  """扫描整个写作项目，返回 {issues, figure_count, table_count, section_count, summary}。"""
  sections = sorted(
    project.get("sections", []),
    key=lambda s: (s.get("sort_order", 0) if s.get("sort_order") is not None else 999,),
  )
  issues: list[dict] = []
  figure_total = 0
  table_total = 0
  for sec in sections:
    content = sec.get("content") or ""
    figure_total += count_figures(content)
    table_total += count_tables(content)
    issues.extend(detect_section_figure_hints(sec))

  issue_count = len(issues)
  if issue_count:
    summary = (
      f"全文共 {len(sections)} 章，已含 {figure_total} 张图、{table_total} 张表；"
      f"发现 {issue_count} 处建议配图位置。"
    )
  else:
    summary = (
      f"未发现明显缺图表的位置；全文已含 {figure_total} 张图、{table_total} 张表。"
    )
  return {
    "issues": issues,
    "figure_count": figure_total,
    "table_count": table_total,
    "section_count": len(sections),
    "summary": summary,
  }


def detect_text_figure_hints(text: str, section_type: str = "intro") -> dict:
  """对单段文本做规则检测（用于前端实时/保存后轻量检查）。"""
  section = {
    "id": "",
    "section_type": section_type,
    "title": SECTION_LABELS.get(section_type, ""),
    "content": text,
  }
  issues = detect_section_figure_hints(section)
  return {
    "issues": issues,
    "figure_count": count_figures(text),
    "table_count": count_tables(text),
    "summary": f"当前章节发现 {len(issues)} 处建议配图位置。",
  }
