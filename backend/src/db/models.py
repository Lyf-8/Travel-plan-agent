"""SQLAlchemy 2.0 ORM 模型定义

表结构（8 张核心表）：
    1. users            - 用户表
    2. chat_sessions    - 对话/行程会话表
    3. chat_messages    - 对话消息表
    4. itinerary_versions - 行程版本表（每次生成/重生成一条）
    5. itinerary_items  - 行程明细项（每天的每个活动）
    6. user_feedback    - 用户反馈表
    7. rag_documents    - RAG 知识库文档元数据
    8. short_links      - 行程分享短链接表
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .connection import Base


# ============================================================
# 1. 用户表
# ============================================================
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="用户名（可匿名UUID）")
    nickname: Mapped[Optional[str]] = mapped_column(String(128), comment="展示昵称")
    email: Mapped[Optional[str]] = mapped_column(String(128), comment="邮箱")
    avatar: Mapped[Optional[str]] = mapped_column(String(512), comment="头像 URL")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    # 关联
    sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    feedbacks: Mapped[list["UserFeedback"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ============================================================
# 2. 对话/行程会话表
# ============================================================
class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("idx_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, comment="对外暴露的会话 UUID"
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(256), default="未命名行程", comment="会话/行程标题")
    summary: Mapped[Optional[str]] = mapped_column(Text, comment="会话摘要")
    destination: Mapped[Optional[str]] = mapped_column(String(128), comment="目的地城市")
    travel_days: Mapped[Optional[int]] = mapped_column(Integer, comment="旅行天数")
    budget_min: Mapped[Optional[float]] = mapped_column(Float, comment="最低预算")
    budget_max: Mapped[Optional[float]] = mapped_column(Float, comment="最高预算")
    preferences: Mapped[Optional[dict]] = mapped_column(JSON, comment="偏好（JSON：餐饮/景点风格等）")
    status: Mapped[str] = mapped_column(
        String(32), default="active", comment="active / completed / archived"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 关联
    user: Mapped[Optional[User]] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.seq"
    )
    versions: Mapped[list["ItineraryVersion"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ItineraryVersion.version"
    )
    feedbacks: Mapped[list["UserFeedback"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


# ============================================================
# 3. 对话消息表
# ============================================================
class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("idx_session_seq", "session_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, comment="消息序号，从1递增")
    role: Mapped[str] = mapped_column(String(16), comment="user / assistant / system / tool")
    content: Mapped[str] = mapped_column(Text, comment="消息文本内容")
    extra: Mapped[Optional[dict]] = mapped_column(JSON, comment="附加数据（tool_calls、token用量等）")
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, comment="输入 tokens")
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, comment="输出 tokens")
    cost: Mapped[Optional[float]] = mapped_column(Float, comment="本次调用成本（元）")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, comment="耗时 (ms)")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # 关联
    session: Mapped[ChatSession] = relationship(back_populates="messages")


# ============================================================
# 4. 行程版本表（每次生成/重新生成一条）
# ============================================================
class ItineraryVersion(Base):
    __tablename__ = "itinerary_versions"
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_session_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, comment="版本号 v1, v2...")
    parent_version: Mapped[Optional[int]] = mapped_column(
        Integer, comment="父版本号（基于哪一版修改/重生成）"
    )
    trigger: Mapped[str] = mapped_column(
        String(32),
        default="initial",
        comment="生成原因: initial / feedback / manual",
    )
    total_budget: Mapped[Optional[float]] = mapped_column(Float, comment="总预算 (元)")
    total_distance_km: Mapped[Optional[float]] = mapped_column(Float, comment="总行程公里数")
    map_data: Mapped[Optional[dict]] = mapped_column(JSON, comment="地图数据（POI/路线）")
    raw_output: Mapped[Optional[dict]] = mapped_column(JSON, comment="Agent11 输出的完整 JSON")
    generated_by: Mapped[Optional[str]] = mapped_column(
        String(64), comment="生成模型 (gpt-4o-mini / qwen-plus ...)"
    )
    tokens_total: Mapped[Optional[int]] = mapped_column(Integer, comment="本次生成总 tokens")
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer, comment="本次生成耗时 (秒)")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否为当前展示版本")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 关联
    session: Mapped[ChatSession] = relationship(back_populates="versions")
    items: Mapped[list["ItineraryItem"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="ItineraryItem.day, ItineraryItem.order_in_day"
    )
    feedbacks: Mapped[list["UserFeedback"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


# ============================================================
# 5. 行程明细项（每天的每个活动）
# ============================================================
class ItineraryItem(Base):
    __tablename__ = "itinerary_items"
    __table_args__ = (
        Index("idx_version_day_order", "version_id", "day", "order_in_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("itinerary_versions.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[int] = mapped_column(Integer, comment="第几天，从1开始")
    order_in_day: Mapped[int] = mapped_column(Integer, comment="当天的顺序号，从1开始")
    item_type: Mapped[str] = mapped_column(
        String(32),
        comment="类型: attraction / food / hotel / transport / rest / shopping",
    )
    title: Mapped[str] = mapped_column(String(256), comment="活动标题")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="详细描述 + 背景介绍")
    start_time: Mapped[Optional[str]] = mapped_column(String(8), comment="HH:MM")
    end_time: Mapped[Optional[str]] = mapped_column(String(8), comment="HH:MM")
    duration_min: Mapped[Optional[int]] = mapped_column(Integer, comment="建议时长 (分钟)")

    # 地点
    location_name: Mapped[Optional[str]] = mapped_column(String(256), comment="地点名称")
    location_address: Mapped[Optional[str]] = mapped_column(String(512), comment="详细地址")
    longitude: Mapped[Optional[float]] = mapped_column(Float, comment="经度 (高德坐标系)")
    latitude: Mapped[Optional[float]] = mapped_column(Float, comment="纬度 (高德坐标系)")
    amap_poi_id: Mapped[Optional[str]] = mapped_column(String(64), comment="高德 POI ID")

    # 交通 & 预算
    transport_from_prev: Mapped[Optional[str]] = mapped_column(
        String(32), comment="从上一项过来的交通方式: walk / drive / subway / bus / taxi"
    )
    travel_time_min: Mapped[Optional[int]] = mapped_column(Integer, comment="从上一项过来的时间 (分钟)")
    travel_distance_m: Mapped[Optional[int]] = mapped_column(Integer, comment="从上一项过来的距离 (米)")
    cost_ticket: Mapped[Optional[float]] = mapped_column(Float, comment="门票费")
    cost_food: Mapped[Optional[float]] = mapped_column(Float, comment="餐饮费")
    cost_hotel: Mapped[Optional[float]] = mapped_column(Float, comment="住宿费")
    cost_transport: Mapped[Optional[float]] = mapped_column(Float, comment="交通费")
    cost_other: Mapped[Optional[float]] = mapped_column(Float, comment="其他费用")

    # 其他
    tags: Mapped[Optional[list]] = mapped_column(JSON, comment="标签数组")
    image_url: Mapped[Optional[str]] = mapped_column(String(512), comment="配图 URL")
    rag_refs: Mapped[Optional[list]] = mapped_column(
        JSON, comment="RAG 引用的知识库文档 IDs"
    )
    extra: Mapped[Optional[dict]] = mapped_column(JSON, comment="扩展字段")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 关联
    version: Mapped[ItineraryVersion] = relationship(back_populates="items")


# ============================================================
# 6. 用户反馈表
# ============================================================
class UserFeedback(Base):
    __tablename__ = "user_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[int] = mapped_column(
        ForeignKey("itinerary_versions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    rating: Mapped[Optional[int]] = mapped_column(Integer, comment="评分 1-5")
    comment: Mapped[Optional[str]] = mapped_column(Text, comment="用户文字反馈")
    edit_instructions: Mapped[Optional[str]] = mapped_column(
        Text, comment="修改指令（重生成时输入给 Agent）"
    )
    item_level_changes: Mapped[Optional[list]] = mapped_column(
        JSON, comment="行程明细级别的调整记录 (新增/删除/顺序变化)"
    )

    # 重生成关联
    regenerated_to_version: Mapped[Optional[int]] = mapped_column(
        Integer, comment="基于该反馈生成的新版本号"
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="submitted",
        comment="submitted / processing / regenerated",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 关联
    session: Mapped[ChatSession] = relationship(back_populates="feedbacks")
    version: Mapped[ItineraryVersion] = relationship(back_populates="feedbacks")
    user: Mapped[Optional[User]] = relationship(back_populates="feedbacks")


# ============================================================
# 7. RAG 知识库文档元数据表
# ============================================================
class RAGDocument(Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        Index("idx_source", "source_type", "source_id"),
        Index("idx_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(64), unique=True, comment="向量库中的 chunk ID")
    title: Mapped[str] = mapped_column(String(512), comment="文档标题")
    content_snippet: Mapped[Optional[str]] = mapped_column(
        Text, comment="内容片段（预览用，非完整向量）"
    )
    source_type: Mapped[str] = mapped_column(
        String(32), comment="wiki / amap_poi / scrapy / manual"
    )
    source_id: Mapped[Optional[str]] = mapped_column(String(128), comment="原始来源 ID（如 POI ID、百科 URL）")
    category: Mapped[Optional[str]] = mapped_column(
        String(64), comment="分类: attraction / food / hotel / history / culture"
    )
    city: Mapped[Optional[str]] = mapped_column(String(64), comment="所属城市")
    vector_id: Mapped[Optional[str]] = mapped_column(
        String(128), comment="对应向量库中的 point id"
    )
    chunk_index: Mapped[Optional[int]] = mapped_column(
        Integer, comment="如果原文分块，则是第几块 (0-based)"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用检索")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


# ============================================================
# 8. 行程分享短链接表
# ============================================================
class ShortLink(Base):
    __tablename__ = "short_links"
    __table_args__ = (
        Index("idx_short_code", "short_code", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    short_code: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, comment="短码（hashids 生成）"
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), index=True
    )
    itinerary_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("itinerary_versions.id", ondelete="SET NULL"), index=True
    )
    share_snapshot: Mapped[dict] = mapped_column(JSON, comment="行程快照 JSON（分享瞬间的行程+预算信息）")
    expire_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), comment="过期时间"
    )
    view_count: Mapped[int] = mapped_column(Integer, default=0, comment="浏览次数")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    # 关联
    session: Mapped[Optional["ChatSession"]] = relationship("ChatSession")
