# Agent 流程设计（LangGraph）

> 代码位置：`backend/src/agents/`
> 编排框架：**LangGraph 1.x（StateGraph）**；LLM 调用不依赖 LangChain，节点内直接用 OpenAI SDK 协议调用千问。

## 1. 状态图总览

```
START
  → intent_understanding        意图理解（LLM 解析目的地/天数/预算/偏好）
      ├── needs_clarification ──→ END                【条件边：信息不足，短路结束】
      └── continue ──→ itinerary_framework           行程框架（逐日时间轴）
                        → poi_retrieval               POI 检索（高德 API + RAG 并行）
                        → travel_context              天气 + 路线（asyncio.gather 并发）
                        → resource_budget             酒店/餐饮 + 预算核算
                        → content_beautify            Markdown 文案美化
                        → map_and_share               地图标记 + 分享快照
                        → final_output                纯数据组装（不调 LLM）
                        → END
```

图定义见 [graph.py](../backend/src/agents/graph.py)，可直接用 `get_graph().get_graph().draw_mermaid()` 导出 Mermaid 图。

## 2. 状态 Schema（AgentState）

[state.py](../backend/src/agents/state.py) 使用 `TypedDict(total=False)` 定义全局状态，字段合并语义分两类：

| 合并方式 | 字段 | 说明 |
|---|---|---|
| 覆盖（默认） | `destination`、`arranged_itinerary`、`poi_candidates`、`map_data`、`final_output` 等 | 节点返回的新值替换旧值 |
| 自定义 reducer | `node_executed: Annotated[list, merge_list]` | 节点名列表追加 |
| | `errors: Annotated[list, merge_list]` | 错误信息列表追加 |
| | `total_tokens / total_cost: Annotated[number, add_number]` | token、成本跨节点累加 |

reducer 均为 None 安全：未在输入中提供的键首帧为 `None`。

## 3. 节点契约

8 个节点位于 `agents/nodes/n01_*.py ~ n08_*.py`，统一签名：

```python
async def execute(state: AgentState) -> dict:
    updates: dict = {"node_executed": [NODE_NAME]}
    try:
        # 读：state.get("destination", "")
        # 业务逻辑（LLM / 工具 / 纯计算）
        updates["arranged_itinerary"] = arranged
        updates["total_tokens"] = resp.usage.total_tokens
    except Exception as e:
        updates["errors"] = [f"[NodeX] xxx 失败: {e}"]
    return updates  # 只返回增量，由 reducer 合并
```

要点：

- 节点**不直接修改 state**，只返回增量 dict（LangGraph 推荐的不可变更新模式）
- 单节点异常被自身捕获并写入 `errors`，**不阻断流水线**，下游节点可降级空跑
- Node8（final_output）只做数据组装，不调用 LLM，避免最终阶段大文本超时

## 4. 条件边：澄清分流

```python
def route_after_intent(state) -> str:
    return "needs_clarification" if state.get("needs_clarification") else "continue"

graph.add_conditional_edges(
    "intent_understanding", route_after_intent,
    {"needs_clarification": END, "continue": "itinerary_framework"},
)
```

意图理解置信度不足或关键信息缺失时，图在 Node1 后直接结束，后续 7 个节点全部短路。
Service 层检测到该路径后：

1. 不创建行程版本、不落行程明细
2. SSE 先推 `clarification` 事件（澄清问题），再推 `done`（`needs_clarification=true`）

## 5. SSE 流式桥接

[itinerary_service.py](../backend/src/services/itinerary_service.py) 用 `graph.astream(inputs, stream_mode="values")` 驱动图：

- `values` 模式：每个节点（super-step）完成后吐出**完整 state 快照**
- service 对比 `state["node_executed"]` 的新增项识别刚完成的节点（模块名 → 图节点名通过 `MODULE_TO_NODE` 反查）
- 每个节点产出一对事件：完成前由上一帧补发 `node_start`，完成时推 `node_progress`（含进度百分比、增量 token、中文阶段成果 `detail`）
- 最终推 `clarification?` + `done`；**数据库 commit 在 yield done 之前完成**，客户端断开不丢数据

事件序列：`node_start → node_progress → node_start → … → done`

## 6. 反馈重生成

[feedback_service.py](../backend/src/services/feedback_service.py) 通过 `get_graph().ainvoke(inputs)` 一次性执行整张图：

- 输入额外携带 `feedback` 字段（当前版本行程 + 修改意见的 JSON 上下文），Node2 生成新框架时读取
- 结果创建新版本，`parent_version` 指向被反馈的版本，形成版本链

## 7. 失败与降级策略

| 场景 | 行为 |
|---|---|
| LLM Provider 全部失败 | 节点写 `errors`，流水线继续（下游产出为空），最终回复展示错误摘要 |
| LLM JSON 解析失败 | Node4/Node5/Node7 有 fallback：直接使用高德 API 原始数据 |
| 高德 QPS 超限 | 工具层抛错 → 节点写 errors，不影响其他节点 |
| 单节点异常 | try/except 兜底，图不会中断（无重试循环边） |
