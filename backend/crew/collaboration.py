"""协作模式定义：串行 / 辩论 / 投票"""
import json
import re
from enum import Enum

from backend.agents.roles import AgentRole
from backend.tasks.definitions import OutputFormat, TaskDefinition


class CollaborationMode(str, Enum):
  SEQUENTIAL = "sequential"
  DEBATE = "debate"
  VOTING = "voting"


COLLABORATION_LABELS: dict[str, str] = {
  CollaborationMode.SEQUENTIAL: "串行模式",
  CollaborationMode.DEBATE: "辩论模式",
  CollaborationMode.VOTING: "投票模式",
}

DEBATE_TASK_ID = "task_debate"
VOTING_AGGREGATE_TASK_ID = "task_vote_aggregate"

VOTING_SOLVER_CONFIGS: list[tuple[str, str, str]] = [
  (
    "task_vote_planner",
    "planner",
    "侧重创新性与研究框架的完整性，提出具有前瞻性的方案",
  ),
  (
    "task_vote_designer",
    "experiment_designer",
    "侧重实验设计的严谨性与可行性，确保方法可落地执行",
  ),
  (
    "task_vote_analyst",
    "resource_analyst",
    "侧重资源约束与预算合理性，确保方案经济可行",
  ),
]


def get_debate_tasks() -> list[TaskDefinition]:
  return [
    TaskDefinition(
      id=DEBATE_TASK_ID,
      name="方案辩论",
      description="正方提出方案，反方质疑，正方修订，裁判评估，多轮迭代直至共识。",
      agent_id="experiment_designer",
      output_format=OutputFormat.MARKDOWN,
    ),
  ]


def get_voting_tasks() -> list[TaskDefinition]:
  name_map = {
    "task_vote_planner": "求解者·规划师",
    "task_vote_designer": "求解者·设计师",
    "task_vote_analyst": "求解者·分析师",
  }
  solver_ids = [cfg[0] for cfg in VOTING_SOLVER_CONFIGS]
  tasks = [
    TaskDefinition(
      id=task_id,
      name=name_map[task_id],
      description=f"独立求解：{focus}",
      agent_id=agent_id,
      output_format=OutputFormat.MARKDOWN,
    )
    for task_id, agent_id, focus in VOTING_SOLVER_CONFIGS
  ]
  tasks.append(
    TaskDefinition(
      id=VOTING_AGGREGATE_TASK_ID,
      name="方案聚合评审",
      description="评审所有求解者方案，按维度打分并选出最优方案。",
      agent_id="review_specialist",
      depends_on=solver_ids,
      output_format=OutputFormat.MARKDOWN,
    ),
  )
  return tasks


def debate_proponent_role(base: AgentRole) -> AgentRole:
  return AgentRole(
    id=base.id,
    name=base.name,
    title=base.title,
    background=base.background,
    goal=base.goal + " 在辩论中作为正方，提出有说服力的方案，并针对质疑进行辩护与修订。",
    tools=base.tools,
    use_reasoning=base.use_reasoning,
  )


def debate_critic_role(base: AgentRole) -> AgentRole:
  return AgentRole(
    id=base.id,
    name=base.name,
    title=base.title,
    background=base.background,
    goal=(
      "在辩论中作为反方，寻找方案中的逻辑漏洞、数据缺失、可行性风险，"
      "并提出尖锐、具体的质疑，每条质疑须可操作、可验证。"
    ),
    tools=[],
    use_reasoning=True,
  )


def debate_judge_role(base: AgentRole) -> AgentRole:
  return AgentRole(
    id=base.id,
    name=base.name,
    title=base.title,
    background=base.background,
    goal=(
      "在辩论中作为裁判，评估辩论是否达成共识。"
      "依据完整性、可行性、逻辑一致性三个维度判断方案是否令人满意。"
    ),
    tools=[],
    use_reasoning=True,
  )


def resolve_debate_proponent_agent_id(scenario: str) -> str:
  if scenario == "literature_review":
    return "planner"
  return "experiment_designer"


def build_debate_init_prompt(user_input: str, scenario: str) -> str:
  return f"""## 任务：生成初始方案草稿

请根据用户需求，输出一份完整、结构化的工作方案草稿，作为辩论的起点。

## 用户原始需求

{user_input}

## 场景

{scenario}

## 输出要求

- 使用 Markdown 格式
- 内容须完整、可辩论（包含明确的方法、步骤与假设）
- 标注不确定信息，避免虚构数据
"""


def build_debate_critic_prompt(user_input: str, proposal: str, history_text: str) -> str:
  return f"""## 任务：反方质疑

请审查以下方案，输出质疑列表。每条质疑须具体、尖锐，并说明理由。

## 用户原始需求

{user_input}

## 辩论历史

{history_text}

## 当前方案

{proposal}

## 输出格式

使用 Markdown，按以下结构输出：

# 反方质疑（第 N 轮）

## 质疑列表
1. **[类别]** 质疑内容 — 理由
2. ...

## 总体评价
简要说明方案的主要薄弱环节
"""


def build_debate_revision_prompt(
  user_input: str, proposal: str, criticisms: str, history_text: str,
) -> str:
  return f"""## 任务：正方修订方案

请根据反方质疑，修订方案并在修订中逐条回应质疑。

## 用户原始需求

{user_input}

## 辩论历史

{history_text}

## 当前方案（修订前）

{proposal}

## 反方质疑

{criticisms}

## 输出格式

# 修订方案

## 逐条回应
（针对每条质疑给出回应）

## 修订后的完整方案
（整合所有修订后的完整方案正文）
"""


