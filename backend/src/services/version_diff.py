"""行程版本差异对比

职责：
    - 对比同一会话的两个行程版本，输出新增 / 删除 / 修改 / 未变化的明细

说明：
    - 按 (day, order_in_day) 作为对齐键进行逐项比较
    - 直接读取 ORM 对象属性，不依赖其他 service，相对独立
"""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from ..core.exceptions import ResourceNotFound
from ..db.connection import get_session_factory
from ..db.repositories import Repositories


class VersionDiffService:
    """行程版本差异对比服务"""

    # 需要逐字段比较的明细字段（不含 day / order_in_day，它们用于对齐）
    _COMPARE_FIELDS: tuple[str, ...] = (
        "item_type", "title", "description",
        "start_time", "end_time", "duration_min",
        "location_name", "location_address", "longitude", "latitude", "amap_poi_id",
        "transport_from_prev", "travel_time_min", "travel_distance_m",
        "cost_ticket", "cost_food", "cost_hotel", "cost_transport", "cost_other",
        "tags", "image_url",
    )

    async def compute_diff(
        self, session_id: str, version_a: int, version_b: int
    ) -> dict:
        """对比两个版本的行程差异"""
        # 同版本无需对比
        if version_a == version_b:
            return {
                "session_id": session_id,
                "version_a": version_a,
                "version_b": version_b,
                "added": [],
                "removed": [],
                "modified": [],
                "unchanged": [],
            }

        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)

            # 获取两个版本
            ver_a = await repos.versions.get_by_version(session_id, version_a)
            if ver_a is None:
                raise ResourceNotFound(
                    f"版本不存在: session={session_id} version={version_a}"
                )
            ver_b = await repos.versions.get_by_version(session_id, version_b)
            if ver_b is None:
                raise ResourceNotFound(
                    f"版本不存在: session={session_id} version={version_b}"
                )

            items_a = list(await repos.items.list_by_version(ver_a.id))
            items_b = list(await repos.items.list_by_version(ver_b.id))

            diff = self._diff_items(items_a, items_b)
            logger.info(
                f"版本差异计算完成 session={session_id} "
                f"v{version_a} vs v{version_b}: "
                f"+{len(diff['added'])} -{len(diff['removed'])} "
                f"~{len(diff['modified'])} ={len(diff['unchanged'])}"
            )
            return {
                "session_id": session_id,
                "version_a": version_a,
                "version_b": version_b,
                **diff,
            }
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    def _diff_items(self, items_a: list, items_b: list) -> dict:
        """内部：对比两组 items（按 day + order_in_day 对齐）"""
        # 以 (day, order_in_day) 作为键建立索引
        map_a = {self._item_key(it): it for it in items_a}
        map_b = {self._item_key(it): it for it in items_b}

        keys_a = set(map_a.keys())
        keys_b = set(map_b.keys())

        added: list[dict] = []
        removed: list[dict] = []
        modified: list[dict] = []
        unchanged: list[dict] = []

        # b 中相对 a 新增的
        for k in sorted(keys_b - keys_a):
            added.append(self._item_summary(map_b[k]))
        # a 中相对 b 删除的
        for k in sorted(keys_a - keys_b):
            removed.append(self._item_summary(map_a[k]))
        # 两者都有的：逐字段比较
        for k in sorted(keys_a & keys_b):
            it_a = map_a[k]
            it_b = map_b[k]
            changes = self._compare_fields(it_a, it_b)
            summary = self._item_summary(it_a)
            if changes:
                summary["changes"] = changes
                modified.append(summary)
            else:
                unchanged.append(summary)

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
            "unchanged": unchanged,
        }

    @staticmethod
    def _item_key(it: Any) -> tuple:
        """以 (day, order_in_day) 作为对齐键"""
        return (getattr(it, "day", None), getattr(it, "order_in_day", None))

    @staticmethod
    def _item_summary(it: Any) -> dict:
        """提取行程项的简要信息"""
        return {
            "day": getattr(it, "day", None),
            "order_in_day": getattr(it, "order_in_day", None),
            "title": getattr(it, "title", None),
            "item_type": getattr(it, "item_type", None),
        }

    @classmethod
    def _compare_fields(cls, it_a: Any, it_b: Any) -> dict:
        """比较两个行程项的字段差异，返回 {field: (old, new)}"""
        changes: dict = {}
        for field in cls._COMPARE_FIELDS:
            val_a = getattr(it_a, field, None)
            val_b = getattr(it_b, field, None)
            if val_a != val_b:
                changes[field] = (val_a, val_b)
        return changes


# ============================================================
# 单例
# ============================================================
_service: Optional[VersionDiffService] = None


def get_version_diff_service() -> VersionDiffService:
    """获取版本差异服务单例"""
    global _service
    if _service is None:
        _service = VersionDiffService()
    return _service
