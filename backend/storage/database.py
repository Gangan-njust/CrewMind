"""数据库连接与初始化"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import settings

_engine = None
SessionLocal: sessionmaker | None = None
_initialized = False


class Base(DeclarativeBase):
  pass


def setup_database() -> None:
  global _engine, SessionLocal, _initialized
  if _initialized:
    return

  settings.ensure_dirs()
  _engine = create_engine(
    settings.get_database_url(),
    connect_args={"check_same_thread": False},
  )
  SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

  from backend.storage.models import (  # noqa: F401
    CustomAgentRecord,
    TopicRecord,
    User,
    WorkflowRecord,
    WorkflowTemplateRecord,
  )

  Base.metadata.create_all(bind=_engine)

  from backend.storage.migrate import run_migrations

  run_migrations(_engine)
  _initialized = True


def get_session():
  if not SessionLocal:
    setup_database()
  return SessionLocal()
