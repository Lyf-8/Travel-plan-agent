"""全局自定义异常类 + FastAPI 异常处理器"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel


# ============================================================
# 1. 自定义异常
# ============================================================
class AppBaseError(Exception):
    """应用级基类异常"""
    code: int = 1000
    status_code: int = 500
    message: str = "Internal Server Error"

    def __init__(self, message: str | None = None, data: dict | None = None) -> None:
        if message is not None:
            self.message = message
        self.data = data or {}
        super().__init__(self.message)


class ConfigError(AppBaseError):
    """配置缺失/错误"""
    code = 1001
    status_code = 500
    message = "配置错误"


class LLMCallError(AppBaseError):
    """LLM 调用失败"""
    code = 2001
    status_code = 502
    message = "大模型调用失败"


class LLMRateLimitError(LLMCallError):
    """LLM 限流"""
    code = 2002
    status_code = 429
    message = "大模型请求频率超限"


class LLMTimeoutError(LLMCallError):
    """LLM 超时"""
    code = 2003
    status_code = 504
    message = "大模型调用超时"


class ToolCallError(AppBaseError):
    """外部工具调用失败"""
    code = 3001
    status_code = 502
    message = "工具调用失败"


class AmapAPIError(ToolCallError):
    """高德 API 调用失败"""
    code = 3002
    status_code = 502
    message = "高德地图 API 调用失败"


class RAGError(AppBaseError):
    """RAG 相关错误"""
    code = 4001
    status_code = 500
    message = "知识库检索失败"


class ValidationError(AppBaseError):
    """业务校验失败"""
    code = 40001
    status_code = 400
    message = "参数校验失败"


class ResourceNotFound(AppBaseError):
    """资源不存在"""
    code = 40401
    status_code = 404
    message = "资源不存在"


# ============================================================
# 2. 统一响应结构
# ============================================================
class ErrorResponse(BaseModel):
    code: int
    message: str
    data: dict = {}


def make_error_response(exc: AppBaseError) -> dict:
    return ErrorResponse(code=exc.code, message=exc.message, data=exc.data).model_dump()


# ============================================================
# 3. FastAPI 异常处理器（在 main.py 中注册）
# ============================================================
async def app_base_error_handler(request: Request, exc: AppBaseError) -> JSONResponse:
    """处理所有 AppBaseError 子类"""
    logger.opt(exception=exc).warning(
        f"[Exception] code={exc.code} status={exc.status_code} msg={exc.message}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=make_error_response(exc),
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理器"""
    logger.opt(exception=exc).error(f"[Unhandled] {type(exc).__name__}: {exc}")
    err = AppBaseError(message=str(exc) if True else "Internal Server Error")
    return JSONResponse(
        status_code=500,
        content=make_error_response(err),
    )
