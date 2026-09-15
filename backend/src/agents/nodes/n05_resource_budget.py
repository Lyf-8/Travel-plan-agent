"""Node5：资源预算节点

合并说明：合并旧 n06（酒店餐饮）+ n07（预算计算），使用 asyncio.gather 并发查询
酒店和餐饮资源，同时输出 hotels/foods + budget_breakdown。
对应旧节点：n06_hotel_food + n07_budget_calc

LangGraph 约定：返回增量 dict，不直接修改 state。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from loguru import logger

from ...llm.factory import llm_call
from ..prompts.node_prompts import RESOURCE_BUDGET_PROMPT
from ..state import AgentState
from ...tools.amap_food import get_food_search
from ...tools.amap_hotel import get_hotel_search
from ...utils.helpers import extract_json_from_text, safe_float


NODE_NAME = "n05_resource_budget"


async def _search_hotels(
    destination: str,
    poi_candidates: list[dict],
    budget_max: float,
) -> list[dict]:
    hotel_search = get_hotel_search()
    center_lng: float | None = None
    center_lat: float | None = None
    valid_pois = [p for p in poi_candidates if p.get("longitude") and p.get("latitude")]
    if valid_pois:
        lons = [float(p["longitude"]) for p in valid_pois]
        lats = [float(p["latitude"]) for p in valid_pois]
        center_lng = sum(lons) / len(lons)
        center_lat = sum(lats) / len(lats)

    max_cost_per_night = None
    if budget_max and budget_max > 0:
        max_cost_per_night = budget_max * 0.4 / max(1, 1)

    hotels_raw = await hotel_search.search(
        city=destination,
        near_lng=center_lng,
        near_lat=center_lat,
        radius=5000,
        min_rating=3.5,
        page_size=15,
    )

    hotels_out = []
    for h in hotels_raw:
        d = asdict(h)
        d.pop("raw", None)
        if max_cost_per_night and d.get("price_min") and d["price_min"] > max_cost_per_night * 1.5:
            continue
        hotels_out.append(d)
    return hotels_out


async def _search_foods(
    destination: str,
    poi_candidates: list[dict],
    budget_max: float,
    food_prefs: list[str],
) -> list[dict]:
    food_search = get_food_search()
    foods_out: list[dict] = []
    seen_ids = set()

    valid_pois = [p for p in poi_candidates if p.get("longitude") and p.get("latitude")]
    search_points = []

    if valid_pois:
        for p in valid_pois[:5]:
            search_points.append((float(p["longitude"]), float(p["latitude"])))
    if not search_points:
        search_points.append((None, None))

    cuisines = ["all"]
    if food_prefs:
        pref_to_cuisine = {
            "川菜": "chinese", "粤菜": "chinese", "湘菜": "chinese",
            "中餐": "chinese", "西餐": "western", "日料": "japanese_korean",
            "韩餐": "japanese_korean", "火锅": "hotpot", "小吃": "snack",
        }
        extra = set()
        for pref in food_prefs:
            for k, v in pref_to_cuisine.items():
                if k in pref:
                    extra.add(v)
        if extra:
            cuisines = list(extra)

    max_avg_cost = None
    if budget_max and budget_max > 0:
        max_avg_cost = budget_max * 0.25 / max(1, 3)

    for cuisine in cuisines:
        for lng, lat in search_points:
            try:
                if lng is not None and lat is not None:
                    items = await food_search.search(
                        city=destination,
                        cuisine=cuisine,
                        near_lng=lng,
                        near_lat=lat,
                        radius=3000,
                        min_rating=3.5,
                        max_cost=max_avg_cost,
                        page_size=10,
                    )
                else:
                    items = await food_search.search(
                        city=destination,
                        cuisine=cuisine,
                        min_rating=3.5,
                        max_cost=max_avg_cost,
                        page_size=15,
                    )
                for f in items:
                    fid = f.id
                    if fid and fid not in seen_ids:
                        seen_ids.add(fid)
                        d = asdict(f)
                        d.pop("raw", None)
                        foods_out.append(d)
            except Exception as e:
                logger.warning(f"[Node5] 餐饮搜索失败 cuisine={cuisine}: {e}")

    return foods_out


async def execute(state: AgentState) -> dict:
    updates: dict = {"node_executed": [NODE_NAME]}
    try:
        destination = state.get("destination", "")
        logger.info(f"[Node5] 开始资源预算（酒店+餐饮+预算），目的地: {destination}")

        if not destination:
            raise ValueError("destination 为空")

        preferences = state.get("preferences", {}) or {}
        food_prefs = preferences.get("food", []) if isinstance(preferences, dict) else []
        poi_candidates = state.get("poi_candidates", []) or []
        budget_max = state.get("budget_max", 0.0) or 0.0

        logger.info(f"[Node5] 并发查询酒店和餐饮")
        hotel_task = _search_hotels(destination, poi_candidates, budget_max)
        food_task = _search_foods(destination, poi_candidates, budget_max, food_prefs)

        hotels_raw, foods_raw = await asyncio.gather(
            hotel_task, food_task, return_exceptions=False
        )
        logger.info(
            f"[Node5] 资源查询完成: 酒店 {len(hotels_raw)} 家, 餐饮 {len(foods_raw)} 家"
        )

        input_data = {
            "destination": destination,
            "travel_days": state.get("travel_days", 0),
            "budget_min": state.get("budget_min", 0.0),
            "budget_max": budget_max,
            "preferences": preferences,
            "poi_candidates": poi_candidates,
            "routes": state.get("routes", []),
            "hotels_raw": hotels_raw,
            "foods_raw": foods_raw,
        }
        user_content = json.dumps(input_data, ensure_ascii=False)

        messages = [
            {"role": "system", "content": RESOURCE_BUDGET_PROMPT},
            {"role": "user", "content": user_content},
        ]

        resp = await llm_call(messages)
        updates["total_tokens"] = resp.usage.total_tokens
        updates["total_cost"] = resp.usage.cost_cny

        result = extract_json_from_text(resp.content)
        routes = state.get("routes", []) or []
        travel_days = state.get("travel_days", 0)
        if not result:
            logger.warning(f"[Node5] LLM 输出解析失败，使用原始数据")
            hotels = hotels_raw
            foods = foods_raw
            budget_breakdown = _fallback_budget(hotels_raw, foods_raw, routes, travel_days)
        else:
            hotels = result.get("recommended_hotels", hotels_raw) or hotels_raw
            foods = result.get("recommended_foods", foods_raw) or foods_raw
            raw_breakdown = result.get("budget_breakdown")
            if isinstance(raw_breakdown, dict) and raw_breakdown:
                budget_breakdown = raw_breakdown
            else:
                budget_breakdown = _fallback_budget(hotels_raw, foods_raw, routes, travel_days)

        updates["hotels"] = hotels
        updates["foods"] = foods
        updates["budget_breakdown"] = budget_breakdown
        logger.info(
            f"[Node5] 资源预算完成: hotels={len(hotels)}, "
            f"foods={len(foods)}, budget_total={budget_breakdown.get('total', 0)}"
        )

    except Exception as e:
        err_msg = f"[Node5] 资源预算失败: {e}"
        logger.error(err_msg)
        updates["errors"] = [err_msg]

    return updates


def _fallback_budget(
    hotels: list[dict],
    foods: list[dict],
    routes: list[dict],
    travel_days: int,
) -> dict:
    days = max(1, travel_days)
    hotel_cost = 0.0
    if hotels:
        prices = [safe_float(h.get("price_min"), 0) for h in hotels if h.get("price_min")]
        if prices:
            hotel_cost = sum(prices) / len(prices) * days

    food_cost = 0.0
    if foods:
        costs = [safe_float(f.get("avg_cost"), 0) for f in foods if f.get("avg_cost")]
        if costs:
            avg_food = sum(costs) / len(costs)
            food_cost = avg_food * 3 * days

    transport_cost = 0.0
    for r in routes:
        taxi = safe_float(r.get("taxi_cost"), 0)
        if taxi:
            transport_cost += taxi
    if transport_cost == 0:
        transport_cost = 50.0 * days

    ticket_cost = 0.0
    if not ticket_cost:
        ticket_cost = 100.0 * days

    other = 50.0 * days
    total = hotel_cost + food_cost + transport_cost + ticket_cost + other

    return {
        "transport": round(transport_cost, 2),
        "food": round(food_cost, 2),
        "hotel": round(hotel_cost, 2),
        "tickets": round(ticket_cost, 2),
        "other": round(other, 2),
        "total": round(total, 2),
    }
