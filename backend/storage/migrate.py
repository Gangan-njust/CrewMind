"""数据库 schema 迁移与 admin 用户初始化"""
import logging

from sqlalchemy import inspect, select, text

from backend.auth import get_user_by_username, hash_password
from backend.config import settings
from backend.storage.database import Base, get_session
from backend.storage.models import CustomAgentRecord, User, WorkflowRecord

logger = logging.getLogger(__name__)


def _column_exists(inspector, table: str, column: str) -> bool:
  return column in {c["name"] for c in inspector.get_columns(table)}


def _table_exists(inspector, table: str) -> bool:
  return table in inspector.get_table_names()


def run_migrations(engine) -> None:
  inspector = inspect(engine)

  with engine.begin() as conn:
    if not _table_exists(inspector, "users"):
      User.__table__.create(bind=conn)
      logger.info("已创建 users 表")

    if _table_exists(inspector, "workflow_records") and not _column_exists(
      inspector, "workflow_records", "user_id"
    ):
      conn.execute(text("ALTER TABLE workflow_records ADD COLUMN user_id VARCHAR(36)"))
      logger.info("已为 workflow_records 添加 user_id 列")

    if _table_exists(inspector, "custom_agents") and not _column_exists(
      inspector, "custom_agents", "user_id"
    ):
      conn.execute(text("ALTER TABLE custom_agents ADD COLUMN user_id VARCHAR(36)"))
      logger.info("已为 custom_agents 添加 user_id 列")

  _ensure_admin_user()
  _migrate_existing_data_to_admin()


def _ensure_admin_user() -> User:
  admin = get_user_by_username("admin")
  if admin:
    return admin

  with get_session() as session:
    admin = User(
      id="00000000-0000-0000-0000-000000000001",
      username="admin",
      password_hash=hash_password(settings.admin_password),
      created_at=__import__("datetime").datetime.now(),
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    logger.info("已创建默认 admin 用户")
    return admin


def _migrate_existing_data_to_admin() -> None:
  admin = get_user_by_username("admin")
  if not admin:
    return

  migrated_records = 0
  migrated_agents = 0

  with get_session() as session:
    for row in session.scalars(
      select(WorkflowRecord).where(WorkflowRecord.user_id.is_(None))
    ).all():
      row.user_id = admin.id
      migrated_records += 1

    for row in session.scalars(
      select(CustomAgentRecord).where(CustomAgentRecord.user_id.is_(None))
    ).all():
      row.user_id = admin.id
      migrated_agents += 1

    if migrated_records or migrated_agents:
      session.commit()
      logger.info(
        "已将 %d 条工作记录、%d 个自定义 Agent 迁移至 admin 用户",
        migrated_records,
        migrated_agents,
      )
