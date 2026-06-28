"""工作流模板存储与内置推荐模板"""
import json
import re
import uuid
from datetime import datetime

from sqlalchemy import select

from backend.storage.database import get_session
from backend.storage.models import WorkflowTemplateRecord

VARIABLE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")

BUILTIN_TEMPLATES: list[dict] = [
  {
    "id": "builtin:ai_literature_review",
    "name": "AI 方向文献综述模板",
    "description": "适用于人工智能/机器学习方向的系统性文献综述，覆盖研究背景、方法分类与趋势分析。",
    "scenario": "literature_review",
    "user_input": (
      "请围绕「{{研究方向}}」开展系统性文献综述。\n\n"
      "研究背景：{{研究背景简述}}\n"
      "关注重点：{{具体技术或方法，如 Transformer、强化学习等}}\n"
      "应用场景：{{应用场景，如医学影像、自然语言处理等}}\n"
      "文献时间范围：{{起始年份}} 至今\n\n"
      "请梳理该领域的主要研究脉络、代表性工作、当前热点与研究空白，并给出未来研究方向建议。"
    ),
    "selected_agents": ["planner", "literature_researcher", "review_specialist"],
    "is_builtin": True,
    "variables": ["研究方向", "研究背景简述", "具体技术或方法，如 Transformer、强化学习等", "应用场景，如医学影像、自然语言处理等", "起始年份"],
  },
  {
    "id": "builtin:biology_experiment",
    "name": "生物实验方案模板",
    "description": "适用于分子生物学、细胞生物学等实验研究，含假设、分组设计与样本量规划。",
    "scenario": "experiment_design",
    "user_input": (
      "请为以下生物实验课题设计完整实验方案。\n\n"
      "实验课题：{{实验课题名称}}\n"
      "研究对象/材料：{{物种或细胞系，如 HEK293、C57BL/6 小鼠等}}\n"
      "核心科学问题：{{待验证的假设或机制}}\n"
      "主要实验方法：{{如 Western Blot、qPCR、流式细胞术等}}\n"
      "预期样本量：约 {{样本数量}} 例/组\n"
      "实验周期：{{预计周期，如 8 周}}\n"
      "资源约束：{{设备、经费或伦理等限制}}\n\n"
      "请输出包含实验分组、操作流程、对照设置、数据采集与质控措施的详细方案。"
    ),
    "selected_agents": ["planner", "experiment_designer", "resource_analyst", "review_specialist"],
    "is_builtin": True,
    "variables": ["实验课题名称", "物种或细胞系，如 HEK293、C57BL/6 小鼠等", "待验证的假设或机制", "如 Western Blot、qPCR、流式细胞术等", "样本数量", "预计周期，如 8 周", "设备、经费或伦理等限制"],
  },
  {
    "id": "builtin:full_proposal",
    "name": "完整科研工作方案模板",
    "description": "从文献调研到实验设计与预算的全流程方案，适合基金申报或开题报告。",
    "scenario": "full_proposal",
    "user_input": (
      "请制定一份完整的科研工作方案。\n\n"
      "课题名称：{{课题名称}}\n"
      "研究背景与意义：{{背景描述}}\n"
      "研究目标：{{主要目标与次要目标}}\n"
      "技术路线偏好：{{方法或技术栈}}\n"
      "预期成果：{{论文、专利、样机等}}\n"
      "项目周期：{{项目周期，如 3 年}}\n"
      "经费规模：约 {{预算金额}} 万元\n\n"
      "请协调各 Agent 输出文献综述、实验方案、预算清单与终审报告。"
    ),
    "selected_agents": ["planner", "literature_researcher", "experiment_designer", "resource_analyst", "review_specialist"],
    "is_builtin": True,
    "variables": ["课题名称", "背景描述", "主要目标与次要目标", "方法或技术栈", "论文、专利、样机等", "项目周期，如 3 年", "预算金额"],
  },
  {
    "id": "builtin:cs_literature_review",
    "name": "计算机专业文献综述模板",
    "description": "适用于计算机科学方向，覆盖算法、系统、软件工程等主题的文献梳理与趋势分析。",
    "scenario": "literature_review",
    "user_input": (
      "请围绕计算机科学方向「{{研究方向}}」开展系统性文献综述。\n\n"
      "研究背景：{{研究背景简述}}\n"
      "核心问题：{{待解决的核心技术问题}}\n"
      "关注技术栈：{{编程语言、框架或算法，如 PyTorch、分布式系统、图神经网络等}}\n"
      "应用场景：{{应用场景，如推荐系统、边缘计算、代码生成等}}\n"
      "文献时间范围：{{起始年份}} 至今\n\n"
      "请梳理该方向的代表性工作、方法分类、主流 benchmark、研究空白与未来趋势。"
    ),
    "selected_agents": ["planner", "literature_researcher", "review_specialist"],
    "is_builtin": True,
    "variables": ["研究方向", "研究背景简述", "待解决的核心技术问题", "编程语言、框架或算法，如 PyTorch、分布式系统、图神经网络等", "应用场景，如推荐系统、边缘计算、代码生成等", "起始年份"],
  },
  {
    "id": "builtin:cs_system_validation",
    "name": "计算机专业系统验证方案模板",
    "description": "适用于算法实验、系统性能评测、A/B 测试等计算机方向的验证方案设计。",
    "scenario": "experiment_design",
    "user_input": (
      "请为以下计算机方向课题设计系统验证与实验方案。\n\n"
      "课题名称：{{课题名称}}\n"
      "研究目标：{{要验证的假设或系统能力}}\n"
      "技术方案概述：{{系统架构、模型或算法简述}}\n"
      "数据集/Benchmark：{{如 ImageNet、COCO、自建数据集等}}\n"
      "对比基线：{{Baseline 方法或系统}}\n"
      "评价指标：{{如 Accuracy、F1、Latency、Throughput 等}}\n"
      "实验环境：{{硬件配置，如 GPU 型号、内存等}}\n"
      "预期实验周期：{{预计周期，如 6 周}}\n\n"
      "请输出实验分组、对照设置、消融实验、数据采集流程与结果分析计划。"
    ),
    "selected_agents": ["planner", "experiment_designer", "resource_analyst", "review_specialist"],
    "is_builtin": True,
    "variables": ["课题名称", "要验证的假设或系统能力", "系统架构、模型或算法简述", "如 ImageNet、COCO、自建数据集等", "Baseline 方法或系统", "如 Accuracy、F1、Latency、Throughput 等", "硬件配置，如 GPU 型号、内存等", "预计周期，如 6 周"],
  },
  {
    "id": "builtin:mechanical_literature_review",
    "name": "机械专业文献综述模板",
    "description": "适用于机械工程、智能制造、机器人等方向的文献调研与工艺技术综述。",
    "scenario": "literature_review",
    "user_input": (
      "请围绕机械工程方向「{{研究方向}}」开展文献综述。\n\n"
      "研究背景：{{研究背景简述}}\n"
      "研究对象：{{零件、机构或系统，如减速器、六轴机器人、增材制造设备等}}\n"
      "关键工艺/方法：{{如 CNC 加工、有限元分析、拓扑优化等}}\n"
      "性能关注点：{{如强度、刚度、疲劳寿命、加工精度等}}\n"
      "文献时间范围：{{起始年份}} 至今\n\n"
      "请梳理国内外研究现状、主流技术路线、工程应用案例与研究空白。"
    ),
    "selected_agents": ["planner", "literature_researcher", "review_specialist"],
    "is_builtin": True,
    "variables": ["研究方向", "研究背景简述", "零件、机构或系统，如减速器、六轴机器人、增材制造设备等", "如 CNC 加工、有限元分析、拓扑优化等", "如强度、刚度、疲劳寿命、加工精度等", "起始年份"],
  },
  {
    "id": "builtin:mechanical_experiment",
    "name": "机械专业实验方案模板",
    "description": "适用于力学试验、工艺验证、结构测试等机械方向实验方案设计。",
    "scenario": "experiment_design",
    "user_input": (
      "请为以下机械工程实验课题设计完整实验方案。\n\n"
      "实验课题：{{实验课题名称}}\n"
      "研究对象：{{试件或部件，如齿轮副、焊接接头、复合材料板等}}\n"
      "实验目的：{{待验证的性能指标或工艺参数}}\n"
      "实验方法：{{如拉伸试验、疲劳试验、三坐标测量、振动测试等}}\n"
      "试验设备：{{如万能试验机、扫描电镜、激光跟踪仪等}}\n"
      "试样数量：约 {{样本数量}} 件/组\n"
      "实验周期：{{预计周期，如 10 周}}\n"
      "约束条件：{{加工精度、安全规范或经费限制}}\n\n"
      "请输出实验分组、加载条件、测量方案、误差分析与质量控制措施。"
    ),
    "selected_agents": ["planner", "experiment_designer", "resource_analyst", "review_specialist"],
    "is_builtin": True,
    "variables": ["实验课题名称", "试件或部件，如齿轮副、焊接接头、复合材料板等", "待验证的性能指标或工艺参数", "如拉伸试验、疲劳试验、三坐标测量、振动测试等", "如万能试验机、扫描电镜、激光跟踪仪等", "样本数量", "预计周期，如 10 周", "加工精度、安全规范或经费限制"],
  },
]


