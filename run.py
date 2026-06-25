"""应用启动入口"""
import uvicorn
from backend.config import settings


def main():
  uvicorn.run(
    "backend.main:app",
    host=settings.app_host,
    port=settings.app_port,
    reload=True,
    log_level=settings.log_level.lower(),
  )


if __name__ == "__main__":
  main()