def build_debate_judge_prompt(
  user_input: str, proposal: str, history_text: str, round_num: int, max_rounds: int,
) -> str:
  return f"""## 任务：裁判评估

评估当前辩论是否已使方案足够完善，决定是否继续下一轮辩论。

## 用户原始需求

{user_input}

## 辩论历史

{history_text}

## 当前方案（第 {round_num} 轮）

{proposal}

## 评估维度

1. **完整性**：是否覆盖用户需求的所有关键方面
2. **可行性**：方法是否可落地执行
3. **逻辑一致性**：论证是否自洽、无矛盾

## 输出要求

先输出 Markdown 评估报告，然后在末尾单独输出 JSON 决策块（必须可被解析）：

```json
{{
  "should_continue": false,
  "reason": "所有质疑已充分回应，方案已完善",
  "scores": {{
    "completeness": 8,
    "feasibility": 8,
    "consistency": 9
  }}
}}
```

- `should_continue`: 若方案已令人满意则为 false；若仍需改进则为 true
- 当前为第 {round_num}/{max_rounds} 轮，若已达最大轮数应设为 false
"""


def format_debate_history(history: list[dict]) -> str:
  if not history:
    return "（尚无历史记录）"
  parts: list[str] = []
  for entry in history:
    phase_label = {
      "proponent_init": "正方初稿",
      "critic": "反方质疑",
      "proponent": "正方修订",
      "judge": "裁判评估",
    }.get(entry.get("phase", ""), entry.get("phase", ""))
    rnd = entry.get("round", 0)
    parts.append(f"### 第 {rnd} 轮 · {phase_label}\n\n{entry.get('content', '')}")
  return "\n\n".join(parts)


def format_debate_output(proposal: str, history: list[dict], rounds: int) -> str:
  summary_parts: list[str] = []
  for entry in history:
    if entry.get("phase") == "critic":
      summary_parts.append(f"**第 {entry.get('round')} 轮反方质疑**\n{entry.get('content', '')[:500]}...")
    elif entry.get("phase") == "proponent" and entry.get("round", 0) > 0:
      summary_parts.append(f"**第 {entry.get('round')} 轮正方回应**\n（见完整修订方案）")

  return f"""# 辩论模式 · 最终方案

> 共进行 {rounds} 轮辩论

## 最终方案

{proposal}

---

## 辩论摘要

{chr(10).join(summary_parts) if summary_parts else "（单轮即达成共识）"}

---

## 完整辩论记录

{format_debate_history(history)}
"""


def parse_judge_decision(text: str) -> dict:
  default = {
    "should_continue": False,
    "reason": "无法解析裁判决策，默认终止",
    "scores": {},
  }
  json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
  raw = json_match.group(1) if json_match else None
  if not raw:
    brace_match = re.search(r"\{[^{}]*\"should_continue\"[^{}]*\}", text, re.DOTALL)
    raw = brace_match.group(0) if brace_match else None
  if not raw:
    return default
  try:
    data = json.loads(raw)
    return {
      "should_continue": bool(data.get("should_continue", False)),
      "reason": str(data.get("reason", "")),
      "scores": data.get("scores", {}),
    }
  except json.JSONDecodeError:
    return default


def build_solver_prompt(user_input: str, focus: str, scenario: str) -> str:
  return f"""## 任务：独立生成完整工作方案

请独立思考，不受其他 Agent 影响，针对用户需求生成一份完整的工作方案。

## 侧重点

{focus}

## 用户原始需求

{user_input}

## 场景

{scenario}

## 输出要求

- 使用 Markdown 格式，结构完整
- 方案须自洽、可执行
- 明确标注不确定信息
"""


def build_aggregator_prompt(user_input: str, proposals: dict[str, str], agent_names: dict[str, str]) -> str:
  sections = []
  for task_id, output in proposals.items():
    name = agent_names.get(task_id, task_id)
    sections.append(f"### 方案：{name}\n\n{output}")
  proposals_text = "\n\n---\n\n".join(sections)

  return f"""## 任务：方案聚合评审

评审以下各求解者独立生成的方案，按维度打分并选出最优方案。

## 用户原始需求

{user_input}

## 各求解者方案

{proposals_text}

## 评审维度（每项 1-10 分）

- 创新性
- 可行性
- 完整性
- 逻辑性

## 输出格式

# 聚合评审报告

## 各方案评分表

| 方案 | 创新性 | 可行性 | 完整性 | 逻辑性 | 加权总分 |
|------|--------|--------|--------|--------|----------|
| ... | | | | | |

## 评审意见

（对各方案的优缺点分析）

## 最终推荐

说明推荐哪个方案及理由

## 最优方案正文

（输出推荐方案的完整内容，可直接作为最终交付物）

在报告末尾输出 JSON：

```json
{{
  "winner": "方案名称",
  "scores": {{
    "方案A": {{"innovation": 8, "feasibility": 7, "completeness": 9, "logic": 8, "total": 8.0}}
  }}
}}
```
"""


def format_voting_output(
  winner_proposal: str, aggregator_report: str, solver_outputs: dict[str, str], agent_names: dict[str, str],
) -> str:
  summaries = []
  for task_id, output in solver_outputs.items():
    name = agent_names.get(task_id, task_id)
    preview = output[:300] + ("..." if len(output) > 300 else "")
    summaries.append(f"- **{name}**：{preview}")

  return f"""# 投票模式 · 最终方案

## 最终选定方案

{winner_proposal}

---

## 聚合者评审

{aggregator_report}

---

## 各求解者方案摘要

{chr(10).join(summaries)}
"""
