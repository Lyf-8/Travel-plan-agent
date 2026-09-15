# 简历项目介绍：AI 旅行攻略生成系统

> 适用场景：校招 / 实习简历项目经历栏、面试自我介绍、作品集

---

## 项目经历（简历格式）

```
项目名称  ｜  AI 旅行攻略生成系统
时间      ｜  2026.6 - 2026.7
角色      ｜  独立开发（个人项目）
技术栈    ｜  Python / FastAPI / LangGraph / DashScope (千问) / ChromaDB / 高德地图 API / Vue3 / SQLite
```

### 项目描述

基于 **LangGraph 8 节点状态图**的智能旅行 Agent 系统，将"用户自然语言需求 → 多日程、带地图、含预算的完整行程"拆解为 8 个专用节点流水线执行。集成 LLM + RAG 混合检索 + 高德地图多维度 API，支持意图澄清条件短路、节点级 SSE 流式推送、用户反馈一键重生成与版本对比。

### 核心职责 / 亮点

- **LangGraph 状态图编排**：设计 8 节点有向状态图（意图理解 → 行程框架 → POI 检索 → 旅行上下文 → 资源预算 → 文案美化 → 地图分享 → 最终输出），在意图理解节点后加入**条件边**，信息不足时直接短路后续 7 节点；节点间通过 TypedDict + 自定义 reducer（列表追加 / 数值累加）合并状态，单节点异常由自身捕获写入 `errors`，流水线不中断。

- **多模型降级 + 上下文压缩**：LLM 工厂实现 `primary_only / primary_fallback / round_robin` 三种路由策略，DashScope 千问为主、OpenAI 为备，单 Provider 失败自动降级；针对长对话累积上下文问题，设计 TokenManager 将历史消息从 **30K tokens 压缩至 6K**（约 80% 压缩率），保留最近 5 条原文 + 更早消息 LLM 摘要。

- **RAG 混合检索架构**：Embedding 层优先本地 bge-small-zh-v1.5 模型（512 维），不可用时回退 OpenAI Embedding API；检索层采用"向量召回 Top-K → BM25 关键词重排"混合策略；缓存层使用 RAGCache（TTL 3600s）减少重复向量检索。

- **节点级 SSE 流式推送**：用 `graph.astream(stream_mode="values")` 驱动 LangGraph，对比 `node_executed` 新增项识别刚完成节点，实时推送 `node_start → node_progress → clarification? → done` 四类 SSE 事件；前端 Vue3 Pinia store 逐事件渲染流式气泡，后端在 yield done **之前完成数据库 commit**，防止客户端断开丢数据。

- **反馈驱动版本链**：用户提交反馈 → `feedback_service` 以 `graph.ainvoke` 重跑整张图（输入携带当前版本行程 + 修改意见） → 生成新版本 `parent_version` 指向上一版本；前端 VersionCompare 组件用 DiffHighlight 高亮新旧差异。

- **Node8 零 LLM 最终组装**：final_output 节点直接用 Python dict 组装前 7 节点产出，**不调用 LLM**，避免最终阶段大文本超时（>120s 问题）。

### 技术难点与解决方案

| 难点 | 解决方案 |
|---|---|
| HuggingFace Embedding 模型启动联网校验卡死 | 设置 `HF_HUB_OFFLINE=1`，本地模型已缓存，离线启动；配合 `TRANSFORMERS_OFFLINE=1` 防止 transformers 联网 |
| LangGraph 节点间状态合并语义 | 用 `TypedDict(total=False)` 定义 AgentState，`Annotated[list, merge_list]` 处理 node_executed/errors 追加，`Annotated[int, add_number]` 处理 total_tokens 累加 |
| 高德 QPS 超限导致 POI 检索失败 | 节点自身 try/except 兜底，写 errors 后返回空结果，下游节点降级空跑，流水线不中断 |
| Vite 代理 SSE 缓冲导致流式不生效 | Vite dev server 默认缓冲 text/event-stream 响应，需配置 proxy 关闭 buffering |
| Windows 上 uvicorn IPv6 解析问题 | proxy target 必须写 `http://127.0.0.1:8000` 而非 `localhost`，避免 Windows 解析 IPv6 ::1 连接失败 |
| AMap JS API Map 构造器 gray 底图 | 移除 `features` 等无效选项，AMap JS API 2.0+ 不再支持 |

---

## 面试快答版（1 分钟 / 3 分钟）

### 1 分钟版

