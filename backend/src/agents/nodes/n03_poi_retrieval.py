"""Node3：POI 检索节点

合并说明：保留旧节点逻辑，关键词生成直接参考目的地+偏好（不依赖 daily_plan_outline）；
对多个关键词使用 asyncio.gather 并行调用检索工具，单个关键词内部工具串行执行。
对应旧节点：n03_poi_retrieval

LangGraph 约定：返回增量 dict，不直接修改 state。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from loguru import logger

from ...llm.factory import llm_call
from ..prompts.node_prompts import POI_RETRIEVAL_PROMPT
from ...rag.retriever import get_retriever
from ..state import AgentState
from ...tools.amap_poi import get_poi_search
from ...utils.helpers import extract_json_from_text


NODE_NAME = "n03_poi_retrieval"


async def _search_single_keyword(
    keyword: str,
    destination: str,
    day: int,
    slot: str,
) -> tuple[list[dict], str]:
    poi_search = get_poi_search()
    retriever = get_retriever()

    poi_items = await poi_search.keywords_search(
        keywords=keyword,
        city=destination,
        citylimit=True,
        offset=10,
    )
    poi_dicts = []
    for p in poi_items:
        d = asdict(p)
        d.pop("raw", None)
        d["day"] = day
        d["slot"] = slot
        d["keyword_source"] = keyword
        poi_dicts.append(d)

    rag_result = await retriever.retrieve(
        query=f"{destination} {keyword}",
        top_k=3,
        city=destination,
    )
    rag_text = rag_result.context_text

    return poi_dicts, rag_text


async def execute(state: AgentState) -> dict:
    updates: dict = {"node_executed": [NODE_NAME]}
    try:
        destination = state.get("destination", "")
        logger.info(f"[Node3] 开始 POI 检索，目的地: {destination}")

        if not destination:
            raise ValueError("destination 为空")

        preferences = state.get("preferences", {}) or {}
        input_data = {
            "destination": destination,
            "travel_days": state.get("travel_days", 0),
            "preferences": preferences,
            "interests": preferences.get("interests", []),
        }
        user_content = json.dumps(input_data, ensure_ascii=False)

        messages = [
            {"role": "system", "content": POI_RETRIEVAL_PROMPT},
            {"role": "user", "content": user_content},
        ]

        resp = await llm_call(messages)
        updates["total_tokens"] = resp.usage.total_tokens
        updates["total_cost"] = resp.usage.cost_cny

        result = extract_json_from_text(resp.content)
        if not result:
            raise ValueError(f"LLM 返回无法解析为 JSON: {resp.content[:200]}")

        poi_keywords = result.get("poi_keywords", []) or []
        if not poi_keywords:
            raise ValueError("poi_keywords 为空")

        logger.info(f"[Node3] 生成 {len(poi_keywords)} 组关键词，开始并行检索")

        tasks = []
        for day_item in poi_keywords:
            day = day_item.get("day", 1)
            slots = day_item.get("slots", []) or []
            for slot_item in slots:
                slot = slot_item.get("slot", "")
                keyword = slot_item.get("keyword", "")
                if keyword:
                    tasks.append(
                        _search_single_keyword(keyword, destination, day, slot)
                    )

        results = await asyncio.gather(*tasks, return_exceptions=False)

        all_poi: list[dict] = []
        rag_parts: list[str] = []
        seen_ids = set()
        for poi_dicts, rag_text in results:
            for pd in poi_dicts:
                pid = pd.get("id")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    all_poi.append(pd)
            if rag_text:
                rag_parts.append(rag_text)

        rag_context = "\n\n---\n\n".join(rag_parts)
        updates["poi_candidates"] = all_poi
        updates["rag_context"] = rag_context
        logger.info(
            f"[Node3] POI 检索完成: 候选 {len(all_poi)} 个, "
            f"RAG 上下文 {len(rag_context)} 字符"
        )

    except Exception as e:
        err_msg = f"[Node3] POI 检索失败: {e}"
        logger.error(err_msg)
        updates["errors"] = [err_msg]

    return updates
