"""RAG 渐进式缓存（内存 + TTL）

解决问题：
    - 用户多次问同一个景点相关问题 → 避免重复向量检索 + 重复外部百科抓取
    - "缓存优先、外部搜索兜底"策略：
        1. 先查缓存 → 命中直接返回
        2. 缓存未命中 → 向量库检索 → 结果写回缓存
        3. 向量库还未命中 → 调用 WikiSearch 抓百科 → 写向量库 + 写缓存
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from ..core.config import get_settings
from .vector_store import SearchHit


# 为了避免 pickle 序列化问题，用简单字段存
@dataclass
class _CacheEntry:
    hits: list[SearchHit]
    expire_at: float


def _cache_key(query: str, city: Optional[str], category: Optional[str]) -> str:
    q = " ".join(query.strip().split()).lower()
    return f"{city or ''}|{category or ''}|{q}"


class RAGCache:
    """内存字典缓存 + TTL。生产可替换为 Redis（接口保持不变）"""

    def __init__(self, ttl_seconds: Optional[int] = None, max_items: int = 5000) -> None:
        settings = get_settings()
        self.ttl = ttl_seconds if ttl_seconds is not None else settings.RAG_CACHE_TTL
        self.max_items = max_items
        self._data: dict[str, _CacheEntry] = {}

    # ---------- 内部工具 ----------
    def _evict_if_needed(self) -> None:
        if len(self._data) <= self.max_items:
            return
        # 淘汰：按 expire_at 从小到大排，删过期的+最老的
        now = time.time()
        items = sorted(self._data.items(), key=lambda kv: kv[1].expire_at)
        # 先删过期
        expired = [k for k, v in items if v.expire_at <= now]
        for k in expired:
            self._data.pop(k, None)
        # 还超就删最老的
        target = int(self.max_items * 0.8)
        remain = sorted(self._data.items(), key=lambda kv: kv[1].expire_at)
        to_delete = len(remain) - target
        if to_delete > 0:
            for k, _ in remain[:to_delete]:
                self._data.pop(k, None)

    # ---------- 对外 API ----------
    async def get(
        self,
        query: str,
        city: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Optional[list[SearchHit]]:
        key = _cache_key(query, city, category)
        entry = self._data.get(key)
        if entry is None:
            return None
        if time.time() > entry.expire_at:
            self._data.pop(key, None)
            return None
        return list(entry.hits)

    async def set(
        self,
        query: str,
        hits: list[SearchHit],
        city: Optional[str] = None,
        category: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        key = _cache_key(query, city, category)
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl
        self._data[key] = _CacheEntry(hits=list(hits), expire_at=time.time() + ttl)
        self._evict_if_needed()
        logger.debug(f"[RAGCache] SET query={query[:30]!r} hits={len(hits)}")

    async def invalidate(
        self,
        query: Optional[str] = None,
        city: Optional[str] = None,
        category: Optional[str] = None,
    ) -> int:
        """按条件删除缓存（不传 query 就按 city/category 模糊匹配）"""
        if query is not None:
            key = _cache_key(query, city, category)
            return 1 if self._data.pop(key, None) else 0
        # 模糊删除：city/category 任一命中
        to_remove: list[str] = []
        for k in self._data.keys():
            kcity, kcat, _ = k.split("|", 2)
            if city and city != kcity:
                continue
            if category and category != kcat:
                continue
            to_remove.append(k)
        for k in to_remove:
            self._data.pop(k, None)
        return len(to_remove)

    async def clear(self) -> None:
        self._data.clear()
        logger.info("[RAGCache] 已清空")

    def stats(self) -> dict:
        return {"count": len(self._data), "ttl": self.ttl, "max": self.max_items}


_cache: Optional[RAGCache] = None


def get_rag_cache() -> RAGCache:
    global _cache
    if _cache is None:
        _cache = RAGCache()
    return _cache
