"""LangGraph 工作流定义

8 个节点组成的有向状态图：

    START
      → intent_understanding          （意图理解）
          ├─ needs_clarification=True ──→ END          【条件边：需要澄清时短路结束】
          └─ continue → itinerary_framework            （行程框架）
                          → poi_retrieval               （POI 检索）
                          → travel_context              （天气 + 路线）
                          → resource_budget             （酒店餐饮 + 预算）
                          → content_beautify            （Markdown 文案）
                          → map_and_share               （地图 + 分享数据）
                          → final_output                （最终组装）
                          → END

要点：
    - State Schema 见 state.py 的 AgentState（TypedDict + Annotated reducer）
    - 节点函数签名：async def execute(state: AgentState) -> dict（返回状态增量）
    - 节点自身捕获异常并写入 errors（merge_list reducer 追加），图不会因单节点失败而中断
"""
from __future__ import annotations

from functools import lru_cache
from typing import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from .nodes import (
    n01_intent_understanding,
    n02_itinerary_framework,
    n03_poi_retrieval,
    n04_travel_context,
    n05_resource_budget,
    n06_content_beautify,
    n07_map_and_share,
    n08_final_output,
)
from .state import AgentState


# 节点执行函数类型：接收完整 state，返回状态增量 dict
NodeExecutor = Callable[[AgentState], Awaitable[dict]]

# (图节点名, 模块节点名, 执行函数)
# 图节点名对前端（SSE 事件）稳定；模块名写入 state.node_executed 便于排障
NODE_SPECS: list[tuple[str, str, NodeExecutor]] = [
    ("intent_understanding", n01_intent_understanding.NODE_NAME, n01_intent_understanding.execute),
    ("itinerary_framework", n02_itinerary_framework.NODE_NAME, n02_itinerary_framework.execute),
    ("poi_retrieval", n03_poi_retrieval.NODE_NAME, n03_poi_retrieval.execute),
    ("travel_context", n04_travel_context.NODE_NAME, n04_travel_context.execute),
    ("resource_budget", n05_resource_budget.NODE_NAME, n05_resource_budget.execute),
    ("content_beautify", n06_content_beautify.NODE_NAME, n06_content_beautify.execute),
    ("map_and_share", n07_map_and_share.NODE_NAME, n07_map_and_share.execute),
    ("final_output", n08_final_output.NODE_NAME, n08_final_output.execute),
]

# 图节点名（顺序即流水线顺序，也是 SSE 进度索引）
NODE_NAMES: list[str] = [spec[0] for spec in NODE_SPECS]

# 模块节点名 → 图节点名 反查表
MODULE_TO_NODE: dict[str, str] = {mod: graph_name for graph_name, mod, _ in NODE_SPECS}

# 条件边路由结果
ROUTE_CLARIFY = "needs_clarification"
ROUTE_CONTINUE = "continue"


def route_after_intent(state: AgentState) -> str:
    """意图理解之后的条件路由

    - needs_clarification=True：直接结束图（后续 7 个节点短路跳过）
    - 否则：进入行程框架设计
    """
    if state.get("needs_clarification"):
        return ROUTE_CLARIFY
    return ROUTE_CONTINUE


def build_graph():
    """构建并编译行程规划状态图"""
    graph = StateGraph(AgentState)

    # 1. 注册节点
    for graph_name, _mod_name, executor in NODE_SPECS:
        graph.add_node(graph_name, executor)

    # 2. 入口边
    graph.add_edge(START, "intent_understanding")

    # 3. 意图理解 → 条件边（澄清短路 / 继续主流程）
    graph.add_conditional_edges(
        "intent_understanding",
        route_after_intent,
        {
            ROUTE_CLARIFY: END,
            ROUTE_CONTINUE: "itinerary_framework",
        },
    )

    # 4. 主流程线性边（第 2 个节点 → … → 最后一个节点）
    for i in range(1, len(NODE_NAMES) - 1):
        graph.add_edge(NODE_NAMES[i], NODE_NAMES[i + 1])

    # 5. 收口
    graph.add_edge(NODE_NAMES[-1], END)

    return graph.compile()


@lru_cache(maxsize=1)
def get_graph():
    """获取编译后的图单例（可直接调用 ainvoke / astream）"""
    return build_graph()
