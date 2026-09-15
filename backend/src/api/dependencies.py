"""FastAPI 依赖注入

提供数据库会话依赖与当前用户依赖。
"""
from __future__ import annotations

from typing import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import get_session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """获取数据库会话依赖

    每次请求生成独立 Session：
    - 请求成功自动提交
    - 抛出异常自动回滚
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(request: Request) -> dict:
    """获取当前用户依赖

    当前为简易实现，统一返回 guest 用户。
    生产环境应校验 JWT 并返回真实用户信息。
    """
    # 读取 Authorization 头（占位），生产环境需解析 JWT
    # auth = request.headers.get("Authorization")
    return {"user_id": None, "username": "guest"}
