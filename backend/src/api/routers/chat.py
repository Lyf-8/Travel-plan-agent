"""对话路由

提供会话创建、列表、详情、消息发送、历史查询、删除等接口。
前缀：``/api/chat``

业务逻辑通过 ``ItineraryService`` 完成；直接读写（列表/详情/历史/删除）
通过 ``Repositories`` 操作数据库。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_current_user, get_db
from ..schemas.chat import (
    ChatHistoryResponse,
    CreateSessionRequest,
    MessageItem,
    MessageResponse,
    SendMessageRequest,
    SessionResponse,
)
from ..schemas.common import ApiResponse
from ...core.exceptions import ResourceNotFound
from ...db.repositories import Repositories
from ...services.itinerary_service import get_itinerary_service

router = APIRouter(prefix="/api/chat")


def _session_to_response(session) -> dict:
    """将 ChatSession ORM 对象转换为响应字典"""
    return SessionResponse.model_validate(session, from_attributes=True).model_dump(mode="json")


async def _get_session_or_404(repos: Repositories, session_id: str):
    """按 session_id 查询会话，不存在则抛出 ResourceNotFound"""
    session = await repos.sessions.get_by_session_id(session_id)
    if session is None:
        raise ResourceNotFound(message=f"会话不存在: {session_id}")
    return session


@router.post(
    "/sessions",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["对话"],
)
async def create_session(
    body: CreateSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """创建会话

    - 根据 ``username`` 获取或创建用户
    - 调用 ``ItineraryService.create_session`` 创建会话
    """
    logger.info(
        f"创建会话请求: path={request.url.path} username={body.username} "
        f"destination={body.destination}"
    )
    repos = Repositories(db)
    # 获取或创建用户，并提交，确保后续 service（独立会话）可见
    user = await repos.users.get_or_create(body.username)
    await repos.commit()

    service = get_itinerary_service()
    session = await service.create_session(
        user_id=user.id,
        destination=body.destination,
        travel_days=body.travel_days,
        budget_min=body.budget_min,
        budget_max=body.budget_max,
        preferences=body.preferences,
        title=body.title,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=ApiResponse(data=_session_to_response(session)).model_dump(mode="json"),
    )


@router.get("/sessions", response_model=ApiResponse, tags=["对话"])
async def list_sessions(
    user_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ApiResponse:
    """获取会话列表（可选按 user_id 过滤，未指定时使用当前用户）"""
    repos = Repositories(db)
    effective_uid = user_id if user_id is not None else current_user.get("user_id")
    if effective_uid is not None:
        sessions = await repos.sessions.list_by_user(effective_uid)
    else:
        sessions = await repos.sessions.list_all(limit=50)
    data = [_session_to_response(s) for s in sessions]
    return ApiResponse(data=data)


@router.get("/sessions/{session_id}", response_model=ApiResponse, tags=["对话"])
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """获取会话详情"""
    repos = Repositories(db)
    session = await _get_session_or_404(repos, session_id)
    return ApiResponse(data=_session_to_response(session))


@router.post("/sessions/{session_id}/messages", response_model=ApiResponse, tags=["对话"])
async def send_message(
    session_id: str,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """发送消息并获取助手回复（可能附带新生成的行程版本）"""
    # 参数校验：消息内容不能为空
    if not body.message or not body.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="消息内容不能为空",
        )

    repos = Repositories(db)
    await _get_session_or_404(repos, session_id)

    service = get_itinerary_service()
    result = await service.send_message(session_id=session_id, message=body.message)
    resp = MessageResponse(
        reply=result.get("reply", ""),
        itinerary=result.get("itinerary"),
        version=result.get("version"),
        session_id=session_id,
    )
    return ApiResponse(data=resp.model_dump(mode="json"))


@router.get("/sessions/{session_id}/messages", response_model=ApiResponse, tags=["对话"])
async def get_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """获取对话历史"""
    repos = Repositories(db)
    await _get_session_or_404(repos, session_id)

    messages = await repos.messages.list_by_session(session_id)
    items = [
        MessageItem(role=m.role, content=m.content, created_at=m.created_at)
        for m in messages
    ]
    history = ChatHistoryResponse(session_id=session_id, messages=items)
    return ApiResponse(data=history.model_dump(mode="json"))


@router.delete("/sessions/{session_id}", response_model=ApiResponse, tags=["对话"])
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """删除会话（级联删除消息、版本、明细、反馈）"""
    repos = Repositories(db)
    session = await _get_session_or_404(repos, session_id)

    # AsyncSession.delete 为同步代理方法（非协程），无需 await；
    # 依赖 ORM cascade="all, delete-orphan" 级联删除关联数据
    db.delete(session)
    await repos.commit()
    return ApiResponse(data={"session_id": session_id, "deleted": True})
