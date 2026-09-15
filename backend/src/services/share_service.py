"""行程分享服务 - 短链接生成与快照管理

职责：
    - 基于 itinerary_version_id + session_id 生成 hashids 短码
    - 生成分享瞬间的行程快照（目的地、天数、行程明细、预算等）
    - 短链接访问时校验过期 + 浏览计数 + 返回快照
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Optional

from hashids import Hashids
from loguru import logger

from ..core.config import get_settings
from ..core.exceptions import ResourceNotFound, ValidationError
from ..db.connection import get_session_factory
from ..db.repositories import Repositories


class ShareService:
    """行程分享短链接服务"""

    def __init__(self) -> None:
        settings = get_settings()
        salt = settings.API_SECRET_KEY or "ai-travel-planner-share-salt"
        self._hashids = Hashids(salt=salt, min_length=6)

    # ============================================================
    # 创建分享链接
    # ============================================================
    async def create_share_link(
        self,
        session_id: str,
        version_id: Optional[int] = None,
        expire_days: int = 30,
    ) -> dict:
        """创建行程分享短链接

        Args:
            session_id: 会话 UUID
            version_id: 指定行程版本 ID（为空则取当前版本）
            expire_days: 有效天数，默认 30 天

        Returns:
            dict: {short_code, share_url, expire_at}
        """
        if expire_days <= 0:
            raise ValidationError("expire_days 必须大于 0")

        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)

            # 1. 获取会话
            session = await repos.sessions.get_by_session_id(session_id)
            if session is None:
                raise ResourceNotFound(f"会话不存在: {session_id}")

            # 2. 获取目标版本
            if version_id is not None:
                version_obj = await repos.versions.get_by_id(version_id)
                if version_obj is None or version_obj.session_id != session_id:
                    raise ResourceNotFound(f"版本不存在: {version_id}")
            else:
                version_obj = await repos.versions.get_current(session_id)
                if version_obj is None:
                    raise ResourceNotFound(f"会话 {session_id} 暂无行程版本")

            # 3. 获取明细项并构造快照
            items = await repos.items.list_by_version(version_obj.id)
            items_list = [self._item_to_dict(it) for it in items]
            budget_breakdown = self._compute_budget_breakdown(items_list)
            arranged_itinerary = self._group_by_day(items_list)

            # 提取天气摘要（从 raw_output 中兜底）
            weather_summary = None
            raw_output = version_obj.raw_output or {}
            if isinstance(raw_output, dict):
                weather_summary = raw_output.get("weather_info") or raw_output.get("weather_summary")

            # 提取酒店、餐饮等聚合信息
            hotels = [
                it for it in items_list if it.get("item_type") == "hotel"
            ]
            foods = [
                it for it in items_list if it.get("item_type") == "food"
            ]

            share_snapshot: dict[str, Any] = {
                "destination": session.destination,
                "travel_days": session.travel_days,
                "arranged_itinerary": arranged_itinerary,
                "budget_breakdown": {
                    "total": version_obj.total_budget,
                    "categories": budget_breakdown,
                },
                "hotels": hotels,
                "foods": foods,
                "weather_summary": weather_summary,
                "total_distance_km": version_obj.total_distance_km,
                "session_title": session.title,
                "version": version_obj.version,
                "created_at": version_obj.created_at.isoformat()
                if version_obj.created_at
                else None,
                "items": items_list,
            }

            # 4. 先插入记录拿到 id，再用 id 编码 short_code
            expire_at = datetime.utcnow() + timedelta(days=expire_days)
            short_link = await repos.short_links.create(
                short_code="pending_" + hashlib.md5(session_id.encode()).hexdigest()[:8],
                session_id=session_id,
                itinerary_version_id=version_obj.id,
                share_snapshot=share_snapshot,
                expire_at=expire_at,
                view_count=0,
            )
            await sess.flush()

            # 用 id + version_id 混合编码，确保唯一性
            short_code = self._hashids.encode(short_link.id, version_obj.id or 0)
            await repos.short_links.update(short_link.id, short_code=short_code)

            await repos.commit()
            logger.info(
                f"创建分享短链接: session={session_id} version={version_obj.version} "
                f"code={short_code} expire={expire_at}"
            )
            return {
                "short_code": short_code,
                "share_url": f"/#/share/{short_code}",
                "expire_at": expire_at.isoformat(),
            }
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    # ============================================================
    # 读取分享快照
    # ============================================================
    async def get_share_snapshot(self, short_code: str) -> dict:
        """根据短码获取分享快照

        - 校验短码存在且未过期
        - 浏览次数 +1
        - 返回快照与元数据
        """
        if not short_code or not short_code.strip():
            raise ValidationError("短码不能为空")

        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)
            short_link = await repos.short_links.get_by_code(short_code)
            if short_link is None:
                raise ResourceNotFound("分享链接不存在或已失效")

            # 校验过期
            if short_link.expire_at and short_link.expire_at < datetime.utcnow():
                raise ResourceNotFound("分享链接已过期")

            # 浏览计数 +1
            await repos.short_links.increment_view(short_link.id)
            new_view_count = (short_link.view_count or 0) + 1

            await repos.commit()
            return {
                "share_snapshot": short_link.share_snapshot,
                "view_count": new_view_count,
                "session_id": short_link.session_id,
                "version_id": short_link.itinerary_version_id,
                "created_at": short_link.created_at.isoformat()
                if short_link.created_at
                else None,
                "expire_at": short_link.expire_at.isoformat()
                if short_link.expire_at
                else None,
            }
        except ResourceNotFound:
            raise
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    # ============================================================
    # 静态工具方法
    # ============================================================
    @staticmethod
    def _item_to_dict(item: Any) -> dict:
        return {
            "id": item.id,
            "day": item.day,
            "order_in_day": item.order_in_day,
            "item_type": item.item_type,
            "title": item.title,
            "description": item.description,
            "start_time": item.start_time,
            "end_time": item.end_time,
            "duration_min": item.duration_min,
            "location_name": item.location_name,
            "location_address": item.location_address,
            "longitude": item.longitude,
            "latitude": item.latitude,
            "transport_from_prev": item.transport_from_prev,
            "travel_time_min": item.travel_time_min,
            "travel_distance_m": item.travel_distance_m,
            "cost_ticket": item.cost_ticket,
            "cost_food": item.cost_food,
            "cost_hotel": item.cost_hotel,
            "cost_transport": item.cost_transport,
            "cost_other": item.cost_other,
            "tags": item.tags,
            "image_url": item.image_url,
        }

    @staticmethod
    def _compute_budget_breakdown(items: list[dict]) -> dict:
        """从 items 聚合预算分类"""
        result = {"transport": 0, "food": 0, "hotel": 0, "tickets": 0, "other": 0}
        for it in items:
            result["tickets"] += float(it.get("cost_ticket") or 0)
            result["food"] += float(it.get("cost_food") or 0)
            result["hotel"] += float(it.get("cost_hotel") or 0)
            result["transport"] += float(it.get("cost_transport") or 0)
            result["other"] += float(it.get("cost_other") or 0)
        return result

    @staticmethod
    def _group_by_day(items: list[dict]) -> list[list[dict]]:
        """按 day 分组，返回 [[day1 items], [day2 items], ...]"""
        days_map: dict[int, list[dict]] = {}
        for it in items:
            d = int(it.get("day") or 1)
            days_map.setdefault(d, []).append(it)
        sorted_days = sorted(days_map.keys())
        return [days_map[d] for d in sorted_days]


# ============================================================
# 单例
# ============================================================
_share_service: Optional[ShareService] = None


def get_share_service() -> ShareService:
    """获取分享服务单例"""
    global _share_service
    if _share_service is None:
        _share_service = ShareService()
    return _share_service
