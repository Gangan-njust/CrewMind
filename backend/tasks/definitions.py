"""步骤2：任务分解与协作流程定义"""
from dataclasses import dataclass, field
from enum import Enum

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

    return "\n\n".join(parts)


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
## 6. 参考文献列表""",
    ),
    TaskDefinition(
      id="task_review",
      name="方案终审",
      description="审查文献综述的完整性、准确性和学术规范性，输出终审报告。",
      agent_id="review_specialist",
      depends_on=["task_planning", "task_literature"],
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
    TaskDefinition(
      id="task_review",
      name="方案终审",
      description="综合审查实验方案和预算，输出最终工作方案。",
      agent_id="review_specialist",
      depends_on=["task_planning", "task_experiment", "task_budget"],
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
    TaskDefinition(
      id="task_review",
      name="方案终审",
      description="综合审查，输出完整工作方案。",
      agent_id="review_specialist",
      depends_on=["task_planning", "task_literature", "task_experiment", "task_budget"],
      requires_human_review=True,
      output_format=OutputFormat.MARKDOWN,
    ),
  ],
}
