"""安全代码解释器：用于实验设计中的样本量与预算估算"""
import logging
import math
import re
import statistics
from typing import Any

from backend.tools.base import BaseTool

logger = logging.getLogger(__name__)

_SAFE_BUILTINS: dict[str, Any] = {
  "abs": abs,
  "min": min,
  "max": max,
  "sum": sum,
  "len": len,
  "range": range,
  "round": round,
  "int": int,
  "float": float,
  "str": str,
  "list": list,
  "dict": dict,
  "tuple": tuple,
  "enumerate": enumerate,
  "zip": zip,
  "bool": bool,
  "print": print,
}

_SAFE_GLOBALS: dict[str, Any] = {
  "__builtins__": _SAFE_BUILTINS,
  "math": math,
  "statistics": statistics,
  "re": re,
}

_EXPERIMENT_ANALYSIS_CODE = """
lines = []
text = context_text

for m in re.finditer(r"(\\d+)\\s*人", text):
    lines.append(f"检测到人数相关描述: {m.group(1)} 人")

for m in re.finditer(r"(\\d+(?:\\.\\d+)?)\\s*万", text):
    wan = float(m.group(1))
    lines.append(f"预算约 {wan} 万元（≈ {wan * 10000:.0f} 元）")

for m in re.finditer(r"(\\d+)\\s*个月", text):
    months = int(m.group(1))
    lines.append(f"研究周期: {months} 个月（约 {months / 12:.1f} 年）")

people = [int(m.group(1)) for m in re.finditer(r"(\\d+)\\s*人", text)]
if people:
    total = max(people)
    per_group = max(total // 2, 1)
    lines.append(f"若随机分为两组，每组约 {per_group} 人")
    if per_group < 30:
        lines.append(
            "统计提示: 每组少于 30 人可能降低检验效力，建议进行功效分析或扩大样本"
        )
    elif per_group >= 64:
        lines.append(
            "统计提示: 样本量对中等效应量（Cohen's d≈0.5）可能具有较好统计效力"
        )

# 两组均值比较样本量近似（α=0.05, power=0.8, d=0.5）
if people:
    d = 0.5
    alpha = 0.05
    power = 0.8
    z_alpha = 1.96
    z_beta = 0.84
    n_per_group = math.ceil(((z_alpha + z_beta) ** 2 * 2) / (d ** 2))
    lines.append(
        f"参考功效分析: 中等效应量 d=0.5 时，每组约需 {n_per_group} 人（α=0.05, power=0.8）"
    )

result = "\\n".join(lines) if lines else "未从文本中提取到可计算的实验参数，请人工补充样本量与预算分析"
"""


class CodeInterpreterTool(BaseTool):
  name = "code_interpreter"
  description = "在安全沙箱中执行 Python 计算，用于样本量估算与预算分析"

  async def run(
    self,
    code: str = "",
    context_vars: dict[str, Any] | None = None,
    **_,
  ) -> str:
    if not code:
      return "错误：请提供代码"

    local_vars: dict[str, Any] = dict(context_vars or {})
    try:
      exec(code, _SAFE_GLOBALS, local_vars)
      if "result" in local_vars:
        return str(local_vars["result"])
      return "代码执行完成，未定义 result 变量"
    except Exception as e:
      logger.warning("代码执行错误: %s", e)
      return f"代码执行错误: {e}"

  async def run_for_experiment_context(
    self,
    user_input: str,
    task_context: dict[str, str],
  ) -> str:
    combined = user_input.strip()
    if task_context:
      combined += "\n" + "\n".join(task_context.values())
    return await self.run(
      code=_EXPERIMENT_ANALYSIS_CODE,
      context_vars={"context_text": combined},
    )
