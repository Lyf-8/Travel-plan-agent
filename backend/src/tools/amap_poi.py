"""高德 POI 搜索工具
文档：https://lbs.amap.com/api/webservice/guide/api/search
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx
from loguru import logger

from ..core.config import get_settings
from ..core.exceptions import AmapAPIError, ConfigError


@dataclass
class POIItem:
    """POI 搜索结果项（标准化结构，不直接暴露高德原始字段）"""
    id: str                       # 高德 POI ID
    name: str                     # 名称
    address: Optional[str] = None # 地址
    category: Optional[str] = None # 分类（如：风景名胜）
    tel: Optional[str] = None     # 电话
    longitude: Optional[float] = None  # 经度
    latitude: Optional[float] = None   # 纬度
    rating: Optional[float] = None     # 评分
    cost: Optional[str] = None         # 人均消费 (文本)
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    raw: Optional[dict] = None   # 原始数据（可选保留）


class AmapPOISearch:
    """高德 POI 搜索封装

    常用搜索类型：
        keywords : 关键字搜索（默认）
        around   : 周边搜索（指定经纬度 + 半径）
        polygon  : 多边形内搜索
    """

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.AMAP_KEY:
            raise ConfigError("AMAP_KEY 未配置")
        self.api_key = settings.AMAP_KEY
        self.base_url = settings.AMAP_BASE_URL.rstrip("/")
        self.timeout = settings.AMAP_TIMEOUT

    # ============================================================
    # 基础 HTTP
    # ============================================================
    async def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        p = {"key": self.api_key, "output": "JSON", **params}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=p)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as e:
            raise AmapAPIError(f"高德 API 超时: {e}") from e
        except Exception as e:  # noqa: BLE001
            raise AmapAPIError(f"高德 API 请求失败: {e}") from e

        # 高德返回 status=1 成功，status=0 失败
        if str(data.get("status")) != "1":
            info = data.get("info", "unknown")
            infocode = data.get("infocode", "-1")
            logger.error(f"高德 POI 返回错误: status=0 infocode={infocode} info={info}")
            raise AmapAPIError(
                message=f"高德 API 错误: {info}",
                data={"infocode": infocode, "info": info},
            )
        return data

    # ============================================================
    # 1. 关键字搜索（最常用）
    # ============================================================
    async def keywords_search(
        self,
        keywords: str,
        city: Optional[str] = None,          # 城市名 or 城市编码（如 "北京" or "110000"）
        citylimit: bool = True,              # 是否限制在指定城市内
        categories: Optional[str] = None,    # 分类编码，多个用 | 分隔
        offset: int = 20,                    # 每页数量 (1-25)
        page: int = 1,                       # 页码
        extensions: str = "all",             # base: 基础信息，all: 详细
    ) -> list[POIItem]:
        """关键字搜索 POI，返回标准化的 POIItem 列表"""
        if not keywords:
            return []
        params: dict[str, Any] = {
            "keywords": keywords,
            "offset": min(max(offset, 1), 25),
            "page": max(page, 1),
            "extensions": extensions,
        }
        if city:
            params["city"] = city
            params["citylimit"] = "true" if citylimit else "false"
        if categories:
            params["types"] = categories

        data = await self._get("/place/text", params)
        pois = data.get("pois", []) or []
        return [self._parse_poi(p) for p in pois]

    # ============================================================
    # 2. 周边搜索（Agent3 景点 -> Agent6 住宿餐饮都会用）
    # ============================================================
    async def around_search(
        self,
        longitude: float,
        latitude: float,
        keywords: Optional[str] = None,
        radius: int = 3000,                       # 半径，米 (最大 50000)
        categories: Optional[str] = None,
        sortrule: str = "distance",               # distance: 按距离 / weight: 综合
        offset: int = 20,
        page: int = 1,
        extensions: str = "all",
    ) -> list[POIItem]:
        location = f"{longitude:.6f},{latitude:.6f}"
        params: dict[str, Any] = {
            "location": location,
            "radius": min(max(radius, 0), 50000),
            "sortrule": sortrule,
            "offset": min(max(offset, 1), 25),
            "page": max(page, 1),
            "extensions": extensions,
        }
        if keywords:
            params["keywords"] = keywords
        if categories:
            params["types"] = categories
        data = await self._get("/place/around", params)
        pois = data.get("pois", []) or []
        return [self._parse_poi(p) for p in pois]

    # ============================================================
    # 3. POI 详情（根据 POI ID 拉取详细）
    # ============================================================
    async def detail(self, poi_id: str) -> Optional[POIItem]:
        if not poi_id:
            return None
        params = {"id": poi_id, "extensions": "all"}
        data = await self._get("/place/detail", params)
        pois = data.get("pois", []) or []
        if not pois:
            return None
        return self._parse_poi(pois[0])

    # ============================================================
    # 解析工具
    # ============================================================
    @staticmethod
    def _parse_poi(raw: dict) -> POIItem:
        location = raw.get("location") or ""
        lng: Optional[float] = None
        lat: Optional[float] = None
        if location and "," in location:
            try:
                lng_str, lat_str = location.split(",", 1)
                lng = float(lng_str)
                lat = float(lat_str)
            except ValueError:
                lng, lat = None, None

        # 评分：高德 extensions=all 才有 biz_ext.rating
        biz_ext = raw.get("biz_ext") or {}
        rating_val = biz_ext.get("rating")
        try:
            rating = float(rating_val) if rating_val not in (None, "", [], "[]") else None
        except (TypeError, ValueError):
            rating = None
        cost = biz_ext.get("cost") if isinstance(biz_ext.get("cost"), str) else None

        return POIItem(
            id=raw.get("id", ""),
            name=raw.get("name", ""),
            address=raw.get("address") or None,
            category=raw.get("type") or raw.get("typecode") or None,
            tel=raw.get("tel") or None,
            longitude=lng,
            latitude=lat,
            rating=rating,
            cost=cost,
            province=raw.get("pname") or None,
            city=raw.get("cityname") or None,
            district=raw.get("adname") or None,
            raw=raw,
        )


# ============================================================
# 便捷单例
# ============================================================
_instance: Optional[AmapPOISearch] = None


def get_poi_search() -> AmapPOISearch:
    global _instance
    if _instance is None:
        _instance = AmapPOISearch()
    return _instance
