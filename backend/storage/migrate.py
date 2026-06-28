"""数据库 schema 迁移与 admin 用户初始化"""
import logging

from sqlalchemy import inspect, select, text

from backend.auth import get_user_by_username, hash_password
from backend.config import settings
from backend.storage.database import Base, get_session
from backend.storage.models import CustomAgentRecord, TopicRecord, User, WorkflowRecord, WorkflowTemplateRecord

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

    if _table_exists(inspector, "workflow_records") and not _column_exists(
      inspector, "workflow_records", "title"
    ):
      conn.execute(
        text("ALTER TABLE workflow_records ADD COLUMN title VARCHAR(256) DEFAULT ''")
      )
      logger.info("已为 workflow_records 添加 title 列")

    if _table_exists(inspector, "custom_agents") and not _column_exists(
      inspector, "custom_agents", "user_id"
    ):
      conn.execute(text("ALTER TABLE custom_agents ADD COLUMN user_id VARCHAR(36)"))
      logger.info("已为 custom_agents 添加 user_id 列")

    if not _table_exists(inspector, "topics"):
      TopicRecord.__table__.create(bind=conn)
      logger.info("已创建 topics 表")

    if _table_exists(inspector, "workflow_records") and not _column_exists(
      inspector, "workflow_records", "topic_id"
    ):
      conn.execute(text("ALTER TABLE workflow_records ADD COLUMN topic_id VARCHAR(36)"))
      logger.info("已为 workflow_records 添加 topic_id 列")

    if _table_exists(inspector, "workflow_records") and not _column_exists(
      inspector, "workflow_records", "version_number"
    ):
      conn.execute(
        text("ALTER TABLE workflow_records ADD COLUMN version_number INTEGER DEFAULT 1")
      )
      logger.info("已为 workflow_records 添加 version_number 列")

    if not _table_exists(inspector, "workflow_templates"):
      WorkflowTemplateRecord.__table__.create(bind=conn)
      logger.info("已创建 workflow_templates 表")

  _ensure_admin_user()
  _migrate_existing_data_to_admin()
  _backfill_workflow_titles()
  _backfill_topics()


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


def _backfill_workflow_titles() -> None:
  from backend.storage.results import generate_base_title

  updated = 0
  with get_session() as session:
    rows = session.scalars(
      select(WorkflowRecord)
      .where(WorkflowRecord.title == "")
      .order_by(WorkflowRecord.user_id, WorkflowRecord.created_at)
    ).all()
    if not rows:
      return

    seen_by_user: dict[str | None, set[str]] = {}
    for row in rows:
      base_title = generate_base_title(row.user_input, row.scenario)
      seen = seen_by_user.setdefault(row.user_id, set())
      title = base_title
      if base_title in seen:
        title = f"{base_title} ({row.created_at.strftime('%Y-%m-%d %H:%M:%S')})"
      row.title = title
      seen.add(base_title)
      updated += 1

    session.commit()
    logger.info("已为 %d 条历史方案回填标题", updated)


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


def _backfill_topics() -> None:
  """将已有方案按课题归组并分配版本号"""
  from backend.storage.results import compute_topic_key, generate_base_title

  with get_session() as session:
    rows = session.scalars(
      select(WorkflowRecord)
      .where(WorkflowRecord.topic_id.is_(None))
      .order_by(WorkflowRecord.user_id, WorkflowRecord.scenario, WorkflowRecord.created_at)
    ).all()
    if not rows:
      return

    topic_cache: dict[tuple[str | None, str], TopicRecord] = {}
    version_counters: dict[str, int] = {}
    created = 0

    for row in rows:
      if not row.user_id:
        continue
      key = compute_topic_key(row.user_input, row.scenario)
      cache_key = (row.user_id, key)
      topic = topic_cache.get(cache_key)
      if not topic:
        topic = TopicRecord(
          id=str(__import__("uuid").uuid4()),
          user_id=row.user_id,
          scenario=row.scenario,
          title=row.title or generate_base_title(row.user_input, row.scenario),
          topic_key=key,
          user_input=row.user_input,
          best_record_id=None,
          created_at=row.created_at,
          updated_at=row.created_at,
        )
        session.add(topic)
        topic_cache[cache_key] = topic
        version_counters[topic.id] = 0
        created += 1

      version_counters[topic.id] += 1
      row.topic_id = topic.id
      row.version_number = version_counters[topic.id]
      topic.updated_at = row.created_at

    if created:
      session.commit()
      logger.info("已为 %d 条历史方案创建 %d 个课题分组", len(rows), created)
