"""高德路线规划工具
支持：驾车 / 步行 / 公交 / 骑行
文档：
    驾车：https://lbs.amap.com/api/webservice/guide/api/direction/#driving
    步行：https://lbs.amap.com/api/webservice/guide/api/direction/#walking
    公交：https://lbs.amap.com/api/webservice/guide/api/direction/#integrated
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import httpx
from loguru import logger

from ..core.config import get_settings
from ..core.exceptions import AmapAPIError, ConfigError


# 输出类型（方便 Agent 处理）
RouteStrategy = Literal["driving", "walking", "transit", "riding"]


@dataclass
class RouteStep:
    instruction: str            # 行走指示
    road: Optional[str] = None  # 道路名
    distance_m: int = 0         # 本段距离
    duration_sec: int = 0       # 本段耗时
    start_lng: Optional[float] = None
    start_lat: Optional[float] = None
    end_lng: Optional[float] = None
    end_lat: Optional[float] = None
    # 公交专用
    bus_line: Optional[str] = None
    bus_stops: int = 0


@dataclass
class RoutePlan:
    strategy: RouteStrategy
    distance_m: int = 0               # 总距离
    duration_sec: int = 0             # 总耗时
    steps: list[RouteStep] = field(default_factory=list)  # 分段
    tolls: Optional[float] = None     # 过路费 (驾车)
    taxi_cost: Optional[float] = None # 打车费用估算
    raw: Optional[dict] = None


class AmapRoutePlanner:
    """高德路线规划封装"""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.AMAP_KEY:
            raise ConfigError("AMAP_KEY 未配置")
        self.api_key = settings.AMAP_KEY
        self.base_url = settings.AMAP_BASE_URL.rstrip("/")
        self.timeout = settings.AMAP_TIMEOUT

    async def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        p = {"key": self.api_key, **params}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=p)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:  # noqa: BLE001
            raise AmapAPIError(f"路线规划请求失败: {e}") from e
        if str(data.get("status")) != "1":
            info = data.get("info", "unknown")
            infocode = data.get("infocode", "-1")
            logger.error(f"高德路线返回错误: infocode={infocode} info={info}")
            raise AmapAPIError(message=f"高德 API 错误: {info}", data={"infocode": infocode})
        return data

    # ---------- 坐标工具 ----------
    @staticmethod
    def _fmt(lng: float, lat: float) -> str:
        return f"{lng:.6f},{lat:.6f}"

    # ============================================================
    # 1. 驾车规划
    # ============================================================
    async def driving(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        strategy: int = 10,  # 10=速度优先 20=费用优先 30=距离优先 40=躲避拥堵
        extensions: str = "all",
    ) -> Optional[RoutePlan]:
        params = {
            "origin": self._fmt(start_lng, start_lat),
            "destination": self._fmt(end_lng, end_lat),
            "strategy": strategy,
            "extensions": extensions,
        }
        data = await self._get("/direction/driving", params)
        routes = (data.get("route") or {}).get("paths") or []
        if not routes:
            return None
        return self._parse_driving(routes[0])

    # ============================================================
    # 2. 步行规划
    # ============================================================
    async def walking(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
    ) -> Optional[RoutePlan]:
        params = {
            "origin": self._fmt(start_lng, start_lat),
            "destination": self._fmt(end_lng, end_lat),
        }
        data = await self._get("/direction/walking", params)
        routes = (data.get("route") or {}).get("paths") or []
        if not routes:
            return None
        return self._parse_walking(routes[0])

    # ============================================================
    # 3. 公交规划（综合换乘）
    # ============================================================
    async def transit(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        city: str = "北京",     # 必须传城市名或城市编码
        cityd: Optional[str] = None,  # 终点城市（跨城时需传）
        strategy: int = 0,      # 0=最快捷 1=少换乘 2=少步行 3=不坐地铁 5=地铁优先
    ) -> Optional[RoutePlan]:
        params = {
            "origin": self._fmt(start_lng, start_lat),
            "destination": self._fmt(end_lng, end_lat),
            "city": city,
            "strategy": strategy,
        }
        if cityd:
            params["cityd"] = cityd
        data = await self._get("/direction/transit/integrated", params)
        routes = (data.get("route") or {}).get("transits") or []
        if not routes:
            return None
        return self._parse_transit(routes[0])

    # ============================================================
    # 4. 智能推荐（根据距离自动选方式）
    # ============================================================
    async def auto_plan(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        **kwargs,
    ) -> RoutePlan:
        """按距离自动推荐：步行<1km，骑行<5km，公交<50km，驾车其他"""
        from math import radians, sin, cos, sqrt, atan2
        R = 6371000.0  # 地球半径 (米)
        lat1, lat2 = radians(start_lat), radians(end_lat)
        dlat = radians(end_lat - start_lat)
        dlng = radians(end_lng - start_lng)
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
        est_dist = R * 2 * atan2(sqrt(a), sqrt(1 - a))

        strategy: RouteStrategy = "driving"
        if est_dist < 1000:
            strategy = "walking"
        elif est_dist < 5000:
            strategy = "riding"
        elif est_dist < 50000 and kwargs.get("city"):
            strategy = "transit"

        if strategy == "walking":
            r = await self.walking(start_lng, start_lat, end_lng, end_lat)
        elif strategy == "transit":
            r = await self.transit(start_lng, start_lat, end_lng, end_lat, **kwargs)
        else:
            r = await self.driving(start_lng, start_lat, end_lng, end_lat, **kwargs)

        if r is None:
            # 任何方式失败都回退为"仅距离估算"
            dur_sec = int(est_dist / 1.4) if strategy == "walking" else int(est_dist / 15.0)
            r = RoutePlan(strategy=strategy, distance_m=int(est_dist), duration_sec=dur_sec)
        return r

    # ============================================================
    # 解析
    # ============================================================
    @staticmethod
    def _parse_steps(steps_raw: list[dict]) -> list[RouteStep]:
        out: list[RouteStep] = []
        for s in steps_raw:
            polyline = s.get("polyline") or ""
            first, last = None, None
            if polyline:
                pts = polyline.split(";")
                if pts and "," in pts[0]:
                    first = pts[0].split(",")
                if pts and "," in pts[-1]:
                    last = pts[-1].split(",")
            step = RouteStep(
                instruction=s.get("instruction", ""),
                road=s.get("road") or None,
                distance_m=int(s.get("distance") or 0),
                duration_sec=int(s.get("duration") or 0),
                start_lng=float(first[0]) if first else None,
                start_lat=float(first[1]) if first else None,
                end_lng=float(last[0]) if last else None,
                end_lat=float(last[1]) if last else None,
            )
            out.append(step)
        return out

    def _parse_driving(self, r: dict) -> RoutePlan:
        steps = self._parse_steps(r.get("steps") or [])
        return RoutePlan(
            strategy="driving",
            distance_m=int(r.get("distance") or 0),
            duration_sec=int(r.get("duration") or 0),
            steps=steps,
            tolls=float(r["tolls"]) if r.get("tolls") not in (None, "") else None,
            raw=r,
        )

    def _parse_walking(self, r: dict) -> RoutePlan:
        steps = self._parse_steps(r.get("steps") or [])
        return RoutePlan(
            strategy="walking",
            distance_m=int(r.get("distance") or 0),
            duration_sec=int(r.get("duration") or 0),
            steps=steps,
            raw=r,
        )

    def _parse_transit(self, r: dict) -> RoutePlan:
        steps: list[RouteStep] = []
        for seg in r.get("segments") or []:
            for bus in (seg.get("bus") or {}).get("buslines") or []:
                steps.append(RouteStep(
                    instruction=f'乘坐 {bus.get("name","公交")}',
                    distance_m=int(bus.get("distance") or 0),
                    duration_sec=int(bus.get("duration") or 0),
                    bus_line=bus.get("name"),
                    bus_stops=len(bus.get("via_stops") or []) + 1,
                ))
            walking = seg.get("walking") or {}
            if walking:
                steps.append(RouteStep(
                    instruction="步行",
                    distance_m=int(walking.get("distance") or 0),
                    duration_sec=int(walking.get("duration") or 0),
                ))
        return RoutePlan(
            strategy="transit",
            distance_m=int(r.get("distance") or 0),
            duration_sec=int(r.get("duration") or 0),
            steps=steps,
            raw=r,
        )


_instance: Optional[AmapRoutePlanner] = None


def get_route_planner() -> AmapRoutePlanner:
    global _instance
    if _instance is None:
        _instance = AmapRoutePlanner()
    return _instance
