"""从任务文本中提取工具调用所需的关键词与查询串"""
import re


def extract_search_query(user_input: str, task_prompt: str) -> str:
  """合并用户输入与任务提示，提取适合学术检索的查询串"""
  combined = f"{user_input.strip()}\n{task_prompt.strip()}"
  lines = [ln.strip() for ln in combined.splitlines() if ln.strip()]

  for line in lines:
    if any(kw in line for kw in ("研究", "课题", "实验", "综述", "诊断", "分析")):
      cleaned = _clean_line(line)
      if len(cleaned) >= 6:
        return cleaned[:150]

  cleaned = _clean_line(combined.replace("\n", " "))
  return cleaned[:150] if cleaned else combined[:120]


def _clean_line(line: str) -> str:
  line = re.sub(r"^#+\s*", "", line)
  line = re.sub(r"^\*+\s*", "", line)
  for prefix in ("研究需求", "用户需求", "课题背景", "背景：", "背景:"):
    if line.startswith(prefix):
      line = line[len(prefix):].strip()
  line = re.sub(r"[「」【】]", "", line)
  return line.strip()
