"""Agent 流水线共享状态（LangGraph State Schema）

定义贯穿 8 节点流水线的统一状态 AgentState（TypedDict）。
每个节点读取上游字段、以「返回增量 dict」的方式写入自身输出，
由 LangGraph 按字段上声明的 reducer 合并进全局状态：

    - 普通字段：默认「覆盖」语义，节点返回的新值替换旧值
    - 累积字段（Annotated + reducer）：
        * node_executed / errors —— 列表追加
        * total_tokens / total_cost —— 数值累加

字段按节点输出分组：
    - 输入：user_input / session_id / feedback
    - A1 意图理解：destination / travel_days / budget / preferences ...
    - A2 行程框架设计：arranged_itinerary 字段
    - A3 POI 检索：poi_candidates / rag_context
    - A4 出行环境整合：routes + weather_info
    - A5 资源预算规划：hotels + foods + budget_breakdown
    - A6 文案美化生成：formatted_itinerary
    - A7 地图与分享数据：map_data + share_payload
    - A8 最终结果输出：final_output
    - 元数据：errors / node_executed / total_tokens / total_cost
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict


# ============================================================
# 自定义 reducer（LangGraph 用它合并节点返回的增量到全局状态）
# 均做 None 安全处理：未在初始输入中出现的键首帧为 None
# ============================================================
def merge_list(left: list | None, right: list | None) -> list:
    """列表追加 reducer：把节点新返回的列表追加到已有列表后"""
    return list(left or []) + list(right or [])


def add_number(left: int | float | None, right: int | float | None) -> int | float:
    """数值累加 reducer：用于 token / 成本跨节点累计"""
    return (left or 0) + (right or 0)


class AgentState(TypedDict, total=False):
    """多 Agent 编排流水线的共享状态

    total=False：所有键均可缺省（LangGraph 中未提供的键首帧为 None，
    节点统一用 state.get(key, default) 读取）。
    """

    # ---------- 输入 ----------
    user_input: str                                              # 用户自然语言请求
    session_id: str                                              # 会话 ID
    feedback: str                                                # 反馈重生成时的上下文 JSON 字符串

    # ---------- A1：意图理解输出 ----------
    destination: str                                             # 目的地城市
    travel_days: int                                             # 旅行天数
    budget_min: float                                            # 预算下限（元）
    budget_max: float                                            # 预算上限（元）
    preferences: dict[str, Any]                                  # {"travel_style":...,"interests":[...]}
    travel_dates: list[str]                                      # ["2026-08-20", ...]
    intent_confidence: float                                     # 意图识别置信度
    needs_clarification: bool                                    # 是否需要澄清
    clarification_question: str                                  # 澄清问题

    # ---------- A3：POI 检索输出 ----------
    poi_candidates: list[dict]                                   # POI 字典列表
    rag_context: str                                             # RAG 检索到的上下文文本

    # ---------- A4：出行环境整合输出（路线 + 天气）----------
    routes: list[dict]                                           # POI 之间的路线分段
    weather_info: dict[str, Any]                                 # {"live":..., "forecasts":...}

    # ---------- A5：资源预算规划输出（酒店餐饮 + 预算）----------
    hotels: list[dict]
    foods: list[dict]
    budget_breakdown: dict[str, Any]                             # transport/food/hotel/tickets/other/total

    # ---------- A2：行程框架设计输出 ----------
    arranged_itinerary: list[dict]                               # 最终逐日行程

    # ---------- A6：文案美化生成输出 ----------
    formatted_itinerary: str                                     # Markdown 格式的行程文本

    # ---------- A7：地图与分享数据输出 ----------
    map_data: dict[str, Any]                                     # POI 坐标 + 路线，供前端地图渲染
    share_payload: dict[str, Any]                                # 分享标题摘要 + 短链接信息

    # ---------- A8：最终结果输出 ----------
    final_output: dict[str, Any]                                 # 完整 JSON，供前端使用

    # ---------- 元数据（跨节点累积，走自定义 reducer）----------
    errors: Annotated[list[str], merge_list]                     # 各节点累积的错误信息
    node_executed: Annotated[list[str], merge_list]              # 已执行的节点名
    total_tokens: Annotated[int, add_number]                     # 累计 token 消耗
    total_cost: Annotated[float, add_number]                     # 累计成本（元）
