"""高德天气查询工具
文档：https://lbs.amap.com/api/webservice/guide/api/weatherinfo

两种天气：
    base : 实况天气（温度、湿度、风力...）
    all  : 预报天气（未来 3-4 天预报）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx
from loguru import logger

from ..core.config import get_settings
from ..core.exceptions import AmapAPIError, ConfigError


@dataclass
class LiveWeather:
    """实况天气"""
    province: str
    city: str
    adcode: str
    weather: str               # 天气现象（如"多云"）
    temperature: str           # 温度（摄氏度，文本）
    winddirection: str         # 风向
    windpower: str             # 风力
    humidity: str              # 湿度（%）
    reporttime: str            # 发布时间


@dataclass
class ForecastDay:
    """某日预报"""
    date: str                  # YYYY-MM-DD
    week: str                  # 星期几（数字）
    dayweather: str            # 白天天气
    nightweather: str          # 夜间天气
    daytemp: str               # 白天最高温
    nighttemp: str             # 夜间最低温
    daywind: str               # 白天风向
    nightwind: str             # 夜间风向
    daypower: str              # 白天风力
    nightpower: str            # 夜间风力


@dataclass
class WeatherResult:
    live: Optional[LiveWeather] = None
    forecasts: list[ForecastDay] = None  # type: ignore[assignment]


class AmapWeather:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.AMAP_KEY:
            raise ConfigError("AMAP_KEY 未配置")
        self.api_key = settings.AMAP_KEY
        self.base_url = settings.AMAP_BASE_URL.rstrip("/")
        self.timeout = settings.AMAP_TIMEOUT

    async def _get(self, params: dict) -> dict:
        url = f"{self.base_url}/weather/weatherInfo"
        p = {"key": self.api_key, **params}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=p)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:  # noqa: BLE001
            raise AmapAPIError(f"天气查询失败: {e}") from e
        if str(data.get("status")) != "1":
            info = data.get("info", "unknown")
            infocode = data.get("infocode", "-1")
            logger.error(f"高德天气错误: infocode={infocode} info={info}")
            raise AmapAPIError(message=info, data={"infocode": infocode})
        return data

    async def get_live(self, city_adcode: str) -> Optional[LiveWeather]:
        """查询实况天气，city_adcode=城市编码（如北京=110000）"""
        data = await self._get({"city": city_adcode, "extensions": "base"})
        lives = data.get("lives") or []
        if not lives:
            return None
        l = lives[0]
        return LiveWeather(
            province=l.get("province", ""),
            city=l.get("city", ""),
            adcode=l.get("adcode", ""),
            weather=l.get("weather", ""),
            temperature=l.get("temperature", ""),
            winddirection=l.get("winddirection", ""),
            windpower=l.get("windpower", ""),
            humidity=l.get("humidity", ""),
            reporttime=l.get("reporttime", ""),
        )

    async def get_forecast(self, city_adcode: str) -> list[ForecastDay]:
        """查询未来几天的天气预报"""
        data = await self._get({"city": city_adcode, "extensions": "all"})
        casts = ((data.get("forecasts") or [{}])[0]).get("casts") or []
        result: list[ForecastDay] = []
        for c in casts:
            result.append(ForecastDay(
                date=c.get("date", ""),
                week=c.get("week", ""),
                dayweather=c.get("dayweather", ""),
                nightweather=c.get("nightweather", ""),
                daytemp=c.get("daytemp", ""),
                nighttemp=c.get("nighttemp", ""),
                daywind=c.get("daywind", ""),
                nightwind=c.get("nightwind", ""),
                daypower=c.get("daypower", ""),
                nightpower=c.get("nightpower", ""),
            ))
        return result

    async def get_all(self, city_adcode: str) -> WeatherResult:
        """同时获取实况+预报"""
        live, forecasts = await _run_parallel(
            self.get_live(city_adcode),
            self.get_forecast(city_adcode),
        )
        return WeatherResult(live=live, forecasts=forecasts or [])


async def _run_parallel(coro_a, coro_b):
    import asyncio
    return await asyncio.gather(coro_a, coro_b, return_exceptions=False)


_instance: Optional[AmapWeather] = None


def get_weather() -> AmapWeather:
    global _instance
    if _instance is None:
        _instance = AmapWeather()
    return _instance
