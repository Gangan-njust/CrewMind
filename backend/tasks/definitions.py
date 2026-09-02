"""步骤2：任务分解与协作流程定义"""
from dataclasses import dataclass, field
from enum import Enum

from backend.agents.citations import REFERENCE_CITATION_RULES
from backend.agents.roles import ScenarioType


class TaskStatus(str, Enum):
  PENDING = "pending"
  RUNNING = "running"
  WAITING_HUMAN = "waiting_human"
  COMPLETED = "completed"
  FAILED = "failed"
  SKIPPED = "skipped"
  SUSPENDED = "suspended"


class OutputFormat(str, Enum):
  MARKDOWN = "markdown"
  JSON = "json"
  TEMPLATE = "template"


@dataclass
class TaskDefinition:
  """子任务定义"""
  id: str
  name: str
  description: str
  agent_id: str
  output_format: OutputFormat = OutputFormat.MARKDOWN
  depends_on: list[str] = field(default_factory=list)
  requires_human_review: bool = False
  output_template: str = ""

  def build_prompt(self, user_input: str, context: dict[str, str]) -> str:
    """构建任务执行提示词，注入前序上下文"""
    parts = [f"## 任务：{self.name}\n\n{self.description}"]

    if user_input:
      parts.append(f"## 用户原始需求\n\n{user_input}")

    if context:
      parts.append("## 前序任务输出（供参考）")
      for task_id, output in context.items():
        parts.append(f"### [{task_id}]\n{output}")

    if self.output_template:
      parts.append(f"## 输出模板\n\n请严格按照以下模板格式输出：\n\n{self.output_template}")

    fmt_hint = {
      OutputFormat.MARKDOWN: "请使用 Markdown 格式输出。",
      OutputFormat.JSON: "请使用 JSON 格式输出，确保可被解析。",
      OutputFormat.TEMPLATE: "请严格按照指定模板格式输出。",
    }
    parts.append(f"## 输出要求\n\n{fmt_hint[self.output_format]}")
    if self.output_format == OutputFormat.MARKDOWN:
      parts.append(REFERENCE_CITATION_RULES.strip())

    return "\n\n".join(parts)


# ── 学科领域审稿任务（可选，勾选对应 Agent 时启用） ─────────────

_DOMAIN_REVIEW_DEPS = ["task_cs_review", "task_bio_review", "task_material_review"]


