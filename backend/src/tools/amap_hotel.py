"""高德酒店查询（复用 POI 搜索 + 关键字 hotel 封装）

说明：高德"纯酒店专用 API"是商业付费版，普通开发者用通用 POI 搜索即可：
    - types=100101 (宾馆酒店) + keywords=xxx 效果足够
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger

from ..core.exceptions import ToolCallError
from .amap_poi import AmapPOISearch, POIItem, get_poi_search


# 高德 POI 分类编码：宾馆酒店大类
HOTEL_CATEGORY = "100101"


@dataclass
class HotelItem:
    """标准化酒店结构"""
    id: str
    name: str
    address: Optional[str]
    stars: Optional[int] = None        # 星级 1-5（从评分估算）
    price_min: Optional[float] = None  # 最低房价（元，从文本解析）
    rating: Optional[float] = None     # 评分
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    tel: Optional[str] = None
    district: Optional[str] = None
    raw: Optional[dict] = None


class AmapHotelSearch:
    """酒店查询（POI + 星级/价格后处理）"""

    def __init__(self, poi: Optional[AmapPOISearch] = None) -> None:
        self.poi = poi or get_poi_search()

    async def search(
        self,
        city: str,
        keywords: Optional[str] = None,         # 例如 "国贸"
        near_lng: Optional[float] = None,       # 中心点经度（附近搜索）
        near_lat: Optional[float] = None,
        radius: int = 5000,                     # 半径 5km
        min_rating: Optional[float] = None,     # 最低评分
        page_size: int = 20,
        page: int = 1,
    ) -> list[HotelItem]:
        """搜索酒店"""
        kw = (keywords or "") + " 酒店" if keywords else "酒店"

        if near_lng is not None and near_lat is not None:
            pois = await self.poi.around_search(
                longitude=near_lng,
                latitude=near_lat,
                keywords=kw,
                categories=HOTEL_CATEGORY,
                radius=radius,
                offset=page_size,
                page=page,
            )
        else:
            pois = await self.poi.keywords_search(
                keywords=kw,
                city=city,
                citylimit=True,
                categories=HOTEL_CATEGORY,
                offset=page_size,
                page=page,
            )

        items: list[HotelItem] = []
        for p in pois:
            hotel = self._poi_to_hotel(p)
            if min_rating is not None and (hotel.rating or 0) < min_rating:
                continue
            items.append(hotel)
        return items

    async def detail(self, poi_id: str) -> Optional[HotelItem]:
        p = await self.poi.detail(poi_id)
        if p is None:
            return None
        return self._poi_to_hotel(p)

    # ---------- 解析 ----------
    @staticmethod
    def _poi_to_hotel(p: POIItem) -> HotelItem:
        # 星级估算：rating=5 → 5星，4.x → 4星
        stars = None
        if p.rating is not None:
            stars = max(1, min(5, int(round(p.rating))))

        # 价格：从 cost 文本解析，比如 "￥388 起" → 388
        price_min = None
        if p.cost:
            import re
            m = re.search(r"(\d+(?:\.\d+)?)", p.cost)
            if m:
                try:
                    price_min = float(m.group(1))
                except ValueError:
                    price_min = None
        return HotelItem(
            id=p.id,
            name=p.name,
            address=p.address,
            stars=stars,
            price_min=price_min,
            rating=p.rating,
            longitude=p.longitude,
            latitude=p.latitude,
            tel=p.tel,
            district=p.district,
            raw=p.raw,
        )


_instance: Optional[AmapHotelSearch] = None


def get_hotel_search() -> AmapHotelSearch:
    global _instance
    if _instance is None:
        try:
            _instance = AmapHotelSearch()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"酒店搜索初始化失败: {e}")
            raise ToolCallError(str(e)) from e
    return _instance
