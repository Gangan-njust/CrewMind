"""Agent 角色注册表：内置角色 + 用户自定义角色"""
import json
import re
import uuid

from sqlalchemy import select

from backend.agents.roles import AgentRole, ALL_AGENTS as BUILTIN_AGENTS
from backend.storage.database import get_session
from backend.storage.models import CustomAgentRecord

VALID_TOOLS = {"web_search", "file_parser", "code_interpreter"}
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _record_to_role(record: CustomAgentRecord) -> AgentRole:
  tools = json.loads(record.tools_json or "[]")
  return AgentRole(
    id=record.id,
    name=record.name,
    title=record.title,
    background=record.background,
    goal=record.goal,
    tools=tools,
    use_reasoning=record.use_reasoning,
  )


def get_agent_registry(user_id: str) -> dict[str, AgentRole]:
  """返回内置 + 当前用户自定义 Agent 的合并注册表"""
  registry = dict(BUILTIN_AGENTS)
  session = get_session()
  try:
    stmt = select(CustomAgentRecord).where(CustomAgentRecord.user_id == user_id)
    for record in session.scalars(stmt).all():
      registry[record.id] = _record_to_role(record)
  finally:
    session.close()
  return registry


def is_builtin(agent_id: str) -> bool:
  return agent_id in BUILTIN_AGENTS


def validate_agent_id(agent_id: str) -> None:
  if not _ID_PATTERN.match(agent_id):
    raise ValueError("角色 ID 须以小写字母开头，仅含小写字母、数字和下划线，长度 2-64")
  if is_builtin(agent_id):
    raise ValueError(f"角色 ID 与内置角色冲突: {agent_id}")


def validate_tools(tools: list[str]) -> None:
  invalid = [t for t in tools if t not in VALID_TOOLS]
  if invalid:
    raise ValueError(f"不支持的工具: {', '.join(invalid)}")


def serialize_agent(role: AgentRole, builtin: bool) -> dict:
  return {
    "id": role.id,
    "name": role.name,
    "title": role.title,
    "background": role.background,
    "goal": role.goal,
    "tools": role.tools,
    "use_reasoning": role.use_reasoning,
    "is_builtin": builtin,
  }


def list_agents(user_id: str) -> list[dict]:
  registry = get_agent_registry(user_id)
  return [
    serialize_agent(role, is_builtin(aid))
    for aid, role in registry.items()
  ]


def create_custom_agent(
  *,
  user_id: str,
  agent_id: str | None,
  name: str,
  title: str,
  background: str,
  goal: str,
  tools: list[str] | None = None,
  use_reasoning: bool = False,
) -> dict:
  tools = tools or []
  validate_tools(tools)

  final_id = agent_id or f"custom_{uuid.uuid4().hex[:8]}"
  validate_agent_id(final_id)

  registry = get_agent_registry(user_id)
  if final_id in registry:
    raise ValueError(f"角色 ID 已存在: {final_id}")

  session = get_session()
  try:
    record = CustomAgentRecord(
      id=final_id,
      user_id=user_id,
      name=name,
      title=title,
      background=background,
      goal=goal,
      tools_json=json.dumps(tools, ensure_ascii=False),
      use_reasoning=use_reasoning,
    )
    session.add(record)
    session.commit()
    role = _record_to_role(record)
    return serialize_agent(role, False)
  finally:
    session.close()


def update_custom_agent(
  agent_id: str,
  *,
  user_id: str,
  name: str,
  title: str,
  background: str,
  goal: str,
  tools: list[str] | None = None,
  use_reasoning: bool = False,
) -> dict:
  if is_builtin(agent_id):
    raise ValueError("内置角色不可修改")

  tools = tools or []
  validate_tools(tools)

  session = get_session()
  try:
    record = session.get(CustomAgentRecord, agent_id)
    if not record or record.user_id != user_id:
      raise ValueError(f"角色不存在: {agent_id}")

    record.name = name
    record.title = title
    record.background = background
    record.goal = goal
    record.tools_json = json.dumps(tools, ensure_ascii=False)
    record.use_reasoning = use_reasoning
    session.commit()
    return serialize_agent(_record_to_role(record), False)
  finally:
    session.close()


def delete_custom_agent(agent_id: str, user_id: str) -> None:
  if is_builtin(agent_id):
    raise ValueError("内置角色不可删除")

  session = get_session()
  try:
    record = session.get(CustomAgentRecord, agent_id)
    if not record or record.user_id != user_id:
      raise ValueError(f"角色不存在: {agent_id}")
    session.delete(record)
    session.commit()
  finally:
    session.close()
