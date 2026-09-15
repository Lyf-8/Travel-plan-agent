"""Node4：旅行上下文节点

合并说明：合并旧 n04（路线规划）+ n05（天气查询），使用 asyncio.gather 并发调用
高德路线 API 和天气 API，同时输出 routes + weather_info。
对应旧节点：n04_route_planning + n05_weather_query

LangGraph 约定：返回增量 dict，不直接修改 state。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from loguru import logger

from ...llm.factory import llm_call
from ..prompts.node_prompts import TRAVEL_CONTEXT_PROMPT
from ..state import AgentState
from ...tools.amap_route import get_route_planner
from ...tools.amap_weather import get_weather
from ...utils.helpers import extract_json_from_text


NODE_NAME = "n04_travel_context"


def _city_name_to_adcode(city_name: str) -> str:
    mapping = {
        "北京": "110000",
        "上海": "310000",
        "广州": "440100",
        "深圳": "440300",
        "杭州": "330100",
        "成都": "510100",
        "西安": "610100",
        "南京": "320100",
        "苏州": "320500",
        "武汉": "420100",
        "重庆": "500000",
        "天津": "120000",
        "厦门": "350200",
        "青岛": "370200",
        "长沙": "430100",
    }
    return mapping.get(city_name, "")


async def _call_weather_api(destination: str) -> dict:
    weather = get_weather()
    adcode = _city_name_to_adcode(destination)
    if not adcode:
        return {}
    result = await weather.get_all(adcode)
    out: dict = {}
    if result.live:
        out["live"] = asdict(result.live)
    if result.forecasts:
        out["forecasts"] = [asdict(f) for f in result.forecasts]
    return out


async def _call_route_api(poi_candidates: list[dict], destination: str) -> list[dict]:
    planner = get_route_planner()
    routes_out: list[dict] = []

    valid_pois = [p for p in poi_candidates if p.get("longitude") and p.get("latitude")]
    if len(valid_pois) < 2:
        return routes_out

    day_groups: dict[int, list[dict]] = {}
    for p in valid_pois:
        day = int(p.get("day", 1))
        day_groups.setdefault(day, []).append(p)

    for day, pois in day_groups.items():
        day_routes: list[dict] = []
        for i in range(len(pois) - 1):
            a = pois[i]
            b = pois[i + 1]
            try:
                plan = await planner.auto_plan(
                    start_lng=float(a["longitude"]),
                    start_lat=float(a["latitude"]),
                    end_lng=float(b["longitude"]),
                    end_lat=float(b["latitude"]),
                    city=destination,
                )
                d = asdict(plan)
                d.pop("raw", None)
                d["day"] = day
                d["from_poi"] = a.get("name", "")
                d["to_poi"] = b.get("name", "")
                d["from_id"] = a.get("id", "")
                d["to_id"] = b.get("id", "")
                day_routes.append(d)
            except Exception as e:
                logger.warning(f"[Node4] 路线规划失败 {a.get('name')}->{b.get('name')}: {e}")
        routes_out.extend(day_routes)

    return routes_out


async def execute(state: AgentState) -> dict:
    updates: dict = {"node_executed": [NODE_NAME]}
    try:
        destination = state.get("destination", "")
        logger.info(f"[Node4] 开始旅行上下文（路线+天气），目的地: {destination}")

        if not destination:
            raise ValueError("destination 为空")

        poi_candidates = state.get("poi_candidates", []) or []
        logger.info(f"[Node4] 并发调用天气 API 和路线 API")
        weather_task = _call_weather_api(destination)
        route_task = _call_route_api(poi_candidates, destination)

        weather_info_raw, routes_raw = await asyncio.gather(
            weather_task, route_task, return_exceptions=False
        )
        logger.info(
            f"[Node4] API 调用完成: 天气={'有' if weather_info_raw else '无'}, "
            f"路线段数={len(routes_raw)}"
        )

        input_data = {
            "destination": destination,
            "travel_days": state.get("travel_days", 0),
            "preferences": state.get("preferences", {}),
            "poi_candidates": poi_candidates,
            "weather_info_raw": weather_info_raw,
            "routes_raw": routes_raw,
        }
        user_content = json.dumps(input_data, ensure_ascii=False)

        messages = [
            {"role": "system", "content": TRAVEL_CONTEXT_PROMPT},
            {"role": "user", "content": user_content},
        ]

        resp = await llm_call(messages)
        updates["total_tokens"] = resp.usage.total_tokens
        updates["total_cost"] = resp.usage.cost_cny

        result = extract_json_from_text(resp.content)
        if not result:
            logger.warning(f"[Node4] LLM 输出解析失败，使用原始 API 数据")
            routes, weather_info = routes_raw, weather_info_raw
        else:
            routes = result.get("routes", routes_raw) or routes_raw
            weather_info = result.get("weather_info", weather_info_raw) or weather_info_raw

        updates["routes"] = routes
        updates["weather_info"] = weather_info
        logger.info(
            f"[Node4] 旅行上下文完成: routes={len(routes)} 段, "
            f"weather={'有' if weather_info else '无'}"
        )

    except Exception as e:
        err_msg = f"[Node4] 旅行上下文失败: {e}"
        logger.error(err_msg)
        updates["errors"] = [err_msg]

    return updates
