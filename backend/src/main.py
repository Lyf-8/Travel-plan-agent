"""FastAPI 应用入口

职责：
    1. 创建 FastAPI 实例、挂载中间件、注册全局异常处理器
    2. 启动生命周期（lifespan）中完成：
        - 日志初始化
        - SQLite 表初始化（create_all）
        - 向量库 collection 就绪
    3. 挂载路由（api/routers 下的 chat / itinerary / health）
    4. 暴露配置预览接口

运行：
    cd backend
    uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

import contextlib
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from .core.config import get_settings
from .core.exceptions import AppBaseError, app_base_error_handler, global_exception_handler
from .core.logger import setup_logger
from .db.connection import close_database, init_database
from .rag.retriever import get_retriever


# ============================================================
# Lifespan
# ============================================================
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用启动/关闭生命周期钩子"""
    settings = get_settings()

    # ---- 1. 日志初始化 ----
    setup_logger()
    logger.info(f"启动 {settings.APP_NAME} - env={settings.APP_ENV} port={settings.APP_PORT}")

    # ---- 2. DB 初始化 ----
    try:
        await init_database()
        logger.info("SQLite 初始化完成 (表已创建)")
    except Exception as e:  # noqa: BLE001
        logger.error(f"SQLite 初始化失败: {e}")
        raise

    # ---- 3. 向量库预热 ----
    # 开发时可通过 SKIP_RAG_INIT=1 跳过模型加载，加快启动
    import os
    if os.getenv("SKIP_RAG_INIT", "0") == "1":
        logger.info("跳过向量库预热（SKIP_RAG_INIT=1），首次使用 RAG 时延迟初始化")
    else:
        try:
            retriever = get_retriever()
            await retriever.ensure_ready()
            logger.info(f"向量库就绪: backend={retriever.store.backend_name}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"向量库初始化跳过（本地开发可忽略）: {e}")

    logger.info("应用启动完成，等待请求...")

    yield  # --- 应用启动完毕，开始服务 ---

    # ---- 关闭 ----
    logger.info("正在关闭应用...")
    await close_database()
    logger.info("应用已关闭")


# ============================================================
# FastAPI 实例
# ============================================================
_settings = get_settings()

app = FastAPI(
    title=_settings.APP_NAME,
    description="AI Travel Planner - 基于多 Agent 协作的旅行规划系统",
    version="0.1.0",
    debug=_settings.DEBUG,
    lifespan=lifespan,
)

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 全局异常处理器 ----------
app.add_exception_handler(AppBaseError, app_base_error_handler)
app.add_exception_handler(Exception, global_exception_handler)


# ============================================================
# 挂载路由
# ============================================================
from .api.routers.chat import router as chat_router  # noqa: E402
from .api.routers.health import router as health_router  # noqa: E402
from .api.routers.itinerary import router as itinerary_router  # noqa: E402
from .api.routers.share import router as share_router  # noqa: E402
from .api.routers.stream import router as stream_router  # noqa: E402

app.include_router(health_router, tags=["meta"])
app.include_router(chat_router, tags=["对话"])
app.include_router(itinerary_router, tags=["行程"])
app.include_router(share_router, tags=["分享"])
app.include_router(stream_router, tags=["流式对话"])


# ============================================================
# 基础接口
# ============================================================
@app.get("/", tags=["meta"])
async def index() -> dict:
    s = get_settings()
    return {
        "name": s.APP_NAME,
        "version": app.version,
        "env": s.APP_ENV,
        "debug": s.DEBUG,
        "vector_backend": s.VECTOR_DB_BACKEND,
    }


@app.get("/api/config/preview", tags=["meta"])
async def config_preview() -> dict:
    """预览当前生效的非敏感配置（方便联调排错）"""
    s = get_settings()
    safe = {
        "APP_NAME": s.APP_NAME,
        "APP_ENV": s.APP_ENV,
        "DEBUG": s.DEBUG,
        "LLM_STRATEGY": s.LLM_STRATEGY,
        "OPENAI_MODEL": s.OPENAI_MODEL,
        "OPENAI_HAS_KEY": bool(s.OPENAI_API_KEY),
        "DASHSCOPE_MODEL": s.DASHSCOPE_MODEL,
        "DASHSCOPE_HAS_KEY": bool(s.DASHSCOPE_API_KEY),
        "EMBEDDING_MODEL_NAME": s.EMBEDDING_MODEL_NAME,
        "EMBEDDING_DEVICE": s.EMBEDDING_DEVICE,
        "VECTOR_DB_BACKEND": s.VECTOR_DB_BACKEND,
        "CHROMA_PERSIST_DIR": s.CHROMA_PERSIST_DIR,
        "QDRANT_HOST": s.QDRANT_HOST,
        "QDRANT_PORT": s.QDRANT_PORT,
        "AMAP_HAS_KEY": bool(s.AMAP_KEY),
        "SQLITE_URL": s.SQLITE_URL,
        "RAG_TOP_K": s.RAG_TOP_K,
        "RAG_CACHE_TTL": s.RAG_CACHE_TTL,
    }
    return safe
