"""工具基类"""
from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
  name: str = "base_tool"
  description: str = "基础工具"

  @abstractmethod
  async def run(self, **kwargs: Any) -> str:
    """执行工具，返回字符串结果"""

  def to_schema(self) -> dict:
    return {"name": self.name, "description": self.description}
