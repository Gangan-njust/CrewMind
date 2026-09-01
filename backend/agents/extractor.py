"""从任意角色描述/提示词中提取结构化 Agent 字段"""
import json
import re

from backend.agents.prompt_parser import (
  merge_extracted_fields,
  normalize_pasted_prompt,
  parse_markdown_agent_prompt,
)
from backend.agents.registry import VALID_TOOLS, validate_tools
from backend.llm.client import llm_client

MAX_PROMPT_CHARS = 50000

EXTRACT_AGENT_PROMPT = """你是一名 Agent 角色配置助手。用户将粘贴一段角色描述、系统提示词或 Agent 定义，**常见为 Markdown 格式**（# 标题、## 小节、列表、粗体等），请理解其结构与语义并提取为 CrewMind 自定义 Agent 字段。

## Markdown 解析提示
- 「## 专业背景」「## 背景」「## Backstory」等小节内容 → background
- 「## 核心目标」「## 目标」「## Goal」等小节内容 → goal
- 「你是一位专业的……」首句 → title
- 「## 可用工具」「## Tools」列表或正文提及的工具 → tools
- 一级标题 `# 角色名` 或文首角色称谓 → name
- background / goal 若原文含 Markdown 列表或强调，可保留为 Markdown 文本

## 可用工具（tools 字段只能从中选择，无合适工具则返回空数组）
- web_search：学术文献检索
- file_parser：参考文件解析
- code_interpreter：样本量与预算计算
- rag_search：本地文献库检索

## 提取规则
1. name：简短中文角色名（2-20 字），如「文献调研专家」
2. title：职称或专业头衔，比 name 更完整
3. background：专业背景与能力描述，保留关键信息，至少 30 字；若原文较长请归纳，但保留 Markdown 列表结构
4. goal：该角色在工作流中的核心职责与输出目标，至少 30 字
5. tools：根据角色职责推断需要的工具 ID，不要臆造未列出的工具
6. use_reasoning：是否需要深度推理（实验设计、复杂终审类角色为 true，一般角色为 false）
7. id：可选，英文 snake_case 角色 ID；无法合理推断则省略

## 输出要求
仅输出 JSON 对象，不要 markdown 代码块或解释：
{{"name":"...","title":"...","background":"...","goal":"...","tools":[],"use_reasoning":false}}

## 用户粘贴内容
__USER_PROMPT__
"""


def _parse_json_response(text: str) -> dict:
  text = text.strip()
  if text.startswith("```"):
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
  try:
    return json.loads(text)
  except json.JSONDecodeError:
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
      return json.loads(match.group(0))
    raise ValueError(f"无法解析 LLM JSON 输出: {text[:200]}")


def _normalize_extracted(data: dict) -> dict:
  name = str(data.get("name") or "").strip()
  title = str(data.get("title") or "").strip()
  background = str(data.get("background") or "").strip()
  goal = str(data.get("goal") or "").strip()

  if not name and title:
    name = title[:20]
  if not title and name:
    title = name

  tools_raw = data.get("tools") or []
  if isinstance(tools_raw, str):
    tools_raw = [t.strip() for t in re.split(r"[,，、\s]+", tools_raw) if t.strip()]
  if not isinstance(tools_raw, list):
    tools_raw = []
  tools = [str(t).strip() for t in tools_raw if str(t).strip()]
  validate_tools(tools)

  use_reasoning = bool(data.get("use_reasoning", False))

  agent_id = data.get("id")
  if agent_id is not None:
    agent_id = str(agent_id).strip() or None

  if not name or not title or len(background) < 10 or len(goal) < 10:
    raise ValueError("未能从内容中提取完整的角色信息，请补充描述后重试")

  result = {
    "name": name[:128],
    "title": title[:256],
    "background": background,
    "goal": goal,
    "tools": tools,
    "use_reasoning": use_reasoning,
  }
  if agent_id:
    result["id"] = agent_id
  return result


async def extract_agent_from_prompt(prompt: str) -> dict:
  text = normalize_pasted_prompt(prompt)
  if len(text) < 10:
    raise ValueError("粘贴内容过短，请提供更完整的角色描述")
  if len(text) > MAX_PROMPT_CHARS:
    text = text[:MAX_PROMPT_CHARS]

  markdown_data = parse_markdown_agent_prompt(text)

  llm_prompt = EXTRACT_AGENT_PROMPT.replace("__USER_PROMPT__", text)
  response = await llm_client.chat(
    [{"role": "user", "content": llm_prompt}],
    temperature=0.2,
  )
  if hasattr(response, "__aiter__"):
    chunks = []
    async for chunk in response:
      chunks.append(chunk)
    response = "".join(chunks)

  llm_data = _parse_json_response(str(response))
  if not isinstance(llm_data, dict):
    raise ValueError("模型返回格式无效")

  data = merge_extracted_fields(markdown_data, llm_data)
  return _normalize_extracted(data)
