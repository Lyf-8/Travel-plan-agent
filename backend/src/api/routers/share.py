"""行程分享路由

提供分享短链接的创建与访问接口。
前缀：``/api/share``

- POST /api/share           创建分享链接
- GET  /api/share/{code}    根据短码获取快照数据
- GET  /api/share/go/{code} 跳转到前端分享页（可选）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db
from ..schemas.common import ApiResponse
from ...core.exceptions import ResourceNotFound, ValidationError
from ...db.repositories import Repositories
from ...services.share_service import get_share_service

router = APIRouter(prefix="/api/share")


# ============================================================
# Pydantic Schemas
# ============================================================
class CreateShareRequest(BaseModel):
    """创建分享链接请求体"""

    session_id: str = Field(..., description="会话 UUID")
    version_id: Optional[int] = Field(
        default=None, description="指定行程版本 ID（为空取当前版本）"
    )
    expire_days: int = Field(default=30, ge=1, le=365, description="有效天数，1-365")


class CreateShareResponse(BaseModel):
    """创建分享链接响应"""

    short_code: str
    share_url: str
    expire_at: Optional[str] = None


class ShareSnapshotResponse(BaseModel):
    """分享快照响应"""

    share_snapshot: Any
    view_count: int
    session_id: Optional[str] = None
    version_id: Optional[int] = None
    created_at: Optional[str] = None
    expire_at: Optional[str] = None


# ============================================================
# Helper
# ============================================================
async def _ensure_session_exists(
    repos: Repositories, session_id: str
) -> None:
    session = await repos.sessions.get_by_session_id(session_id)
    if session is None:
        raise ResourceNotFound(message=f"会话不存在: {session_id}")


# ============================================================
# API Endpoints
# ============================================================
@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED, tags=["分享"])
async def create_share_link(
    body: CreateShareRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """创建行程分享短链接"""
    logger.info(
        f"创建分享链接: path={request.url.path} session={body.session_id} "
        f"version_id={body.version_id} expire_days={body.expire_days}"
    )
    repos = Repositories(db)
    await _ensure_session_exists(repos, body.session_id)

    service = get_share_service()
    try:
        result = await service.create_share_link(
            session_id=body.session_id,
            version_id=body.version_id,
            expire_days=body.expire_days,
        )
    except (ResourceNotFound, ValidationError):
        raise
    except Exception as exc:
        logger.opt(exception=exc).error(f"创建分享链接失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建分享链接失败: {exc}",
        )

    resp = CreateShareResponse(**result)
    return ApiResponse(data=resp.model_dump(mode="json"))


@router.get("/{short_code}", response_model=ApiResponse, tags=["分享"])
async def get_share_snapshot(
    short_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """根据短码获取分享快照数据（浏览次数 +1）"""
    logger.info(
        f"访问分享快照: path={request.url.path} code={short_code}"
    )
    service = get_share_service()
    try:
        result = await service.get_share_snapshot(short_code)
    except ResourceNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="分享链接不存在或已过期",
        )
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的短码",
        )
    except Exception as exc:
        logger.opt(exception=exc).error(f"获取分享快照失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取分享快照失败: {exc}",
        )

    resp = ShareSnapshotResponse(**result)
    return ApiResponse(data=resp.model_dump(mode="json"))


@router.get("/go/{short_code}", include_in_schema=False)
async def redirect_to_frontend_share_page(short_code: str) -> RedirectResponse:
    """将短链接访问重定向到前端分享落地页

    用法：外部访问 http://host/api/share/go/xxx → 跳前端 /#/share/xxx
    （因为路由可能有冲突，这里路径单独用 /go/ 前缀，与 /{code} 不冲突）
    """
    return RedirectResponse(url=f"/#/share/{short_code}")
