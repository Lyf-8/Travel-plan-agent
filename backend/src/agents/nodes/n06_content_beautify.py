"""Node6：内容美化节点

合并说明：保留旧 n09（行程美化）逻辑，直接从 arranged_itinerary 生成
富有感染力的 Markdown 格式 formatted_itinerary 文案。
对应旧节点：n09_itinerary_beautify

LangGraph 约定：返回增量 dict，不直接修改 state。
"""
from __future__ import annotations

import json

from loguru import logger

from ...llm.factory import llm_call
from ..prompts.node_prompts import CONTENT_BEAUTIFY_PROMPT
from ..state import AgentState


NODE_NAME = "n06_content_beautify"


async def execute(state: AgentState) -> dict:
    updates: dict = {"node_executed": [NODE_NAME]}
    try:
        arranged_itinerary = state.get("arranged_itinerary", []) or []
        logger.info(f"[Node6] 开始内容美化，逐日行程数: {len(arranged_itinerary)}")

        if not arranged_itinerary:
            raise ValueError("arranged_itinerary 为空")

        input_data = {
            "destination": state.get("destination", ""),
            "travel_days": state.get("travel_days", 0),
            "preferences": state.get("preferences", {}),
            "arranged_itinerary": arranged_itinerary,
            "weather_info": state.get("weather_info", {}),
            "budget_breakdown": state.get("budget_breakdown", {}),
        }
        user_content = json.dumps(input_data, ensure_ascii=False)

        messages = [
            {"role": "system", "content": CONTENT_BEAUTIFY_PROMPT},
            {"role": "user", "content": user_content},
        ]

        resp = await llm_call(messages)
        updates["total_tokens"] = resp.usage.total_tokens
        updates["total_cost"] = resp.usage.cost_cny

        content = resp.content.strip()
        if not content:
            raise ValueError("LLM 返回空内容")

        if content.startswith("```markdown"):
            content = content[len("```markdown"):]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        updates["formatted_itinerary"] = content
        logger.info(
            f"[Node6] 内容美化完成: Markdown 长度 {len(content)} 字符"
        )

    except Exception as e:
        err_msg = f"[Node6] 内容美化失败: {e}"
        logger.error(err_msg)
        updates["errors"] = [err_msg]

    return updates
