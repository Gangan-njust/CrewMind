"""应用全局配置"""
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend/ 的上级），确保无论从哪启动都能读到 .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# 显式加载 .env（在 Settings 初始化之前）
load_dotenv(ENV_FILE, override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_reasoning_model: str = "deepseek-reasoner"

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    max_iterations: int = 3
    default_temperature: float = 0.7

    data_dir: Path = Path("./data")
    results_dir: Path = Path("./data/results")
    uploads_dir: Path = Path("./data/uploads")
    database_url: str = ""

    # Semantic Scholar API Key（可选，可提高检索速率限制）
    semantic_scholar_api_key: str = ""

    # 用户认证
    jwt_secret: str = "change-me-in-production"
    admin_password: str = "admin123"

    def get_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = (PROJECT_ROOT / self.data_dir / "app.db").resolve()
        return f"sqlite:///{db_path.as_posix()}"

    def ensure_dirs(self) -> None:
        (PROJECT_ROOT / self.data_dir).mkdir(parents=True, exist_ok=True)
        (PROJECT_ROOT / self.results_dir).mkdir(parents=True, exist_ok=True)
        (PROJECT_ROOT / self.uploads_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
