"""Node1：意图理解节点

合并说明：保留原节点逻辑，直接从用户输入中解析旅行意图（目的地、天数、预算、偏好等）。
对应旧节点：n01_intent_understanding

LangGraph 约定：节点不直接修改 state，而是返回「增量 dict」，
由 state.py 中声明的 reducer 合并进全局状态。
"""
from __future__ import annotations

from loguru import logger

from ...llm.factory import llm_call
from ..prompts.node_prompts import INTENT_UNDERSTANDING_PROMPT
from ..state import AgentState
from ...utils.helpers import extract_json_from_text, safe_float, safe_int


NODE_NAME = "n01_intent_understanding"


async def execute(state: AgentState) -> dict:
    # 本节点对全局状态的增量更新
    updates: dict = {"node_executed": [NODE_NAME]}
    try:
        user_input = state.get("user_input", "")
        logger.info(f"[Node1] 开始意图理解，输入长度: {len(user_input)}")

        if not user_input.strip():
            raise ValueError("用户输入为空")

        messages = [
            {"role": "system", "content": INTENT_UNDERSTANDING_PROMPT},
            {"role": "user", "content": user_input},
        ]

        resp = await llm_call(messages)
        updates["total_tokens"] = resp.usage.total_tokens
        updates["total_cost"] = resp.usage.cost_cny

        result = extract_json_from_text(resp.content)
        if not result:
            raise ValueError(f"LLM 返回无法解析为 JSON: {resp.content[:200]}")

        destination = result.get("destination", "") or ""
        travel_days = safe_int(result.get("travel_days"), 0)
        budget_min = safe_float(result.get("budget_min"), 0.0)
        budget_max = safe_float(result.get("budget_max"), 0.0)
        preferences = result.get("preferences", {}) or {}
        travel_dates = result.get("travel_dates", []) or []
        intent_confidence = safe_float(result.get("intent_confidence"), 0.0)
        needs_clarification = bool(result.get("needs_clarification", False))
        clarification_question = result.get("clarification_question", "") or ""

        # ---- 代码层兜底：修正 LLM 可能的不合理输出 ----
        # 天数为 0 时设默认 3 天
        if travel_days <= 0 and destination:
            travel_days = 3
            logger.warning(f"[Node1] travel_days=0 兜底为 3")
        # 预算上限为 0 时设默认 5000
        if budget_max <= 0 and destination:
            budget_max = 5000.0
            logger.warning(f"[Node1] budget_max=0 兜底为 5000")
        # 目的地存在且天数合理时，自动关闭澄清标志
        if destination and travel_days > 0:
            needs_clarification = False
            clarification_question = ""
        # 置信度低于 0.6 时强制澄清（除非已有完整信息）
        if intent_confidence < 0.6 and destination:
            needs_clarification = True
            clarification_question = (
                f"关于{destination}的旅行，能否告诉我具体天数和预算？"
            )

        updates.update(
            destination=destination,
            travel_days=travel_days,
            budget_min=budget_min,
            budget_max=budget_max,
            preferences=preferences,
            travel_dates=travel_dates,
            intent_confidence=intent_confidence,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
        )

        logger.info(
            f"[Node1] 意图理解完成: destination={destination}, "
            f"days={travel_days}, budget=[{budget_min},{budget_max}], "
            f"confidence={intent_confidence:.2f}"
        )

    except Exception as e:
        err_msg = f"[Node1] 意图理解失败: {e}"
        logger.error(err_msg)
        updates["errors"] = [err_msg]

    return updates
