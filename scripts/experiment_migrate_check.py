"""迁移冒烟测试：验证旧库 schema 升级时新增列/表是否正确"""
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import create_engine

from backend.storage.migrate import run_migrations


def main():
  tmp = Path(tempfile.mkdtemp())
  db_path = tmp / "app.db"
  # 模拟旧版 experiments 表（无 config_json/progress/current_step/steps_json）
  conn = sqlite3.connect(db_path)
  conn.executescript(
    """
    CREATE TABLE users (
      id VARCHAR(36) PRIMARY KEY, username VARCHAR(64) UNIQUE,
      password_hash VARCHAR(128), created_at DATETIME
    );
    CREATE TABLE experiments (
      id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), title VARCHAR(256),
      description TEXT, source_workflow_id VARCHAR(36),
      expected_metrics_json TEXT, status VARCHAR(32),
      created_at DATETIME, updated_at DATETIME
    );
    """
  )
  conn.commit()
  conn.close()

  engine = create_engine(f"sqlite:///{db_path.as_posix()}")
  run_migrations(engine)

  conn = sqlite3.connect(db_path)
  cols = {row[1] for row in conn.execute("PRAGMA table_info(experiments)")}
  tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  conn.close()

  for col in ("config_json", "progress", "current_step", "steps_json"):
    assert col in cols, f"缺少列: {col}"
  for table in ("experiment_metrics", "experiment_files"):
    assert table in tables, f"缺少表: {table}"
  print("migration smoke test OK")
  print("experiments cols:", sorted(cols))
  print("new tables:", sorted(t for t in tables if "experiment" in t))


if __name__ == "__main__":
  main()