def _domain_review_tasks(depends_on: list[str]) -> list[TaskDefinition]:
  return [
    TaskDefinition(
      id="task_cs_review",
      name="计算机学科评审",
      description=(
        "以《计算机学报》审稿人身份，审查方案中算法设计、系统架构、实验验证等计算机相关部分，"
        "评估技术先进性、实验完备性与可复现性，判断是否达到顶级期刊录用标准。"
      ),
      agent_id="cs_journal_reviewer",
      depends_on=depends_on,
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 计算机学科评审意见

## 1. 总体评价（录用建议：接受/小修/大修/拒稿）
## 2. 创新性评估
（是否提出新算法/新框架/新模型）
## 3. 实验设计审查
（对比实验、消融实验、基线公平性、数据集选择）
## 4. 可复现性与开源要求
（代码、数据、环境说明）
## 5. 方法描述与理论依据
## 6. 主要问题与修改建议
## 7. 评分（1-10）
- 创新性：
- 实验完备性：
- 可复现性：
- 整体质量：""",
    ),
    TaskDefinition(
      id="task_bio_review",
      name="生物学/生命科学评审",
      description=(
        "以 Cell Press / JIPB 等生物学期刊审稿人身份，审查生物实验设计的科学性与规范性，"
        "评估对照组、样本量、统计方法、伦理合规及生物学意义。"
      ),
      agent_id="bio_journal_reviewer",
      depends_on=depends_on,
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 生物学/生命科学评审意见

## 1. 总体评价（录用建议：接受/小修/大修/拒稿）
## 2. 实验设计科学性
（对照组、重复实验、盲法设计、样本量计算）
## 3. 统计方法审查
## 4. 生物学意义与创新性
## 5. 伦理合规
（动物实验、人体实验、伦理审查）
## 6. 可重复性与数据共享
## 7. 主要问题与修改建议
## 8. 评分（1-10）
- 实验设计：
- 统计严谨性：
- 生物学意义：
- 整体质量：""",
    ),
    TaskDefinition(
      id="task_material_review",
      name="材料/化学学科评审",
      description=(
        "以《镁合金学报》/化学类期刊审稿人身份，审查材料制备/化学合成路线、"
        "表征方法完备性与性能测试标准，评估可重复性与工程应用价值。"
      ),
      agent_id="material_journal_reviewer",
      depends_on=depends_on,
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 材料/化学学科评审意见

## 1. 总体评价（录用建议：接受/小修/大修/拒稿）
## 2. 技术路线可行性
（制备/合成工艺、参数优化）
## 3. 表征方法完备性
（XRD、SEM、TEM、XPS 等是否充分）
## 4. 性能测试与数据呈现
## 5. 可重复性与批次一致性
## 6. 工程应用价值
## 7. 主要问题与修改建议
## 8. 评分（1-10）
- 技术路线：
- 表征完备性：
- 数据可信度：
- 整体质量：""",
    ),
  ]


# ── 各场景任务流程 ──────────────────────────────────────────────

TASK_FLOWS: dict[ScenarioType, list[TaskDefinition]] = {
  ScenarioType.LITERATURE_REVIEW: [
    TaskDefinition(
      id="task_planning",
      name="课题规划",
      description="分析用户研究需求，明确研究问题、范围和关键概念，输出课题规划框架。",
      agent_id="planner",
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 课题规划

## 1. 研究问题
## 2. 研究范围与边界
## 3. 关键概念定义
## 4. 预期成果
## 5. 时间规划建议""",
    ),
    TaskDefinition(
      id="task_literature",
      name="文献调研",
      description="基于课题规划，系统检索和分析相关文献，识别研究现状、空白和趋势。",
      agent_id="literature_researcher",
      depends_on=["task_planning"],
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 文献综述报告

## 1. 检索策略
## 2. 核心文献综述
## 3. 研究现状总结
## 4. 研究空白识别
## 5. 创新方向建议
## 6. 参考文献
（正文引用编号与文末列表对应；每条格式：[编号] 作者. 标题. 期刊, 年份. [链接](URL)）
## 7. 文献数据库说明
（说明本次使用的检索数据库，如 Semantic Scholar、PubMed，及检索词）""",
    ),
    *_domain_review_tasks(["task_planning", "task_literature"]),
    TaskDefinition(
      id="task_review",
      name="方案终审",
      description="审查文献综述的完整性、准确性和学术规范性，并综合各学科审稿意见，输出终审报告。",
      agent_id="review_specialist",
      depends_on=["task_planning", "task_literature", *_DOMAIN_REVIEW_DEPS],
      requires_human_review=True,
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 终审报告

## 1. 质量评估（1-10分）
## 2. 主要优点
## 3. 存在问题
## 4. 改进建议
## 5. 完整工作方案（整合版）""",
    ),
  ],

  ScenarioType.EXPERIMENT_DESIGN: [
    TaskDefinition(
      id="task_planning",
      name="课题规划",
      description="分析实验需求，明确研究假设、实验目标和约束条件。",
      agent_id="planner",
      output_format=OutputFormat.MARKDOWN,
    ),
    TaskDefinition(
      id="task_experiment",
      name="实验方案设计",
      description="设计详细实验方案，包括假设、变量、流程、数据采集和质量控制。",
      agent_id="experiment_designer",
      depends_on=["task_planning"],
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 实验方案

## 1. 研究假设
## 2. 实验设计类型
## 3. 变量定义（自变量/因变量/控制变量）
## 4. 被试/样本设计
## 5. 实验流程
## 6. 数据采集方法
## 7. 统计分析方法
## 8. 质量控制措施""",
    ),
    TaskDefinition(
      id="task_budget",
      name="预算编制",
      description="根据实验方案估算资源需求，编制预算清单。此环节需要人工审批。",
      agent_id="resource_analyst",
      depends_on=["task_experiment"],
      requires_human_review=True,
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 预算方案

## 1. 设备与材料费用
## 2. 人员费用
## 3. 差旅与会议费用
## 4. 其他费用
## 5. 预算汇总表
## 6. 资源优化建议""",
    ),
    *_domain_review_tasks(["task_planning", "task_experiment", "task_budget"]),
    TaskDefinition(
      id="task_review",
      name="方案终审",
      description="综合审查实验方案和预算，并综合各学科审稿意见，输出最终工作方案。",
      agent_id="review_specialist",
      depends_on=["task_planning", "task_experiment", "task_budget", *_DOMAIN_REVIEW_DEPS],
      requires_human_review=True,
      output_format=OutputFormat.MARKDOWN,
    ),
  ],

  ScenarioType.FULL_PROPOSAL: [
    TaskDefinition(
      id="task_planning",
      name="课题规划",
      description="全面分析研究需求，制定整体研究框架。",
      agent_id="planner",
      output_format=OutputFormat.MARKDOWN,
    ),
    TaskDefinition(
      id="task_literature",
      name="文献调研",
      description="系统文献检索与综述。",
      agent_id="literature_researcher",
      depends_on=["task_planning"],
      output_format=OutputFormat.MARKDOWN,
    ),
    TaskDefinition(
      id="task_experiment",
      name="实验方案设计",
      description="设计详细实验方案。",
      agent_id="experiment_designer",
      depends_on=["task_planning", "task_literature"],
      output_format=OutputFormat.MARKDOWN,
    ),
    TaskDefinition(
      id="task_budget",
      name="预算编制",
      description="编制详细预算方案。",
      agent_id="resource_analyst",
      depends_on=["task_experiment"],
      requires_human_review=True,
      output_format=OutputFormat.MARKDOWN,
    ),
    *_domain_review_tasks(["task_planning", "task_literature", "task_experiment", "task_budget"]),
    TaskDefinition(
      id="task_review",
      name="方案终审",
      description="综合审查，并整合各学科审稿意见，输出完整工作方案。",
      agent_id="review_specialist",
      depends_on=["task_planning", "task_literature", "task_experiment", "task_budget", *_DOMAIN_REVIEW_DEPS],
      requires_human_review=True,
      output_format=OutputFormat.MARKDOWN,
    ),
  ],

  ScenarioType.LITERATURE_BASED_PROPOSAL: [
    TaskDefinition(
      id="task_planning",
      name="课题规划",
      description=(
        "基于用户选定的文献库分析结果，明确研究背景、目标与范围。"
        "须优先引用用户文献库内容，标注引用编号。"
      ),
      agent_id="planner",
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 开题报告 · 课题规划

## 1. 研究背景
（优先引用用户文献库 [编号]）
## 2. 国内外研究现状
## 3. 研究意义
## 4. 研究目标
## 5. 研究内容与技术路线
## 6. 预期成果""",
    ),
    TaskDefinition(
      id="task_literature",
      name="文献整合",
      description=(
        "整合用户文献库中选定文献的分析结果，补充必要的研究空白识别。"
        "优先使用用户文献，网络检索仅作补充并须标注来源。"
      ),
      agent_id="literature_researcher",
      depends_on=["task_planning"],
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 文献整合报告

## 1. 用户文献库综述
（按 [编号] 引用用户文献）
## 2. 研究空白识别
## 3. 创新方向建议
## 4. 参考文献
## 5. 文献数据库说明
（区分用户文献库与网络检索来源）""",
    ),
    TaskDefinition(
      id="task_experiment",
      name="研究方法设计",
      description="基于文献整合结果，设计详细研究方法。",
      agent_id="experiment_designer",
      depends_on=["task_planning", "task_literature"],
      output_format=OutputFormat.MARKDOWN,
    ),
    TaskDefinition(
      id="task_budget",
      name="预算编制",
      description="编制研究预算方案。",
      agent_id="resource_analyst",
      depends_on=["task_experiment"],
      requires_human_review=True,
      output_format=OutputFormat.MARKDOWN,
    ),
    *_domain_review_tasks(["task_planning", "task_literature", "task_experiment", "task_budget"]),
    TaskDefinition(
      id="task_review",
      name="开题报告终审",
      description="综合审查开题报告各章节，输出完整开题报告。",
      agent_id="review_specialist",
      depends_on=["task_planning", "task_literature", "task_experiment", "task_budget", *_DOMAIN_REVIEW_DEPS],
      requires_human_review=True,
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 开题报告（完整版）

## 1. 研究背景
## 2. 国内外研究现状
## 3. 研究意义
## 4. 研究目标与内容
## 5. 研究方法
## 6. 技术路线
## 7. 预期成果与创新点
## 8. 研究计划与进度安排
## 9. 参考文献
## 10. 文献数据库说明""",
    ),
  ],

  ScenarioType.LITERATURE_BASED_REVIEW: [
    TaskDefinition(
      id="task_planning",
      name="综述框架规划",
      description=(
        "基于用户选定文献库的分析结果与综述主题，规划系统性文献综述的写作框架："
        "界定综述范围、确定分类维度（按主题/方法/发展阶段/国别等）、设计章节结构。"
        "须优先引用用户文献库内容，标注引用编号。"
      ),
      agent_id="planner",
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 文献综述 · 撰写框架

## 1. 综述主题与核心问题
## 2. 研究背景与研究意义
## 3. 综述范围界定与文献纳入说明
## 4. 关键概念界定
## 5. 拟采用的组织脉络与分类维度
## 6. 综述章节结构设计
## 7. 写作重点与述评提示""",
    ),
    TaskDefinition(
      id="task_literature",
      name="综述撰写",
      description=(
        "严格按照学术文献综述（literature review）写作规范，基于用户选定文献库的分析结果撰写完整综述正文："
        "围绕主题按维度归纳、比较与评述文献，避免逐篇罗列摘要；"
        "正文引用以 [编号] 标注且编号须与用户文献库一致；"
        "识别研究现状、争论点、研究空白与未来方向。网络检索仅作补充并须标注来源。"
      ),
      agent_id="literature_researcher",
      depends_on=["task_planning"],
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 文献综述

## 1 引言
（研究背景与意义、综述目的与范围）
## 2 文献检索与筛选说明
（数据源、时间范围、纳入标准；区分用户文献库与网络来源）
## 3 国内外研究现状
（按主题维度/发展脉络组织小节，逐类综述并给出述评）
### 3.1 （主题一）
### 3.2 （主题二）
## 4 主要研究方法与技术对比
## 5 现有研究存在的问题与争论
## 6 研究空白与未来展望
## 7 结论
## 8 参考文献
（每条格式：[编号] 作者. 标题. 期刊, 年份. DOI/链接；编号须与正文引用一致）
## 9 文献数据库说明""",
    ),
    *_domain_review_tasks(["task_planning", "task_literature"]),
    TaskDefinition(
      id="task_review",
      name="综述终审",
      description=(
        "以学术期刊审稿人视角审查综述的完整性、准确性、逻辑结构与学术规范，"
        "综合各学科审稿意见后整合输出完整文献综述。"
      ),
      agent_id="review_specialist",
      depends_on=["task_planning", "task_literature", *_DOMAIN_REVIEW_DEPS],
      requires_human_review=True,
      output_format=OutputFormat.MARKDOWN,
      output_template="""# 综述终审报告

## 1 质量评估（1-10分）
## 2 主要优点
## 3 存在问题
## 4 改进建议
## 5 完整文献综述（整合版）
（按「引言 → 文献检索与筛选 → 国内外研究现状 → 研究方法对比 → 问题与争论 → 研究空白与展望 → 结论 → 参考文献」结构输出，正文保留 [编号] 引用）""",
    ),
  ],
}
