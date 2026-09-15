"""通用响应模型定义

定义全局统一的 API 响应结构、分页信息与错误响应模型。
所有路由成功时返回 ``ApiResponse``，失败时由全局异常处理器返回 ``ErrorResponse``。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    """统一成功响应包装

    - ``code=0`` 表示成功，非 0 表示错误
    - ``message`` 为提示信息
    - ``data`` 为业务数据，任意类型
    """

    code: int = 0
    message: str = "ok"
    data: Any = None


class PaginationInfo(BaseModel):
    """分页信息"""

    page: int = 1
    page_size: int = 20
    total: int = 0


class ErrorResponse(BaseModel):
    """统一错误响应"""

    code: int
    message: str
    data: dict = {}
