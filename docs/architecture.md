# 系统架构设计

AI 智能旅行规划系统：前端 Vue3 SPA + 后端 FastAPI，核心行程生成由 **LangGraph 状态图**编排，
融合 LLM、RAG 知识库与高德地图工具。

## 1. 分层架构

```
┌──────────────────────────────────────────────────────────┐
│ 前端 frontend/（Vue3 + Vite + Pinia + Element Plus）       │
│   views / components / stores / api                       │
│   SSE 消费：node_start / node_progress / clarification    │
└───────────────┬──────────────────────────────────────────┘
                │ /api（Vite 代理 → 127.0.0.1:8000，SSE 关闭缓冲）
┌───────────────▼──────────────────────────────────────────┐
│ API 层 backend/src/api/                                    │
│   routers: chat / stream / itinerary / share / health     │
│   schemas + dependencies（统一响应体 / 异常处理）           │
├──────────────────────────────────────────────────────────┤
│ 业务服务层 services/                                       │
│   itinerary_service（图驱动 + SSE 桥接 + 落库）             │
│   feedback_service（反馈 → 图重生成新版本）                  │
│   share_service / version_diff                            │
├──────────────────────────────────────────────────────────┤
│ Agent 编排层 agents/（LangGraph StateGraph）               │
│   graph.py   8 节点状态图 + 澄清条件边                       │
│   state.py   TypedDict State + reducer（列表追加/数值累加） │
│   nodes/     n01~n08 节点（返回状态增量，不就地修改）        │
├───────────────┬───────────────┬──────────────────────────┤
│ LLM 层 llm/   │ RAG 层 rag/   │ 工具层 tools/             │
│ OpenAI 协议    │ ChromaDB      │ 高德 POI/天气/路线/        │
│ 千问 + 备援    │ bge-small-zh  │ 酒店/餐饮、维基百科        │
│ 工厂 + 重试    │ 混合检索+缓存  │                           │
├───────────────┴───────────────┴──────────────────────────┤
│ 数据层 db/：SQLAlchemy(async) + aiosqlite（8 张表）          │
│   会话/消息/行程版本/行程项/反馈/短链/RAG 文档               │
└──────────────────────────────────────────────────────────┘
```

## 2. 核心请求链路（流式生成）

```
用户提交需求
  → POST /api/chat/sessions/{id}/messages/stream（SSE）
  → itinerary_service.send_message_stream
      1. 用户消息落库
      2. 构建图输入 dict（user_input / session 上下文）
      3. graph.astream(stream_mode="values") 驱动 LangGraph
         ├─ 各节点调 LLM（llm/factory 主备降级 + tenacity 重试）
         ├─ Node3 并行：高德 POI × N + RAG 检索（asyncio.gather）
         ├─ Node4 并行：天气 API + 路线 API
         ├─ Node5 并行：酒店 + 餐饮
         └─ Node1 后条件边：needs_clarification → END 短路
      4. 每个节点完成 → SSE node_start/node_progress（中文 detail 实时推送）
      5. 行程版本 + 明细落库、助手消息落库、commit
      6. clarification? → done
  → 前端流式气泡逐行渲染步骤，done 时定稿并加载行程
```

关键时序约束：**先 commit 再 yield done**，保证客户端中途断开不丢数据。

## 3. 技术选型

| 层 | 技术 | 说明 |
|---|---|---|
| Web | FastAPI + uvicorn | async 原生，StreamingResponse 承载 SSE |
| Agent | **LangGraph 1.x** | StateGraph、条件边、astream 节点级流 |
| LLM | openai SDK + DashScope | OpenAI 兼容协议，多 Provider 工厂降级 |
| RAG | ChromaDB + sentence-transformers | bge-small-zh-v1.5 本地向量，关键词重排 |
| 工具 | 高德 Web 服务 / 维基百科 | httpx 异步调用 |
| DB | SQLAlchemy 2 + aiosqlite | 全异步，单文件 SQLite |
| 前端 | Vue3 / Pinia / Vue Router / Element Plus | Vite 开发代理 |

## 4. 状态与持久化边界

- **LangGraph State**：单次生成的进程内工作记忆（节点间传递），不做 checkpoint 持久化
- **SQLite**：业务事实数据（会话、消息、行程版本链、反馈、短链），版本链支持对比与回滚
- 两者刻意保持单一事实源：生成结果以版本快照形式落库，图本身无状态，可随时基于反馈整图重跑

## 5. 本地运行

```powershell
# 后端（HF_HUB_OFFLINE 防止 Embedding 模型启动时联网校验卡死）
$env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"
cd backend; ..\.venv\Scripts\python.exe -m uvicorn src.main:app --reload --port 8000

# 前端
cd frontend; npm run dev   # http://localhost:5173
```

相关文档：[Agent 流程设计](./agent_flow.md)｜[API 设计](./api_design.md)
