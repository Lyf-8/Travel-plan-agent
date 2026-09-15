"""Node8：最终结果输出节点

将全部节点输出汇聚为前端可用的完整 JSON。
不再额外调用 LLM（数据已由前 7 个节点生成），直接组装即可。

LangGraph 约定：返回增量 dict，不直接修改 state。
"""
from __future__ import annotations

from loguru import logger

from ..state import AgentState


NODE_NAME = "n08_final_output"


def _build_fallback_output(state: AgentState) -> dict:
    map_data = dict(state.get("map_data", {}) or {})
    share_payload = map_data.pop("share_payload", None)
    budget_breakdown = state.get("budget_breakdown", {}) or {}

    final = {
        "summary": {
            "destination": state.get("destination", ""),
            "travel_days": state.get("travel_days", 0),
            "travel_dates": state.get("travel_dates", []),
            "budget_min": state.get("budget_min", 0.0),
            "budget_max": state.get("budget_max", 0.0),
            "preferences": state.get("preferences", {}),
            "intent_confidence": state.get("intent_confidence", 0.0),
            "needs_clarification": state.get("needs_clarification", False),
            "clarification_question": state.get("clarification_question", ""),
        },
        "itinerary_markdown": state.get("formatted_itinerary", ""),
        "itinerary_structured": state.get("arranged_itinerary", []),
        "map_data": map_data,
        "budget_breakdown": budget_breakdown,
        "weather": state.get("weather_info", {}),
        "hotels": state.get("hotels", []),
        "foods": state.get("foods", []),
        "poi_candidates": state.get("poi_candidates", []),
        "rag_context": state.get("rag_context", ""),
        "metadata": {
            "session_id": state.get("session_id", ""),
            "total_tokens": state.get("total_tokens", 0),
            "total_cost": round(state.get("total_cost", 0.0) or 0.0, 6),
            "nodes_executed": list(state.get("node_executed", []) or []),
            "errors": list(state.get("errors", []) or []),
        },
    }
    if share_payload:
        final["share_payload"] = share_payload
    return final


async def execute(state: AgentState) -> dict:
    updates: dict = {"node_executed": [NODE_NAME]}
    try:
        logger.info(
            f"[Node8] 直接组装最终输出（无 LLM 调用），"
            f"已执行节点数: {len(state.get('node_executed', []) or [])}"
        )
        final_output = _build_fallback_output(state)
        updates["final_output"] = final_output
        logger.info(
            f"[Node8] 最终输出完成: tokens={state.get('total_tokens', 0)}, "
            f"cost={state.get('total_cost', 0.0):.5f}元, "
            f"errors={len(state.get('errors', []) or [])}"
        )
    except Exception as e:
        err_msg = f"[Node8] 最终结果组装失败: {e}"
        logger.error(err_msg)
        try:
            updates["final_output"] = _build_fallback_output(state)
        except Exception:
            updates["final_output"] = {
                "error": str(err_msg),
                "metadata": {"errors": list(state.get("errors", []) or [])},
            }
        updates["errors"] = [err_msg]

    return updates
