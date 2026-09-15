"""全局配置管理 - 使用 pydantic-settings 从 .env 加载"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，优先级：显式传入 > 环境变量 > .env 文件 > 默认值"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---------- 服务配置 ----------
    APP_NAME: str = Field(default="AI-Travel-Planner", description="应用名")
    APP_ENV: str = Field(default="dev", description="运行环境: dev / test / prod")
    APP_HOST: str = Field(default="0.0.0.0", description="监听地址")
    APP_PORT: int = Field(default=8000, description="监听端口")
    DEBUG: bool = Field(default=True, description="调试模式")

    # ---------- LLM - OpenAI ----------
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API Key")
    OPENAI_BASE_URL: str = Field(
        default="https://api.openai.com/v1", description="OpenAI Base URL"
    )
    OPENAI_MODEL: str = Field(default="gpt-4o-mini", description="默认模型")
    OPENAI_EMBEDDING_MODEL: str = Field(
        default="text-embedding-3-small", description="OpenAI Embedding 模型"
    )
    OPENAI_TEMPERATURE: float = Field(default=0.3, description="采样温度")
    OPENAI_MAX_TOKENS: int = Field(default=4096, description="单次最大输出 tokens")

    # ---------- LLM - 阿里 DashScope (千问备选) ----------
    DASHSCOPE_API_KEY: Optional[str] = Field(default=None, description="DashScope API Key")
    DASHSCOPE_MODEL: str = Field(default="qwen-plus", description="千问模型名")
    DASHSCOPE_BASE_URL: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="DashScope 兼容 OpenAI 的 Endpoint",
    )

    # ---------- LLM 上下文压缩 ----------
    CONTEXT_MAX_TOKENS: int = Field(
        default=30720, description="上下文压缩前的最大 tokens 阈值（约 30K），超出触发压缩"
    )
    SUMMARY_TARGET_TOKENS: int = Field(
        default=6144, description="上下文压缩后的目标 tokens 上限（约 6K，80% 压缩率）"
    )

    # ---------- 多模型降级策略 ----------
    LLM_STRATEGY: str = Field(
        default="primary_fallback",
        description="primary_only / primary_fallback / round_robin",
    )

    # ---------- Embedding 本地模型 ----------
    EMBEDDING_MODEL_NAME: str = Field(
        default="BAAI/bge-small-zh-v1.5", description="HuggingFace 本地 Embedding 模型名"
    )
    EMBEDDING_DEVICE: str = Field(default="cpu", description="cpu / cuda")
    EMBEDDING_BATCH_SIZE: int = Field(default=32, description="批处理大小")

    # ---------- Qdrant 向量库 ----------
    QDRANT_HOST: str = Field(default="localhost", description="Qdrant Host")
    QDRANT_PORT: int = Field(default=6333, description="Qdrant gRPC/HTTP Port")
    QDRANT_API_KEY: Optional[str] = Field(default=None, description="Qdrant API Key (可选)")
    QDRANT_COLLECTION_NAME: str = Field(
        default="travel_knowledge", description="Qdrant Collection 名"
    )
    QDRANT_VECTOR_SIZE: int = Field(default=512, description="向量维度 (bge-small-zh 是 512)")

    # ---------- ChromaDB 备选 ----------
    CHROMA_PERSIST_DIR: str = Field(
        default="./data/chroma", description="ChromaDB 持久化目录"
    )
    CHROMA_COLLECTION_NAME: str = Field(
        default="travel_knowledge", description="ChromaDB Collection 名"
    )
    VECTOR_DB_BACKEND: str = Field(
        default="chroma", description="向量库后端: qdrant / chroma"
    )

    # ---------- 高德地图 ----------
    AMAP_KEY: Optional[str] = Field(default=None, description="高德 Web 服务 Key")
    AMAP_SECURITY_CODE: Optional[str] = Field(default=None, description="高德 JS API 安全密钥")
    AMAP_BASE_URL: str = Field(
        default="https://restapi.amap.com/v3", description="高德 Web 服务 Base URL"
    )
    AMAP_TIMEOUT: int = Field(default=10, description="高德 API 超时 (秒)")

    # ---------- 数据库 ----------
    SQLITE_URL: str = Field(
        default="sqlite+aiosqlite:///./data/sqlite/app.db", description="SQLite URL (异步)"
    )

    # ---------- 安全 ----------
    API_SECRET_KEY: str = Field(default="dev-secret-change-me", description="API 签名密钥")
    CORS_ORIGINS: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"],
        description="CORS 允许来源 (JSON 列表)",
    )

    # ---------- 日志 ----------
    LOG_LEVEL: str = Field(default="INFO", description="DEBUG / INFO / WARNING / ERROR")
    LOG_DIR: str = Field(default="./logs", description="日志输出目录")
    LOG_ROTATION: str = Field(default="50 MB", description="日志轮转大小")
    LOG_RETENTION: str = Field(default="7 days", description="日志保留时长")

    # ---------- 缓存 ----------
    RAG_CACHE_TTL: int = Field(default=3600, description="RAG 缓存 TTL (秒)")
    RAG_TOP_K: int = Field(default=5, description="RAG 检索 Top-K")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例获取全局配置（带缓存）"""
    return Settings()
