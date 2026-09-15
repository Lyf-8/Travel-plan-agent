"""健康检查与系统信息路由

提供 ``/health``、``/api/health``、``/api/system/info`` 接口，
用于探活（K8s/负载均衡）与运行时信息查看。
路由无前缀，路径在装饰器中显式声明。
"""
from __future__ import annotations

import platform

from fastapi import APIRouter

from ..schemas.common import ApiResponse
from ...core.config import get_settings

router = APIRouter()


@router.get("/health", response_model=ApiResponse, tags=["meta"])
async def health() -> ApiResponse:
    """健康检查（探活用）"""
    return ApiResponse(data={"status": "ok"})


@router.get("/api/health", response_model=ApiResponse, tags=["meta"])
async def api_health() -> ApiResponse:
    """API 健康检查"""
    return ApiResponse(data={"status": "ok"})


@router.get("/api/system/info", response_model=ApiResponse, tags=["meta"])
async def system_info() -> ApiResponse:
    """系统信息：Python 版本、向量库后端、运行环境等"""
    settings = get_settings()
    info = {
        "app_name": settings.APP_NAME,
        "app_env": settings.APP_ENV,
        "debug": settings.DEBUG,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "vector_db_backend": settings.VECTOR_DB_BACKEND,
        "llm_strategy": settings.LLM_STRATEGY,
        "openai_model": settings.OPENAI_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL_NAME,
    }
    return ApiResponse(data=info)
