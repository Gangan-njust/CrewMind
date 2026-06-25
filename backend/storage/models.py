"""工作方案数据库模型"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.storage.database import Base


class User(Base):
  __tablename__ = "users"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
  password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WorkflowRecord(Base):
  __tablename__ = "workflow_records"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  crew_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
  user_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("users.id"), index=True, nullable=True
  )
  scenario: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
  user_input: Mapped[str] = mapped_column(Text, nullable=False)
  created_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
  metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
  tasks_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class CustomAgentRecord(Base):
  __tablename__ = "custom_agents"

  id: Mapped[str] = mapped_column(String(64), primary_key=True)
  user_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("users.id"), index=True, nullable=True
  )
  name: Mapped[str] = mapped_column(String(128), nullable=False)
  title: Mapped[str] = mapped_column(String(256), nullable=False)
  background: Mapped[str] = mapped_column(Text, nullable=False)
  goal: Mapped[str] = mapped_column(Text, nullable=False)
  tools_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  use_reasoning: Mapped[bool] = mapped_column(nullable=False, default=False)
