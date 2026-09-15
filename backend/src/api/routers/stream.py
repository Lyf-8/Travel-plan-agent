"""流式对话路由

提供 Server-Sent Events (SSE) 流式消息接口。
前缀：``/api/chat``
"""
from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db
from ..schemas.chat import SendMessageRequest
from ...core.exceptions import ResourceNotFound
from ...db.repositories import Repositories
from ...services.itinerary_service import get_itinerary_service

router = APIRouter(prefix="/api/chat")


def _format_sse(event: dict) -> str:
    """将事件 dict 格式化为 SSE 协议字符串

    SSE 协议格式：
        event: <event_name>\n
        data: <json_string>\n\n
    """
    event_name = event.get("event", "message")
    data = event.get("data", {})
    lines = [
        f"event: {event_name}",
        f"data: {json.dumps(data, ensure_ascii=False)}",
        "",
        "",
    ]
    return "\n".join(lines)


async def _get_session_or_404(repos: Repositories, session_id: str):
    """按 session_id 查询会话，不存在则抛出 ResourceNotFound"""
    session = await repos.sessions.get_by_session_id(session_id)
    if session is None:
        raise ResourceNotFound(message=f"会话不存在: {session_id}")
    return session


@router.post(
    "/sessions/{session_id}/messages/stream",
    tags=["流式对话"],
)
async def send_message_stream(
    session_id: str,
    body: SendMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """发送消息并通过 SSE 流式返回进度事件

    事件类型：
        - ``node_start``:    节点开始执行
        - ``node_progress``: 节点执行完成（含进度百分比）
        - ``clarification``: 需要用户澄清（预留）
        - ``error``:         执行出错
        - ``done``:          全部完成（含 reply / itinerary / version）
    """
    # 参数校验：消息内容不能为空
    if not body.message or not body.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="消息内容不能为空",
        )

    logger.info(
        f"流式发送消息请求: path={request.url.path} session_id={session_id} "
        f"message_len={len(body.message)}"
    )

    # 先校验 session 是否存在（流式中抛异常不如同步直接）
    repos = Repositories(db)
    await _get_session_or_404(repos, session_id)

    service = get_itinerary_service()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event in service.send_message_stream(
                session_id=session_id,
                message=body.message,
            ):
                yield _format_sse(event)
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=exc).error(
                f"流式生成器异常 session={session_id}: {exc}"
            )
            err_event = {
                "event": "error",
                "data": {"message": str(exc)},
            }
            yield _format_sse(err_event)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )
