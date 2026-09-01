"""统一工具注册与 Agent 工具调度"""
import json
import logging
from typing import Any, Callable, Awaitable

from backend.agents.citations import format_citation_instruction
from backend.agents.roles import AgentRole
from backend.tools.code_interpreter import CodeInterpreterTool
from backend.tools.file_parser import FileParserTool
from backend.tools.keywords import extract_search_query
from backend.tools.rag_search import RagSearchTool
from backend.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)

ToolEventCallback = Callable[[str, str, str], Awaitable[None]]

TOOL_REGISTRY: dict[str, Any] = {
  "web_search": WebSearchTool(),
  "file_parser": FileParserTool(),
  "code_interpreter": CodeInterpreterTool(),
  "rag_search": RagSearchTool(),
}

# 向后兼容
DEFAULT_TOOLS = TOOL_REGISTRY


async def run_agent_tools(
  agent_role: AgentRole,
  task_prompt: str,
  user_input: str,
  context_outputs: dict[str, str] | None,
  reference_files: list[str],
  partial_output: str,
  on_tool_event: ToolEventCallback | None = None,
  workspace_id: str | None = None,
) -> list[dict[str, str]]:
  """按 Agent 配置执行工具，返回需追加到 messages 的用户消息列表"""
  if partial_output:
    return []

  messages: list[dict[str, str]] = []
  tools = set(agent_role.tools)

  async def _emit(tool_name: str, status: str, detail: str) -> None:
    if on_tool_event:
      await on_tool_event(tool_name, status, detail)

  file_paths = reference_files or []
  if file_paths and "file_parser" in tools:
    parser = TOOL_REGISTRY.get("file_parser")
    if parser:
      await _emit("file_parser", "started", f"解析 {len(file_paths)} 个参考文件")
      try:
        content = await parser.run_for_files(file_paths)
        await _emit("file_parser", "completed", f"已解析 {len(file_paths)} 个文件")
        if content:
          messages.append({
            "role": "user",
            "content": f"## 参考文件内容\n\n{content}",
          })
      except Exception as e:
        logger.warning("file_parser 失败: %s", e)
        await _emit("file_parser", "failed", str(e))

  if "rag_search" in tools and workspace_id:
    rag_tool = TOOL_REGISTRY.get("rag_search")
    if rag_tool:
      query = extract_search_query(user_input, task_prompt)
      if query:
        await _emit("rag_search", "started", f"本地文献库检索: {query[:80]}")
        try:
          search_result = await rag_tool.run(query=query, workspace_id=workspace_id)
          await _emit("rag_search", "completed", "本地文献库检索完成")
          messages.append({
            "role": "user",
            "content": f"## 本地文献库检索结果\n\n检索词: {query}\n\n{search_result}",
          })
        except Exception as e:
          logger.warning("rag_search 失败: %s", e)
          await _emit("rag_search", "failed", str(e))

  if "web_search" in tools:
    search_tool = TOOL_REGISTRY.get("web_search")
    if search_tool:
      query = extract_search_query(user_input, task_prompt)
      if query:
        await _emit("web_search", "started", f"检索: {query[:80]}")
        try:
          search_result = await search_tool.run(query=query)
          databases_used: list[str] = []
          try:
            parsed = json.loads(search_result)
            if isinstance(parsed, dict):
              databases_used = list(parsed.get("databases_used") or [])
          except json.JSONDecodeError:
            pass
          source_hint = (
            "、".join(databases_used) if databases_used else "Semantic Scholar / PubMed"
          )
          await _emit("web_search", "completed", f"检索完成 ({source_hint})")
          citation_hint = format_citation_instruction(databases_used or None)
          messages.append({
            "role": "user",
            "content": (
              f"## 学术文献检索结果\n\n"
              f"检索数据库: {source_hint}\n"
              f"检索词: {query}\n\n"
              f"{search_result}\n\n"
              f"{citation_hint}"
            ),
          })
        except Exception as e:
          logger.warning("web_search 失败: %s", e)
          await _emit("web_search", "failed", str(e))

  if "code_interpreter" in tools:
    interpreter = TOOL_REGISTRY.get("code_interpreter")
    if interpreter:
      await _emit("code_interpreter", "started", "样本量与预算估算")
      try:
        analysis = await interpreter.run_for_experiment_context(
          user_input,
          context_outputs or {},
        )
        await _emit("code_interpreter", "completed", "计算完成")
        messages.append({
          "role": "user",
          "content": f"## 实验参数计算结果\n\n{analysis}",
        })
      except Exception as e:
        logger.warning("code_interpreter 失败: %s", e)
        await _emit("code_interpreter", "failed", str(e))

  return messages
