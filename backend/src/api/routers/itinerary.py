"""行程路由

提供行程查询（当前版本/历史版本列表/指定版本）、反馈提交、重生成接口。
前缀：``/api/itinerary``

- 查询类接口通过 ``Repositories`` 读取，保证返回完整的版本与明细数据
- 反馈与重生成通过 ``FeedbackService`` 完成业务逻辑
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_current_user, get_db
from ..schemas.common import ApiResponse
from ..schemas.itinerary import (
    FeedbackRequest,
    FeedbackResponse,
    ItineraryItemSchema,
    ItineraryVersionSchema,
    RegenerateRequest,
    RegenerateResponse,
    VersionListItem,
)
from ...core.exceptions import ResourceNotFound
from ...db.repositories import Repositories
from ...services.feedback_service import get_feedback_service

router = APIRouter(prefix="/api/itinerary")


async def _get_session_or_404(repos: Repositories, session_id: str) -> None:
    """校验会话存在，不存在则抛出 ResourceNotFound"""
    session = await repos.sessions.get_by_session_id(session_id)
    if session is None:
        raise ResourceNotFound(message=f"会话不存在: {session_id}")


def _build_version_schema(version, items) -> dict:
    """将版本 ORM + 明细列表转换为 ItineraryVersionSchema 字典"""
    items_data = [
        ItineraryItemSchema.model_validate(it, from_attributes=True).model_dump(mode="json")
        for it in items
    ]
    # 从 raw_output 中提取 budget_breakdown 和 weather_info
    raw = version.raw_output if isinstance(version.raw_output, dict) else {}
    budget_breakdown = raw.get("budget_breakdown") or None
    weather_info = raw.get("weather") or None

    schema = ItineraryVersionSchema(
        version=version.version,
        trigger=version.trigger,
        total_budget=version.total_budget,
        total_distance_km=version.total_distance_km,
        map_data=version.map_data,
        budget_breakdown=budget_breakdown,
        weather_info=weather_info,
        raw_output=version.raw_output,
        is_current=version.is_current,
        created_at=version.created_at,
        items=items_data,
    )
    return schema.model_dump(mode="json")


@router.get("/{session_id}", response_model=ApiResponse, tags=["行程"])
async def get_current_itinerary(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """获取当前行程版本（含明细）"""
    repos = Repositories(db)
    await _get_session_or_404(repos, session_id)

    version = await repos.versions.get_current(session_id)
    if version is None:
        raise ResourceNotFound(message=f"会话 {session_id} 暂无行程版本")
    items = await repos.items.list_by_version(version.id)
    return ApiResponse(data=_build_version_schema(version, items))


@router.get("/{session_id}/versions", response_model=ApiResponse, tags=["行程"])
async def list_versions(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """获取会话所有版本列表"""
    repos = Repositories(db)
    await _get_session_or_404(repos, session_id)

    versions = await repos.versions.list_by_session(session_id)
    data = [
        VersionListItem(
            version=v.version,
            trigger=v.trigger,
            is_current=v.is_current,
            created_at=v.created_at,
        ).model_dump(mode="json")
        for v in versions
    ]
    return ApiResponse(data=data)


@router.get(
    "/{session_id}/versions/{version}",
    response_model=ApiResponse,
    tags=["行程"],
)
async def get_version(
    session_id: str,
    version: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """获取指定版本行程（含明细）"""
    repos = Repositories(db)
    await _get_session_or_404(repos, session_id)

    ver = await repos.versions.get_by_version(session_id, version)
    if ver is None:
        raise ResourceNotFound(
            message=f"版本不存在: session={session_id} version={version}"
        )
    items = await repos.items.list_by_version(ver.id)
    return ApiResponse(data=_build_version_schema(ver, items))


@router.post(
    "/{session_id}/feedback",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["行程"],
)
async def submit_feedback(
    session_id: str,
    body: FeedbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> JSONResponse:
    """提交反馈（评分/评论/修改指令）"""
    logger.info(
        f"提交反馈: path={request.url.path} session={session_id} "
        f"version_id={body.version_id} rating={body.rating}"
    )
    repos = Repositories(db)
    await _get_session_or_404(repos, session_id)

    service = get_feedback_service()
    result = await service.submit_feedback(
        session_id=session_id,
        version_id=body.version_id,
        rating=body.rating,
        comment=body.comment,
        edit_instructions=body.edit_instructions,
        user_id=current_user.get("user_id"),
    )
    resp = FeedbackResponse(
        feedback_id=result.get("feedback_id"),
        status=result.get("status", "submitted"),
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=ApiResponse(data=resp.model_dump(mode="json")).model_dump(mode="json"),
    )


@router.post("/{session_id}/regenerate", response_model=ApiResponse, tags=["行程"])
async def regenerate(
    session_id: str,
    body: RegenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """根据反馈或修改指令重新生成行程"""
    # 参数校验：feedback_id 与 edit_instructions 至少提供一个
    if body.feedback_id is None and not body.edit_instructions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="必须提供 feedback_id 或 edit_instructions",
        )

    repos = Repositories(db)
    await _get_session_or_404(repos, session_id)

    service = get_feedback_service()
    result = await service.regenerate(
        session_id=session_id,
        feedback_id=body.feedback_id,
        edit_instructions=body.edit_instructions,
    )
    # 兼容 service 返回 dict 或 ORM 对象两种形式的 items
    raw_items = result.get("items") or []
    items_data: list[dict] = []
    for it in raw_items:
        if isinstance(it, dict):
            items_data.append(ItineraryItemSchema(**it).model_dump(mode="json"))
        else:
            items_data.append(
                ItineraryItemSchema.model_validate(it, from_attributes=True).model_dump(mode="json")
            )
    resp = RegenerateResponse(
        new_version=result.get("new_version"),
        items=items_data,
    )
    return ApiResponse(data=resp.model_dump(mode="json"))