> 我做了一个 AI 旅行攻略生成系统，基于 LangGraph 的 8 节点状态图，把用户说的"我想放假去广州玩 3 天预算 5000"这样一句话，变成带地图标记、预算明细、天气信息的完整行程。核心亮点是：意图理解后有条件边可以直接问用户澄清，节点级 SSE 实时推送进度，还有 RAG 缓存+混合检索补充景点背景，以及 30K→6K 的上下文压缩解决长对话累积问题。用户不满意可以提交反馈一键重生成，版本链自动对比差异。

### 3 分钟版

> 这个项目的核心架构是 LangGraph 状态图，我把行程生成拆成 8 个专用节点：意图理解、行程框架、POI 检索、旅行上下文（天气+路线）、资源预算（酒店+餐饮）、文案美化、地图分享、最终输出。**第一个亮点**是意图理解节点后面加了条件边——如果用户说的话信息不够，比如只说了"我想去旅游"没说去哪几天，就直接短路结束，把澄清问题推给前端问；信息够才走后面的 7 个节点。**第二个亮点**是 SSE 流式，LangGraph 的 astream 按 super-step 吐出完整 state 快照，我对比 node_executed 的新增项就能识别刚完成哪个节点，实时推 node_start 和 node_progress 事件给前端，前端边生成边渲染。**第三个亮点**是 LLM 主备降级，DashScope 千问是主模型，OpenAI 是备，有 primary_fallback 和 round_robin 两种策略，一个 Provider 挂了自动切下一个。**第四个亮点**是 30K→6K 的上下文压缩，用 LLM 把老消息摘要掉只留最近 5 条原文，解决多轮对话累积上下文太大的问题。还有 RAG 这块，向量召回加 BM25 重排，缓存优先外部搜索兜底，以及反馈重生成的版本链对比。整个后端用 FastAPI + SQLite 全异步，前端 Vue3 + Pinia + Element Plus。

---

## GitHub 仓库

```
https://github.com/Lyf-8/Travel-plan-agent
```

---

## 项目结构速览

```
Travel-plan-agent/
├── backend/                    # FastAPI + LangGraph 后端
│   ├── src/
│   │   ├── agents/
│   │   │   ├── graph.py        # LangGraph StateGraph 定义（8节点 + 条件边）
│   │   │   ├── state.py        # AgentState TypedDict + reducer
│   │   │   ├── nodes/          # n01~n08 节点（返回增量 dict）
│   │   │   └── prompts/        # Node Prompt 模板
│   │   ├── services/           # itinerary_service（SSE 桥接）、feedback_service
│   │   ├── llm/                # factory.py（多模型降级）、token_manager（上下文压缩）
│   │   ├── rag/                # retriever（混合检索）、vector_store、cache
│   │   ├── tools/              # 高德 POI/天气/路线/酒店/餐饮、维基百科
│   │   └── core/               # config（pydantic-settings + .env）、logger、exceptions
│   ├── requirements.txt
│   ├── .env.example            # 密钥占位符（真实 .env 被 .gitignore 排除）
│   └── scripts/start_backend.bat
├── frontend/                   # Vue3 + Vite + Pinia + Element Plus
│   ├── src/
│   │   ├── views/              # HomeView / ItineraryCreate / ItineraryDetail / ShareView / VersionCompare
│   │   ├── stores/             # chat（SSE 状态）、itinerary
│   │   ├── components/         # AmapContainer / BudgetProgress / DiffHighlight / FeedbackEditor
│   │   └── api/                # chat.js（SSE 解析）、request.js、itinerary.js
│   └── .env.example
├── docs/                       # architecture.md + agent_flow.md + resume_project.md
└── .gitignore                  # 排除 .env / .venv / node_modules / *.db / __pycache__
```

---

## 关键指标（可根据实际运行数据替换）

| 指标 | 值 | 说明 |
|---|---|---|
| 节点数 | 8 | LangGraph 状态图节点 |
| 条件边 | 1 | 意图理解后澄清短路 |
| LLM 压缩率 | ~80% | 30K tokens → 6K tokens |
| 向量库 | ChromaDB / Qdrant | 可配置切换 |
| Embedding 维度 | 512 | bge-small-zh-v1.5 |
| SSE 事件类型 | 4 | node_start / node_progress / clarification / done |
| 数据库 | SQLite (aiosqlite) | 全异步 |
| 表数量 | 8 | users / sessions / messages / itinerary_versions / itinerary_items / feedback / short_links / rag_documents |
