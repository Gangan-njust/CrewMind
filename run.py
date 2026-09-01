"""应用启动入口"""
import os

import uvicorn

from backend.config import PROJECT_ROOT, settings


def main():
  # 仅监视代码目录，避免 data/ 内 SQLite、Chroma 写入触发无限 reload
  reload = os.environ.get("CREW_RELOAD", "true").lower() in ("1", "true", "yes")
  uvicorn.run(
    "backend.main:app",
    host=settings.app_host,
    port=settings.app_port,
    reload=reload,
    reload_dirs=[
      str((PROJECT_ROOT / "backend").resolve()),
      str((PROJECT_ROOT / "frontend" / "src").resolve()),
    ],
    reload_excludes=[
      "data/*",
      "*.db",
      "*.sqlite",
      ".git/*",
      "**/__pycache__/*",
      "**/.pytest_cache/*",
    ],
    log_level=settings.log_level.lower(),
  )


if __name__ == "__main__":
  main()
