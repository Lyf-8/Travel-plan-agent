"""Node7：地图与分享节点

合并说明：合并旧 n10（地图生成）+ 新增短链接数据准备，输出前端地图可渲染的
map_data 结构 + share_payload 分享预览字典。
对应旧节点：n10_map_generation + 新增短链接准备

LangGraph 约定：返回增量 dict，不直接修改 state。
"""
from __future__ import annotations

import json

from loguru import logger

from ...llm.factory import llm_call
from ..prompts.node_prompts import MAP_SHARE_PROMPT
from ..state import AgentState
from ...utils.helpers import extract_json_from_text, safe_float


NODE_NAME = "n07_map_and_share"


def _build_share_payload(state: AgentState) -> dict:
    destination = state.get("destination", "")
    travel_days = state.get("travel_days", 0)
    preferences = state.get("preferences", {}) or {}
    budget_breakdown = state.get("budget_breakdown", {}) or {}
    poi_candidates = state.get("poi_candidates", []) or []
    title = f"{destination}{travel_days}日游行程"
    desc_parts = []
    if preferences:
        style = preferences.get("travel_style", "")
        if style:
            desc_parts.append(f"风格：{style}")
        interests = preferences.get("interests", [])
        if interests:
            desc_parts.append(f"主题：{'、'.join(interests[:3])}")
    if budget_breakdown:
        total = budget_breakdown.get("total", 0)
        if total:
            desc_parts.append(f"预算：约{int(total)}元")
    description = " | ".join(desc_parts) if desc_parts else f"为您定制的{destination}旅行方案"

    first_poi_lng = None
    first_poi_lat = None
    for p in poi_candidates:
        if p.get("longitude") and p.get("latitude"):
            first_poi_lng = safe_float(p.get("longitude"))
            first_poi_lat = safe_float(p.get("latitude"))
            break

    return {
        "title": title,
        "description": description,
        "image_hint": f"{destination}旅行",
        "destination": destination,
        "travel_days": travel_days,
        "travel_dates": state.get("travel_dates", []),
        "budget_total": budget_breakdown.get("total", 0) if budget_breakdown else 0,
        "poi_count": len(poi_candidates),
        "center_lng": first_poi_lng,
        "center_lat": first_poi_lat,
        "summary_preview": (state.get("formatted_itinerary", "") or "")[:200],
        "short_link_params": {
            "sid": state.get("session_id", ""),
            "dest": destination,
            "days": travel_days,
        },
    }


async def execute(state: AgentState) -> dict:
    updates: dict = {"node_executed": [NODE_NAME]}
    try:
        destination = state.get("destination", "")
        poi_candidates = state.get("poi_candidates", []) or []
        logger.info(f"[Node7] 开始地图与分享数据组装，POI 数: {len(poi_candidates)}")

        input_data = {
            "destination": destination,
            "travel_days": state.get("travel_days", 0),
            "poi_candidates": poi_candidates,
            "routes": state.get("routes", []),
            "arranged_itinerary": state.get("arranged_itinerary", []),
        }
        user_content = json.dumps(input_data, ensure_ascii=False)

        messages = [
            {"role": "system", "content": MAP_SHARE_PROMPT},
            {"role": "user", "content": user_content},
        ]

        resp = await llm_call(messages)
        updates["total_tokens"] = resp.usage.total_tokens
        updates["total_cost"] = resp.usage.cost_cny

        result = extract_json_from_text(resp.content)
        routes = state.get("routes", []) or []
        if not result:
            logger.warning(f"[Node7] LLM 输出解析失败，使用 fallback 地图数据")
            map_data = _fallback_map_data(poi_candidates, routes)
        else:
            raw_map = result.get("map_data")
            if isinstance(raw_map, dict) and raw_map:
                map_data = raw_map
            else:
                map_data = _fallback_map_data(poi_candidates, routes)

        # 分享快照：同时挂到 map_data 内（Node8 会 pop 出来提到顶层）
        share_payload = _build_share_payload(state)
        map_data["share_payload"] = share_payload

        updates["map_data"] = map_data
        updates["share_payload"] = share_payload
        logger.info(
            f"[Node7] 地图与分享完成: markers={len(map_data.get('markers', []))}, "
            f"polylines={len(map_data.get('polylines', []))}"
        )

    except Exception as e:
        err_msg = f"[Node7] 地图与分享失败: {e}"
        logger.error(err_msg)
        updates["errors"] = [err_msg]

    return updates


def _fallback_map_data(poi_candidates: list[dict], routes: list[dict]) -> dict:
    markers: list[dict] = []
    lons: list[float] = []
    lats: list[float] = []
    order_counter: dict[int, int] = {}

    for p in poi_candidates:
        lng = safe_float(p.get("longitude"))
        lat = safe_float(p.get("latitude"))
        day = int(p.get("day", 1))
        order_counter[day] = order_counter.get(day, 0) + 1
        if lng and lat:
            lons.append(lng)
            lats.append(lat)
            markers.append({
                "poi_id": p.get("id", ""),
                "name": p.get("name", ""),
                "lng": lng,
                "lat": lat,
                "day": day,
                "order": order_counter[day],
            })

    center_lng = 0.0
    center_lat = 0.0
    if lons and lats:
        center_lng = round(sum(lons) / len(lons), 6)
        center_lat = round(sum(lats) / len(lats), 6)

    polylines: list[dict] = []
    for r in routes:
        day = r.get("day", 1)
        points: list[list[float]] = []
        steps = r.get("steps", []) or []
        for s in steps:
            slng = s.get("start_lng")
            slat = s.get("start_lat")
            if slng is not None and slat is not None:
                points.append([safe_float(slng), safe_float(slat)])
            elng = s.get("end_lng")
            elat = s.get("end_lat")
            if elng is not None and elat is not None:
                points.append([safe_float(elng), safe_float(elat)])
        if not points:
            continue
        polylines.append({
            "day": day,
            "from": r.get("from_poi", ""),
            "to": r.get("to_poi", ""),
            "points": points,
        })

    zoom = 12
    if lons and lats:
        lon_span = max(lons) - min(lons)
        lat_span = max(lats) - min(lats)
        max_span = max(lon_span, lat_span)
        if max_span > 0.5:
            zoom = 9
        elif max_span > 0.2:
            zoom = 10
        elif max_span > 0.08:
            zoom = 11
        else:
            zoom = 13

    return {
        "center": {"lng": center_lng, "lat": center_lat},
        "markers": markers,
        "polylines": polylines,
        "zoom": zoom,
    }
