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

    # LLM 调用失败自动重试（网络错误、限流 429、5xx 等瞬时故障）
    llm_max_retries: int = 2
    llm_retry_backoff: float = 1.5

    data_dir: Path = Path("./data")
    results_dir: Path = Path("./data/results")
    uploads_dir: Path = Path("./data/uploads")
    literature_dir: Path = Path("./data/literature")
    experiment_dir: Path = Path("./data/experiments")
    database_url: str = ""
    literature_analysis_concurrency: int = 3
    crew_task_concurrency: int = 3

    # RAG 检索增强
    rag_enabled: bool = True
    rag_dir: Path = Path("./data/rag")
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_provider: str = "fastembed"  # fastembed | openai
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    chunk_size: int = 600
    chunk_overlap: int = 120
    rag_top_k: int = 8
    rag_rerank_top_k: int = 5
    rag_rerank_enabled: bool = True
    rag_rerank_model: str = "BAAI/bge-reranker-base"
    rag_section_boost: bool = True
    rag_index_concurrency: int = 2
    rag_index_max_retries: int = 2
    # 语义辅助切块（段落合并决策引入 embedding 相似度信号，默认关闭）
    rag_semantic_chunking: bool = False
    rag_semantic_min_sim: float = 0.50   # 相邻段落相似度低于该值时强制切分
    rag_semantic_max_sim: float = 0.82   # 相邻段落相似度高于该值时允许超限合并
    rag_semantic_max_ratio: float = 1.30  # 语义合并允许的最大超限比例（相对 chunk_size）
    # HuggingFace 模型下载（fastembed embedding / rerank）
    hf_endpoint: str = "https://hf-mirror.com"
    hf_hub_download_timeout: int = 300

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
        (PROJECT_ROOT / self.literature_dir).mkdir(parents=True, exist_ok=True)
        (PROJECT_ROOT / self.experiment_dir).mkdir(parents=True, exist_ok=True)
        (PROJECT_ROOT / self.rag_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
