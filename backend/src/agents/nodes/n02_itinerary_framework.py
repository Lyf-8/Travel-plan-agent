"""Node2：行程框架设计节点

合并说明：合并旧 n02（行程分解）+ n08（行程编排），跳过 daily_plan_outline 中间态，
直接生成完整的 arranged_itinerary 逐日时间轴行程。
对应旧节点：n02_itinerary_decompose + n08_itinerary_arrange

LangGraph 约定：返回增量 dict，不直接修改 state。
"""
from __future__ import annotations

import json

from loguru import logger

from ...llm.factory import llm_call
from ..prompts.node_prompts import ITINERARY_FRAMEWORK_PROMPT
from ..state import AgentState
from ...utils.helpers import extract_json_from_text


NODE_NAME = "n02_itinerary_framework"


async def execute(state: AgentState) -> dict:
    updates: dict = {"node_executed": [NODE_NAME]}
    try:
        destination = state.get("destination", "")
        travel_days = state.get("travel_days", 0)
        logger.info(f"[Node2] 开始行程框架设计，目的地: {destination}, 天数: {travel_days}")

        if not destination or travel_days <= 0:
            raise ValueError(f"参数不完整: destination={destination}, travel_days={travel_days}")

        input_data = {
            "destination": destination,
            "travel_days": travel_days,
            "preferences": state.get("preferences", {}),
            "travel_dates": state.get("travel_dates", []),
            "budget_max": state.get("budget_max", 0.0),
            "poi_candidates": state.get("poi_candidates", []),
            "routes": state.get("routes", []),
            "weather_info": state.get("weather_info", {}),
            "recommended_hotels": state.get("hotels", []),
            "recommended_foods": state.get("foods", []),
            "budget_breakdown": state.get("budget_breakdown", {}),
            "feedback": state.get("feedback", ""),
        }
        user_content = json.dumps(input_data, ensure_ascii=False)

        messages = [
            {"role": "system", "content": ITINERARY_FRAMEWORK_PROMPT},
            {"role": "user", "content": user_content},
        ]

        resp = await llm_call(messages)
        updates["total_tokens"] = resp.usage.total_tokens
        updates["total_cost"] = resp.usage.cost_cny

        result = extract_json_from_text(resp.content)
        if not result:
            raise ValueError(f"LLM 返回无法解析为 JSON: {resp.content[:200]}")

        arranged = result.get("arranged_itinerary", []) or []
        if not arranged:
            raise ValueError("arranged_itinerary 为空")

        updates["arranged_itinerary"] = arranged
        logger.info(f"[Node2] 行程框架设计完成，共 {len(arranged)} 天行程")

    except Exception as e:
        err_msg = f"[Node2] 行程框架设计失败: {e}"
        logger.error(err_msg)
        updates["errors"] = [err_msg]

    return updates
