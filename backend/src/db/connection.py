"""SQLite 异步连接 + SQLAlchemy 2.0 会话管理"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from ..core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


# ============================================================
# Engine & Session 创建
# ============================================================
def _ensure_db_file(sqlite_url: str) -> None:
    """确保 SQLite DB 文件所在目录存在（SQLite 自动建表但不自动建目录）"""
    prefix = "sqlite+aiosqlite:///"
    if sqlite_url.startswith(prefix):
        db_path = sqlite_url[len(prefix):]
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"SQLite DB 目录已准备: {db_file.parent.resolve()}")


def create_engine() -> AsyncEngine:
    """根据配置创建异步 Engine"""
    settings = get_settings()
    _ensure_db_file(settings.SQLITE_URL)

    engine = create_async_engine(
        settings.SQLITE_URL,
        echo=settings.DEBUG,  # DEBUG 模式输出 SQL 日志
        future=True,
        # SQLite 异步驱动专用参数
        connect_args={
            "check_same_thread": False,  # 多线程环境允许
            "timeout": 30,
        },
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    logger.info(f"SQLite Engine created: {settings.SQLITE_URL}")
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """创建 Session 工厂"""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


# ============================================================
# 全局单例（模块加载时延迟初始化，首次访问时创建）
# ============================================================
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(get_engine())
    return _session_factory


# ============================================================
# FastAPI DI：在路由中用 Depends(get_db_session) 获取 Session
# ============================================================
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入用：每次请求生成独立 Session"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.opt(exception=exc).error("DB session 异常，已回滚")
            raise
        finally:
            await session.close()


# ============================================================
# 初始化 / 迁移（开发时自动建表，生产环境请用 Alembic）
# ============================================================
async def init_database() -> None:
    """初始化数据库：创建所有表（开发环境用）"""
    from . import models  # noqa: F401  确保模型被注册到 Base.metadata

    engine = get_engine()
    settings = get_settings()

    if settings.APP_ENV != "prod":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("数据库表初始化完成（非生产环境）")
    else:
        logger.warning("生产环境跳过自动建表，请使用 Alembic 迁移")


async def close_database() -> None:
    """关闭 Engine 连接池（应用退出时调用）"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("数据库连接池已关闭")
        _engine = None
        _session_factory = None
