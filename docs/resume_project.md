# 项目经验 —— AI 旅行攻略生成 Agent

## AI 旅行攻略生成 Agent

**2026.7**　　　　　　　　　　　　　　Agent 应用开发

开发技术 ：Python / LangGraph / FastAPI / DashScope（千问）/ ChromaDB / 高德地图 API / Vue3 / python-dotenv / SQLite

项目描述 ：
- 基于 LangGraph StateGraph 的智能旅行 Agent，将「用户自然语言需求 → 带地图、含预算、有天气的完整多日程行程」串联为 8 节点流水线；
- 融合 LLM + RAG 混合检索（向量召回 + BM25 重排 + 缓存）+ 高德 POI/路线/天气/酒店/餐饮 API，内置意图理解后条件边——信息不足直接短路后续节点并向用户澄清；
- 支持用户提交反馈一键重生成行程，自动对比新旧版本差异并高亮展示，Node8 最终输出零 LLM 调用避免大文本超时。

责任描述 ：
- 负责 LangGraph 8 节点状态图架构设计：节点间通过 TypedDict + 自定义 reducer（列表追加 / 数值累加）合并状态，意图理解节点后加条件边实现澄清短路，单节点异常自身捕获写入 errors 不阻断流水线；
- 搭建 LLM 主备降级 + 上下文压缩体系：LLM 工厂实现 primary_fallback / round_robin 三种路由策略，DashScope 千问为主、OpenAI 为备；TokenManager 将 30K tokens 长对话压缩至 6K（80% 压缩率），保留最近 5 条原文 + 更早消息 LLM 摘要；
- 设计节点级 SSE 流式推送：用 graph.astream(stream_mode="values") 驱动 LangGraph，对比 node_executed 新增项识别刚完成节点，实时推送 node_start → node_progress → clarification? → done 事件，前端 Pinia store 逐事件渲染流式气泡，后端数据库 commit 在 yield done 之前完成防止客户端断开丢数据；
- 完成安全改造：密钥从代码剥离到 .env（python-dotenv + pydantic-settings 加载，.gitignore 排除），扫描全项目无 sk- 密钥泄漏；Vite 代理关闭 text/event-stream 缓冲解决 SSE 流式不生效问题。
