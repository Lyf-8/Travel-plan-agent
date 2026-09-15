"""高德餐饮搜索（复用 POI 搜索 + 餐饮分类）

餐饮 POI 分类编码（节选）：
    050000    餐饮服务
    050100    中餐厅
    050200    西餐厅
    050300    日韩菜
    050500    火锅
    050900    小吃快餐店
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger

from ..core.exceptions import ToolCallError
from .amap_poi import AmapPOISearch, POIItem, get_poi_search


FOOD_CATEGORIES = {
    "all": "050000",
    "chinese": "050100",
    "western": "050200",
    "japanese_korean": "050300",
    "hotpot": "050500",
    "snack": "050900",
}


@dataclass
class FoodItem:
    """标准化餐饮结构"""
    id: str
    name: str
    address: Optional[str]
    cuisine_type: Optional[str] = None    # 菜系分类
    avg_cost: Optional[float] = None      # 人均消费（元）
    rating: Optional[float] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    tel: Optional[str] = None
    district: Optional[str] = None
    raw: Optional[dict] = None


class AmapFoodSearch:
    def __init__(self, poi: Optional[AmapPOISearch] = None) -> None:
        self.poi = poi or get_poi_search()

    async def search(
        self,
        city: str,
        keywords: Optional[str] = None,
        cuisine: str = "all",                        # all / chinese / western / ...
        near_lng: Optional[float] = None,            # 附近搜索：景点附近
        near_lat: Optional[float] = None,
        radius: int = 3000,                          # 3km
        min_rating: Optional[float] = None,
        max_cost: Optional[float] = None,            # 预算内（人均）
        page_size: int = 20,
        page: int = 1,
    ) -> list[FoodItem]:
        cat_code = FOOD_CATEGORIES.get(cuisine, FOOD_CATEGORIES["all"])
        kw = keywords or ""

        if near_lng is not None and near_lat is not None:
            pois = await self.poi.around_search(
                longitude=near_lng,
                latitude=near_lat,
                keywords=kw,
                categories=cat_code,
                radius=radius,
                offset=page_size,
                page=page,
            )
        else:
            pois = await self.poi.keywords_search(
                keywords=kw,
                city=city,
                citylimit=True,
                categories=cat_code,
                offset=page_size,
                page=page,
            )

        items: list[FoodItem] = []
        for p in pois:
            f = self._poi_to_food(p, cuisine)
            if min_rating is not None and (f.rating or 0) < min_rating:
                continue
            if max_cost is not None and f.avg_cost is not None and f.avg_cost > max_cost:
                continue
            items.append(f)
        return items

    @staticmethod
    def _poi_to_food(p: POIItem, cuisine_hint: str) -> FoodItem:
        import re
        avg_cost = None
        if p.cost:
            m = re.search(r"(\d+(?:\.\d+)?)", p.cost)
            if m:
                try:
                    avg_cost = float(m.group(1))
                except ValueError:
                    avg_cost = None
        # type 字段一般是 "餐饮服务;中餐厅;四川火锅" 这种分号结构
        cuisine_type = cuisine_hint
        if p.category:
            parts = [x for x in p.category.split(";") if x]
            if parts:
                cuisine_type = parts[-1]
        return FoodItem(
            id=p.id,
            name=p.name,
            address=p.address,
            cuisine_type=cuisine_type,
            avg_cost=avg_cost,
            rating=p.rating,
            longitude=p.longitude,
            latitude=p.latitude,
            tel=p.tel,
            district=p.district,
            raw=p.raw,
        )


_instance: Optional[AmapFoodSearch] = None


def get_food_search() -> AmapFoodSearch:
    global _instance
    if _instance is None:
        try:
            _instance = AmapFoodSearch()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"餐饮搜索初始化失败: {e}")
            raise ToolCallError(str(e)) from e
    return _instance
