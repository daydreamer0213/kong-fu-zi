import secrets
import warnings

from pydantic import field_validator
from pydantic_settings import BaseSettings

_DEFAULT_SECRET = "changeme"  # 默认值短且明显——启动时检测到会告警


class Settings(BaseSettings):
    """应用配置，从 .env 文件和环境变量中读取"""

    # DeepSeek API
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"

    # 数据库 (SQLite)
    database_url: str = "sqlite:///./data/kong.db"

    # 向量库 (ChromaDB)
    chroma_persist_dir: str = "./data/chroma"

    # BGE 模型存储目录
    model_cache_dir: str = "E:/ai-models"

    # HuggingFace 镜像
    hf_endpoint: str = "https://hf-mirror.com"

    # Tavily 联网搜索
    tavily_api_key: str = ""

    # JWT 认证
    jwt_secret: str = _DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7天过期

    @field_validator("deepseek_api_key")
    @classmethod
    def check_api_key(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("DEEPSEEK_API_KEY 未设置，请在 .env 中配置")
        return v.strip()

    def validate_jwt_secret(self):
        if self.jwt_secret == _DEFAULT_SECRET:
            warnings.warn(
                "WARNING: JWT 密钥使用默认值，生产环境请设置 JWT_SECRET 环境变量！",
                RuntimeWarning,
            )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
settings.validate_jwt_secret()
