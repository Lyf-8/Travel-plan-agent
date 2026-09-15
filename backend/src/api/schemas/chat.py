"""对话相关 Pydantic 模型

包含会话创建、消息发送、会话/消息响应等数据结构，
供 ``api/routers/chat.py`` 使用。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """创建会话请求"""

    destination: Optional[str] = Field(default=None, description="目的地城市")
    travel_days: Optional[int] = Field(default=None, description="旅行天数")
    budget_min: Optional[float] = Field(default=None, description="最低预算")
    budget_max: Optional[float] = Field(default=None, description="最高预算")
    preferences: Optional[dict] = Field(default=None, description="偏好（JSON：餐饮/景点风格等）")
    title: Optional[str] = Field(default=None, description="会话标题")
    username: Optional[str] = Field(default="guest", description="用户名，默认 guest")


class SessionResponse(BaseModel):
    """会话响应"""

    session_id: str
    title: Optional[str] = None
    destination: Optional[str] = None
    travel_days: Optional[int] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    preferences: Optional[dict] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None


class SendMessageRequest(BaseModel):
    """发送消息请求"""

    message: str = Field(..., description="用户消息内容")


class MessageResponse(BaseModel):
    """消息响应（含助手回复与可选行程）"""

    reply: str
    itinerary: Optional[dict] = None
    version: Optional[int] = None
    session_id: str


class MessageItem(BaseModel):
    """单条消息（用于历史记录）"""

    role: str
    content: str
    created_at: Optional[datetime] = None


class ChatHistoryResponse(BaseModel):
    """对话历史响应"""

    session_id: str
    messages: list[MessageItem] = Field(default_factory=list)
