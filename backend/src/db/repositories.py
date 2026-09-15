"""数据仓储层（Repository Pattern）- 封装常用 CRUD

职责：
    - 所有 DB 读写动作都应该通过 Repository 进行
    - Service 层不直接操作 Session，而是调用 Repository 方法
    - 方便未来替换 DB 实现（SQLite → Postgres）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import ResourceNotFound
from .models import (
    ChatMessage,
    ChatSession,
    ItineraryItem,
    ItineraryVersion,
    RAGDocument,
    ShortLink,
    User,
    UserFeedback,
)


# ============================================================
# 通用基类
# ============================================================
class BaseRepository:
    """通用 Repository 基类，每个具体表继承一份"""
    model: Any = None

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, obj_id: int):
        stmt = select(self.model).where(self.model.id == obj_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 100, offset: int = 0):
        stmt = select(self.model).order_by(self.model.id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        stmt = select(func.count()).select_from(self.model)
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)

    async def create(self, **kwargs):
        obj = self.model(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update(self, obj_id: int, **kwargs) -> int:
        stmt = update(self.model).where(self.model.id == obj_id).values(**kwargs)
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def delete(self, obj_id: int) -> int:
        stmt = delete(self.model).where(self.model.id == obj_id)
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)


# ============================================================
# 1. User
# ============================================================
class UserRepository(BaseRepository):
    model = User

    async def get_by_username(self, username: str) -> Optional[User]:
        stmt = select(User).where(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self, username: str, **extra) -> User:
        obj = await self.get_by_username(username)
        if obj:
            return obj
        return await self.create(username=username, **extra)


# ============================================================
# 2. ChatSession
# ============================================================
class ChatSessionRepository(BaseRepository):
    model = ChatSession

    async def get_by_session_id(self, session_id: str) -> Optional[ChatSession]:
        stmt = select(ChatSession).where(ChatSession.session_id == session_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int, limit: int = 50) -> Sequence[ChatSession]:
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ============================================================
# 3. ChatMessage
# ============================================================
class ChatMessageRepository(BaseRepository):
    model = ChatMessage

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        **kwargs,
    ) -> ChatMessage:
        """向会话追加一条消息，自动维护 seq 序号"""
        # 取当前会话最大 seq
        stmt = select(func.max(ChatMessage.seq)).where(ChatMessage.session_id == session_id)
        result = await self.session.execute(stmt)
        max_seq = int(result.scalar() or 0)
        msg = ChatMessage(
            session_id=session_id,
            seq=max_seq + 1,
            role=role,
            content=content,
            **kwargs,
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def list_by_session(
        self, session_id: str, limit: int = 200
    ) -> Sequence[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.seq.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ============================================================
# 4. ItineraryVersion
# ============================================================
class ItineraryVersionRepository(BaseRepository):
    model = ItineraryVersion

    async def create_new_version(
        self,
        session_id: str,
        trigger: str = "initial",
        parent_version: Optional[int] = None,
        **kwargs,
    ) -> ItineraryVersion:
        """创建新版本，自动版本号 + 旧版本 is_current 置 False"""
        # 最大版本号
        stmt = select(func.max(ItineraryVersion.version)).where(
            ItineraryVersion.session_id == session_id
        )
        result = await self.session.execute(stmt)
        max_v = int(result.scalar() or 0)
        new_v = max_v + 1

        # 旧版本 is_current = False
        stmt = (
            update(ItineraryVersion)
            .where(ItineraryVersion.session_id == session_id)
            .values(is_current=False)
        )
        await self.session.execute(stmt)

        obj = ItineraryVersion(
            session_id=session_id,
            version=new_v,
            parent_version=parent_version,
            trigger=trigger,
            is_current=True,
            **kwargs,
        )
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_current(self, session_id: str) -> Optional[ItineraryVersion]:
        stmt = (
            select(ItineraryVersion)
            .where(
                ItineraryVersion.session_id == session_id,
                ItineraryVersion.is_current.is_(True),
            )
            .order_by(ItineraryVersion.version.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_version(self, session_id: str, version: int) -> Optional[ItineraryVersion]:
        stmt = select(ItineraryVersion).where(
            ItineraryVersion.session_id == session_id,
            ItineraryVersion.version == version,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_session(self, session_id: str) -> Sequence[ItineraryVersion]:
        stmt = (
            select(ItineraryVersion)
            .where(ItineraryVersion.session_id == session_id)
            .order_by(ItineraryVersion.version.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ============================================================
# 5. ItineraryItem
# ============================================================
class ItineraryItemRepository(BaseRepository):
    model = ItineraryItem

    async def bulk_create(self, items: Sequence[dict]) -> Sequence[ItineraryItem]:
        """批量创建行程明细"""
        objs = [ItineraryItem(**d) for d in items]
        self.session.add_all(objs)
        await self.session.flush()
        return objs

    async def list_by_version(self, version_id: int) -> Sequence[ItineraryItem]:
        stmt = (
            select(ItineraryItem)
            .where(ItineraryItem.version_id == version_id)
            .order_by(ItineraryItem.day.asc(), ItineraryItem.order_in_day.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ============================================================
# 6. UserFeedback
# ============================================================
class UserFeedbackRepository(BaseRepository):
    model = UserFeedback

    async def list_by_session(self, session_id: str) -> Sequence[UserFeedback]:
        stmt = (
            select(UserFeedback)
            .where(UserFeedback.session_id == session_id)
            .order_by(UserFeedback.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ============================================================
# 7. RAGDocument
# ============================================================
class RAGDocumentRepository(BaseRepository):
    model = RAGDocument

    async def get_by_doc_id(self, doc_id: str) -> Optional[RAGDocument]:
        stmt = select(RAGDocument).where(RAGDocument.doc_id == doc_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def bulk_upsert(self, docs: Sequence[dict]) -> int:
        """批量 upsert（按 doc_id 去重）"""
        created = 0
        for d in docs:
            existing = await self.get_by_doc_id(d["doc_id"])
            if existing is None:
                self.session.add(RAGDocument(**d))
                created += 1
            else:
                for k, v in d.items():
                    if k != "id":
                        setattr(existing, k, v)
        await self.session.flush()
        return created

    async def list_by_city_category(
        self, city: Optional[str], category: Optional[str], limit: int = 100
    ) -> Sequence[RAGDocument]:
        stmt = select(RAGDocument).where(RAGDocument.is_active.is_(True))
        if city:
            stmt = stmt.where(RAGDocument.city == city)
        if category:
            stmt = stmt.where(RAGDocument.category == category)
        stmt = stmt.order_by(RAGDocument.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ============================================================
# 8. ShortLink
# ============================================================
class ShortLinkRepository(BaseRepository):
    model = ShortLink

    async def get_by_code(self, code: str) -> Optional[ShortLink]:
        stmt = select(ShortLink).where(ShortLink.short_code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def increment_view(self, id: int) -> None:
        stmt = (
            update(ShortLink)
            .where(ShortLink.id == id)
            .values(view_count=ShortLink.view_count + 1)
        )
        await self.session.execute(stmt)


# ============================================================
# 统一 Repository 容器（方便一次性注入）
# ============================================================
class Repositories:
    """所有 Repository 的集合，在 FastAPI 中通过 Depends 一次性获取"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.sessions = ChatSessionRepository(session)
        self.messages = ChatMessageRepository(session)
        self.versions = ItineraryVersionRepository(session)
        self.items = ItineraryItemRepository(session)
        self.feedbacks = UserFeedbackRepository(session)
        self.rag_docs = RAGDocumentRepository(session)
        self.short_links = ShortLinkRepository(session)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