def extract_variables(user_input: str) -> list[str]:
  seen: set[str] = set()
  result: list[str] = []
  for match in VARIABLE_PATTERN.finditer(user_input):
    name = match.group(1).strip()
    if name and name not in seen:
      seen.add(name)
      result.append(name)
  return result


def _serialize(row: WorkflowTemplateRecord) -> dict:
  agents = json.loads(row.selected_agents_json or "[]")
  return {
    "id": row.id,
    "name": row.name,
    "description": row.description,
    "scenario": row.scenario,
    "user_input": row.user_input,
    "selected_agents": agents,
    "is_builtin": False,
    "variables": extract_variables(row.user_input),
    "created_at": row.created_at.isoformat(),
  }


class TemplateStore:
  def list_templates(self, user_id: str) -> dict:
    recommended = [{**t, "variables": t.get("variables") or extract_variables(t["user_input"])} for t in BUILTIN_TEMPLATES]
    with get_session() as session:
      rows = session.scalars(
        select(WorkflowTemplateRecord)
        .where(WorkflowTemplateRecord.user_id == user_id)
        .order_by(WorkflowTemplateRecord.created_at.desc())
      ).all()
      mine = [_serialize(row) for row in rows]
    return {"recommended": recommended, "mine": mine}

  def get_template(self, template_id: str, user_id: str) -> dict | None:
    for tpl in BUILTIN_TEMPLATES:
      if tpl["id"] == template_id:
        return {**tpl, "variables": tpl.get("variables") or extract_variables(tpl["user_input"])}
    with get_session() as session:
      row = session.get(WorkflowTemplateRecord, template_id)
      if not row or row.user_id != user_id:
        return None
      return _serialize(row)

  def create_template(
    self,
    user_id: str,
    name: str,
    scenario: str,
    user_input: str,
    selected_agents: list[str],
    description: str = "",
  ) -> dict:
    now = datetime.now()
    row = WorkflowTemplateRecord(
      id=str(uuid.uuid4()),
      user_id=user_id,
      name=name.strip(),
      description=description.strip(),
      scenario=scenario,
      user_input=user_input.strip(),
      selected_agents_json=json.dumps(selected_agents, ensure_ascii=False),
      created_at=now,
    )
    with get_session() as session:
      session.add(row)
      session.commit()
      session.refresh(row)
      return _serialize(row)

  def delete_template(self, template_id: str, user_id: str) -> None:
    if template_id.startswith("builtin:"):
      raise ValueError("内置模板不可删除")
    with get_session() as session:
      row = session.get(WorkflowTemplateRecord, template_id)
      if not row or row.user_id != user_id:
        raise ValueError("模板不存在")
      session.delete(row)
      session.commit()


template_store = TemplateStore()
