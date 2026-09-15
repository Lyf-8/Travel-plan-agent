"""行程服务 - 对话编排 + 行程生成 + 版本管理

职责：
    - 创建 / 列举会话
    - 接收用户消息 → 调用 Agent 编排 → 落库行程版本与明细 → 返回回复
    - 读取当前 / 历史行程版本

说明：
    - 所有 DB 读写都通过 Repositories 模式进行
    - 每个方法独立开 / 关 Session，异常时回滚
"""
from __future__ import annotations

import time
import uuid
from typing import Any, AsyncGenerator, Optional

from loguru import logger

from ..agents.graph import MODULE_TO_NODE, NODE_NAMES, get_graph
from ..core.exceptions import LLMCallError, ResourceNotFound, ValidationError
from ..db.connection import get_session_factory
from ..db.repositories import Repositories
from ..llm.token_manager import approx_tokens


class ItineraryService:
    """行程编排服务：连接对话层与 Agent 编排层"""

    # 节点中文名 → 执行中文案（node_start 时推给前端实时显示）
    NODE_RUNNING_LABELS: dict[str, str] = {
        "intent_understanding": "正在理解你的旅行需求…",
        "itinerary_framework": "正在设计逐日行程框架…",
        "poi_retrieval": "正在检索沿途景点与 POI…",
        "travel_context": "正在查询天气与路线…",
        "resource_budget": "正在规划酒店餐饮并核算预算…",
        "content_beautify": "正在生成行程文案…",
        "map_and_share": "正在组装地图标记与路线…",
        "final_output": "正在汇总最终行程…",
    }

    # ItineraryItem 可入库字段（排除 id / version_id / created_at 等自动字段）
    _ITEM_FIELDS: tuple[str, ...] = (
        "day", "order_in_day", "item_type", "title", "description",
        "start_time", "end_time", "duration_min",
        "location_name", "location_address", "longitude", "latitude", "amap_poi_id",
        "transport_from_prev", "travel_time_min", "travel_distance_m",
        "cost_ticket", "cost_food", "cost_hotel", "cost_transport", "cost_other",
        "tags", "image_url", "rag_refs", "extra",
    )

    # ============================================================
    # 会话管理
    # ============================================================
    async def create_session(
        self,
        user_id: Optional[int] = None,
        destination: Optional[str] = None,
        travel_days: Optional[int] = None,
        budget_min: Optional[float] = None,
        budget_max: Optional[float] = None,
        preferences: Optional[dict] = None,
        title: Optional[str] = None,
        username: str = "guest",
    ) -> dict:
        """创建新会话，返回 session dict"""
        # 参数校验
        if travel_days is not None and travel_days <= 0:
            raise ValidationError("travel_days 必须大于 0")
        if (
            budget_min is not None
            and budget_max is not None
            and budget_min > budget_max
        ):
            raise ValidationError("budget_min 不能大于 budget_max")

        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)
            # 1. 若未指定 user_id，则按 username 获取 / 创建用户
            if user_id is None:
                user = await repos.users.get_or_create(username=username)
                user_id = user.id
                logger.info(f"获取/创建用户: username={username}, user_id={user_id}")

            # 2. 生成会话 UUID 并创建 ChatSession
            session_id = uuid.uuid4().hex
            session_title = title or self._build_title(destination, travel_days)
            session = await repos.sessions.create(
                session_id=session_id,
                user_id=user_id,
                title=session_title,
                destination=destination,
                travel_days=travel_days,
                budget_min=budget_min,
                budget_max=budget_max,
                preferences=preferences or {},
                status="active",
            )
            await repos.commit()
            logger.info(
                f"创建会话成功: session_id={session_id}, "
                f"destination={destination}, days={travel_days}"
            )
            return {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "title": session.title,
                "destination": session.destination,
                "travel_days": session.travel_days,
                "budget_min": session.budget_min,
                "budget_max": session.budget_max,
                "preferences": session.preferences,
                "status": session.status,
                "created_at": session.created_at.isoformat()
                if session.created_at
                else None,
            }
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    async def list_sessions(
        self, user_id: Optional[int] = None, limit: int = 50
    ) -> list[dict]:
        """列出会话（user_id 为空时列出全部）"""
        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)
            if user_id is None:
                sessions = await repos.sessions.list_all(limit=limit)
            else:
                sessions = await repos.sessions.list_by_user(user_id, limit=limit)
            return [self._session_to_dict(s) for s in sessions]
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    # ============================================================
    # 对话 + 行程生成
    # ============================================================
    async def send_message_stream(
        self, session_id: str, message: str
    ) -> AsyncGenerator[dict, None]:
        """流式发消息：逐节点 yield 进度事件，最后 yield done 并落库"""
        if not message or not message.strip():
            raise ValidationError("消息内容不能为空")

        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)

            # 1. 获取会话
            session = await repos.sessions.get_by_session_id(session_id)
            if session is None:
                raise ResourceNotFound(f"会话不存在: {session_id}")

            # 2. 保存用户消息
            tokens_in = approx_tokens(message)
            await repos.messages.append_message(
                session_id=session_id,
                role="user",
                content=message,
                tokens_in=tokens_in,
            )

            # 3. 构建 LangGraph 图输入
            graph = get_graph()
            total_nodes = len(NODE_NAMES)
            graph_inputs = {
                "user_input": message,
                "session_id": session_id,
                "destination": session.destination,
                "travel_days": session.travel_days,
                "budget_min": session.budget_min,
                "budget_max": session.budget_max,
                "preferences": session.preferences or {},
            }

            # 发出 node_start：第一个节点
            first_name = NODE_NAMES[0]
            yield {
                "event": "node_start",
                "data": {
                    "node": first_name,
                    "index": 0,
                    "total": total_nodes,
                    "detail": self.NODE_RUNNING_LABELS.get(first_name, "处理中…"),
                },
            }

            # 4. 驱动状态图，每完成一个节点 yield 一次 node_progress
            # values 模式：每个 super-step 后吐出「完整 state」快照
            start_ts = time.time()

            logger.info(
                f"[LangGraph] 流水线启动(流式): session={session_id} "
                f"input={message[:50]}..."
            )

            state: dict = {}
            seen_executed = 0          # 已消费过的 node_executed 数量
            cumulative_tokens = 0
            clarified = False          # 是否在意图理解后被条件边短路到 END

            async for chunk in graph.astream(graph_inputs, stream_mode="values"):
                state = chunk or {}
                executed = state.get("node_executed") or []
                # 仅处理本次新完成的节点（values 首帧可能是初始状态，node_executed 为空）
                new_modules = executed[seen_executed:]
                seen_executed = len(executed)

                for mod_name in new_modules:
                    name = MODULE_TO_NODE.get(mod_name, mod_name)
                    if name not in NODE_NAMES:
                        continue
                    idx = NODE_NAMES.index(name)

                    # 累积 token
                    current_tokens = state.get("total_tokens", 0) or 0
                    delta_tokens = max(0, current_tokens - cumulative_tokens)
                    cumulative_tokens = current_tokens

                    progress_pct = int(((idx + 1) / total_nodes) * 100)

                    # yield 进度事件（携带该节点阶段成果文本，前端实时追加到气泡）
                    yield {
                        "event": "node_progress",
                        "data": {
                            "node": name,
                            "index": idx,
                            "total": total_nodes,
                            "progress": progress_pct,
                            "tokens": delta_tokens,
                            "total_tokens": cumulative_tokens,
                            "detail": self._node_result_summary(name, state),
                        },
                    }

                    # 澄清短路：意图理解要求澄清 → 图条件边直接 END，无后续节点
                    if name == "intent_understanding" and state.get("needs_clarification"):
                        clarified = True
                        break

                    # 若有下一个节点，yield 下一个节点的 node_start
                    if idx + 1 < total_nodes:
                        next_name = NODE_NAMES[idx + 1]
                        yield {
                            "event": "node_start",
                            "data": {
                                "node": next_name,
                                "index": idx + 1,
                                "total": total_nodes,
                                "detail": self.NODE_RUNNING_LABELS.get(next_name, "处理中…"),
                            },
                        }

                if clarified:
                    break

            latency_ms = int((time.time() - start_ts) * 1000)

            logger.info(
                f"[LangGraph] 流水线结束: "
                f"tokens={state.get('total_tokens', 0)} "
                f"cost={(state.get('total_cost', 0.0) or 0.0):.4f}元 "
                f"nodes={len(state.get('node_executed', []) or [])} "
                f"errors={len(state.get('errors', []) or [])} "
                f"clarified={clarified}"
            )

            # 5. 提取编排结果
            arranged = state.get("arranged_itinerary") or []
            final_output = state.get("final_output") or {}
            formatted = state.get("formatted_itinerary") or ""
            map_data = state.get("map_data") or {}
            budget_breakdown = state.get("budget_breakdown") or {}
            weather_info = state.get("weather_info") or {}
            total_tokens = state.get("total_tokens", 0) or 0
            total_cost = state.get("total_cost", 0.0) or 0.0
            errors = state.get("errors") or []

            # 6. 正常完成且有行程输出：创建新版本 + 扁平化 + 批量落库明细
            #    澄清短路时不产生行程版本
            version_number: Optional[int] = None
            itinerary_dict: Optional[dict] = None
            if not clarified and (arranged or final_output):
                total_budget = self._extract_total_budget(budget_breakdown, final_output)
                total_distance = self._extract_total_distance(final_output, map_data)
                version = await repos.versions.create_new_version(
                    session_id=session_id,
                    trigger="initial",
                    parent_version=None,
                    total_budget=total_budget,
                    total_distance_km=total_distance,
                    map_data=map_data or None,
                    raw_output=final_output or None,
                    tokens_total=total_tokens,
                    duration_sec=int(latency_ms / 1000),
                )
                # 扁平化：将层级式 arranged_itinerary（days > timeline）转为扁平行程项列表
                flat_items = self._flatten_itinerary(arranged)
                # 若 arranged 为空，尝试从 final_output 中提取 itinerary_structured
                if not flat_items and final_output:
                    structured = final_output.get("itinerary_structured") or []
                    if isinstance(structured, list) and structured:
                        flat_items = self._flatten_itinerary(structured)
                items_data = [
                    self._normalize_item(it, version.id, i)
                    for i, it in enumerate(flat_items)
                    if isinstance(it, dict)
                ]
                if items_data:
                    await repos.items.bulk_create(items_data)
                logger.info(
                    f"落库行程明细: {len(items_data)} 条 items, "
                    f"version_id={version.id}"
                )
                version_number = version.version
                itinerary_dict = {
                    "version": version_number,
                    "total_budget": total_budget,
                    "total_distance_km": total_distance,
                    "map_data": map_data,
                    "budget_breakdown": budget_breakdown,
                    "weather_info": weather_info,
                    "items": items_data,
                }

            # 7. 保存助手回复 + 提交
            if clarified:
                # 澄清短路：回复内容即澄清问题，不产生行程
                reply = (
                    state.get("clarification_question")
                    or "为了更好地为你规划，请补充目的地、旅行天数或预算等信息。"
                )
            else:
                reply = formatted or self._summarize_state(state)
            tokens_out = max(0, total_tokens - tokens_in)
            await repos.messages.append_message(
                session_id=session_id,
                role="assistant",
                content=reply,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=total_cost,
                latency_ms=latency_ms,
                extra={
                    "version": version_number,
                    "errors": errors,
                    "needs_clarification": clarified,
                },
            )

            # 先提交数据库（一旦提交就不再回滚，确保数据落库）
            await repos.commit()
            logger.info(
                f"消息处理完成 session={session_id} "
                f"version={version_number} latency_ms={latency_ms}"
            )

            # 8. 需要澄清时先发 clarification 事件（前端据此弹出澄清提示）
            if clarified:
                try:
                    yield {
                        "event": "clarification",
                        "data": {
                            "question": reply,
                            "intent_confidence": state.get("intent_confidence", 0.0),
                        },
                    }
                except Exception as yield_exc:  # noqa: BLE001
                    logger.warning(f"[SSE] 客户端在 clarification 事件时断开: {yield_exc}")

            # 9. yield done 事件（客户端断开不影响已提交数据）
            try:
                yield {
                    "event": "done",
                    "data": {
                        "reply": reply,
                        "itinerary": itinerary_dict,
                        "version": version_number,
                        "needs_clarification": clarified,
                    },
                }
            except (GeneratorExit, ConnectionError, Exception) as yield_exc:
                logger.warning(
                    f"[SSE] 客户端在 done 事件时断开: {yield_exc}"
                )

        except Exception as exc:
            await sess.rollback()
            logger.opt(exception=exc).error(
                f"流式消息处理失败 session={session_id}: {exc}"
            )
            try:
                yield {
                    "event": "error",
                    "data": {
                        "message": str(exc),
                    },
                }
            except Exception:
                pass
        finally:
            await sess.close()

    async def send_message(self, session_id: str, message: str) -> dict:
        """用户发消息 → 调用流式生成器 → 聚合最后一个 done 返回"""
        last_done: Optional[dict] = None
        async for event in self.send_message_stream(session_id=session_id, message=message):
            if event.get("event") == "done":
                last_done = event.get("data")
            elif event.get("event") == "error":
                err_msg = (event.get("data") or {}).get("message", "未知错误")
                raise LLMCallError(err_msg)
        if last_done is None:
            raise LLMCallError("流式处理未返回最终结果")
        return last_done

    # ============================================================
    # 行程版本读取
    # ============================================================
    async def get_current_itinerary(self, session_id: str) -> dict:
        """获取当前行程版本"""
        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)
            version = await repos.versions.get_current(session_id)
            if version is None:
                raise ResourceNotFound(f"该会话暂无行程版本: {session_id}")
            items = await repos.items.list_by_version(version.id)
            return self._version_to_dict(version, items)
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    async def get_version(self, session_id: str, version: int) -> dict:
        """获取指定版本行程"""
        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)
            version_obj = await repos.versions.get_by_version(session_id, version)
            if version_obj is None:
                raise ResourceNotFound(
                    f"版本不存在: session={session_id} version={version}"
                )
            items = await repos.items.list_by_version(version_obj.id)
            return self._version_to_dict(version_obj, items)
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    async def list_versions(self, session_id: str) -> list[dict]:
        """列出所有版本"""
        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)
            versions = await repos.versions.list_by_session(session_id)
            return [
                {
                    "version": v.version,
                    "parent_version": v.parent_version,
                    "trigger": v.trigger,
                    "total_budget": v.total_budget,
                    "total_distance_km": v.total_distance_km,
                    "is_current": v.is_current,
                    "tokens_total": v.tokens_total,
                    "duration_sec": v.duration_sec,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                }
                for v in versions
            ]
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    # ============================================================
    # 静态工具方法（feedback_service 也会复用）
    # ============================================================
    @staticmethod
    def _node_result_summary(node_name: str, state: dict) -> str:
        """节点完成后，从 state 提取一句阶段成果摘要（供 SSE 实时展示）"""
        try:
            if node_name == "intent_understanding":
                style = (state.get("preferences") or {}).get("travel_style", "")
                style_part = f" · {style}" if style else ""
                return (
                    f"已识别需求：{state.get('destination') or '未知目的地'} · "
                    f"{state.get('travel_days')}天 · "
                    f"预算 ¥{int(state.get('budget_min') or 0)}-{int(state.get('budget_max') or 0)}"
                    f"{style_part}"
                )
            if node_name == "itinerary_framework":
                arranged = state.get("arranged_itinerary") or []
                days = len(arranged)
                total_acts = sum(
                    len((d or {}).get("timeline") or [])
                    for d in arranged
                    if isinstance(d, dict)
                )
                return f"行程框架已完成：{days} 天路线，共安排 {total_acts} 个活动"
            if node_name == "poi_retrieval":
                poi_list = state.get("poi_candidates") or []
                names = []
                for p in poi_list[:5]:
                    if isinstance(p, dict):
                        name = p.get("name") or p.get("title")
                        if name:
                            names.append(str(name))
                tail = f"（{'、'.join(names)} 等）" if names else ""
                return f"POI 检索完成：共找到 {len(poi_list)} 个候选地点{tail}"
            if node_name == "travel_context":
                forecast = (state.get("weather_info") or {}).get("forecasts") or []
                weather_txt = ""
                if forecast and isinstance(forecast[0], dict):
                    day = forecast[0]
                    weather_txt = (
                        f"，当地{day.get('dayweather') or ''} "
                        f"{day.get('daytemp_float') or day.get('daytemp') or ''}°"
                    )
                return f"出行信息已整合：{len(state.get('routes') or [])} 段路线{weather_txt}"
            if node_name == "resource_budget":
                bd = state.get("budget_breakdown") or {}
                total = bd.get("total") or bd.get("total_budget")
                detail_parts = []
                for key, label in (
                    ("hotel", "住宿"), ("food", "餐饮"),
                    ("transport", "交通"), ("tickets", "门票"),
                ):
                    val = bd.get(key)
                    if isinstance(val, (int, float)) and val > 0:
                        detail_parts.append(f"{label}¥{int(val)}")
                total_txt = f"，总计约 ¥{int(total)}" if isinstance(total, (int, float)) else ""
                detail_txt = f"（{'、'.join(detail_parts)}）" if detail_parts else ""
                return (
                    f"预算核算完成：{len(state.get('hotels') or [])} 家酒店、"
                    f"{len(state.get('foods') or [])} 家餐厅推荐{detail_txt}{total_txt}"
                )
            if node_name == "content_beautify":
                text_len = len(state.get("formatted_itinerary") or "")
                return f"行程文案已生成（约 {text_len} 字）"
            if node_name == "map_and_share":
                md = state.get("map_data") or {}
                markers = len(md.get("markers") or [])
                lines = len(md.get("polylines") or [])
                return f"地图数据就绪：{markers} 个标记点、{lines} 条路线"
            if node_name == "final_output":
                return "最终行程已组装完成"
        except Exception:  # noqa: BLE001 - 摘要提取失败不影响主流程
            pass
        return "该步骤已完成"

    @staticmethod
    def _build_title(destination: Optional[str], travel_days: Optional[int]) -> str:
        """根据目的地和天数生成默认标题"""
        parts = []
        if destination:
            parts.append(destination)
        if travel_days:
            parts.append(f"{travel_days}日游")
        return " - ".join(parts) if parts else "未命名行程"

    @staticmethod
    def _summarize_state(state: dict) -> str:
        """无格式化输出时，生成简要摘要"""
        arranged = state.get("arranged_itinerary") or []
        destination = state.get("destination") or ""
        if arranged:
            days = sorted(
                {it.get("day", 1) for it in arranged if isinstance(it, dict)}
            )
            return (
                f"已生成行程：{destination} 共 {len(days)} 天、"
                f"{len(arranged)} 个活动。"
            )
        errors = state.get("errors") or []
        if errors:
            return "行程生成遇到问题：" + "；".join(str(e) for e in errors)
        return "已为您规划行程，详情请查看。"

    @staticmethod
    def _extract_total_budget(
        budget_breakdown: dict, final_output: dict
    ) -> Optional[float]:
        """从预算明细或最终输出中提取总预算"""
        for source in (budget_breakdown, final_output):
            if not isinstance(source, dict):
                continue
            for key in ("total_budget", "total", "budget_total", "grand_total"):
                val = source.get(key)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    return float(val)
        return None

    @staticmethod
    def _extract_total_distance(
        final_output: dict, map_data: dict
    ) -> Optional[float]:
        """从最终输出或地图数据中提取总距离 (km)"""
        for source in (final_output, map_data):
            if not isinstance(source, dict):
                continue
            for key in ("total_distance_km", "total_distance", "distance_km"):
                val = source.get(key)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    return float(val)
        return None

    @classmethod
    def _flatten_itinerary(cls, arranged: list) -> list[dict]:
        """将层级式 arranged_itinerary（days > timeline）扁平化为行程项列表

        Agent Node2 输出结构：
          [{day:1, timeline:[{time, activity, poi_id, duration_min, ...}], hotel:...}, ...]

        输出：
          [{day, order_in_day, item_type, title, ...}, ...]
        """
        items: list[dict] = []
        for day_block in arranged:
            if not isinstance(day_block, dict):
                continue
            day_num = int(day_block.get("day", 1))
            timeline = day_block.get("timeline") or []
            order = 1
            for entry in timeline:
                if not isinstance(entry, dict):
                    continue
                activity = entry.get("activity") or entry.get("name") or "未命名活动"
                entry_type = entry.get("type")
                if not entry_type:
                    if "酒店" in activity or "hotel" in str(entry.get("poi_id", "")).lower():
                        entry_type = "hotel"
                    elif any(kw in activity for kw in ["餐", "食", "吃", "晚餐", "午餐", "早餐"]):
                        entry_type = "food"
                    elif any(kw in activity for kw in ["交通", "地铁", "巴士", "出租", "步行"]):
                        entry_type = "transport"
                    else:
                        entry_type = "attraction"
                item = {
                    "day": day_num,
                    "order_in_day": order,
                    "item_type": entry_type,
                    "title": activity,
                    "start_time": entry.get("time"),
                    "duration_min": entry.get("duration_min"),
                    "location_name": activity,
                    "amap_poi_id": entry.get("poi_id"),
                    "transport_from_prev": entry.get("transport_to_next"),
                    "description": f"{day_block.get('date', '')} {day_block.get('weather', '')}".strip() or None,
                }
                cost_fields = ["cost_ticket", "cost_food", "cost_hotel", "cost_transport", "cost_other"]
                for cf in cost_fields:
                    if cf in entry:
                        item[cf] = entry[cf]
                items.append(item)
                order += 1
            hotel_name = day_block.get("hotel")
            if hotel_name:
                items.append({
                    "day": day_num,
                    "order_in_day": order,
                    "item_type": "hotel",
                    "title": hotel_name,
                    "location_name": hotel_name,
                    "description": f"{day_num} 晚住宿：{hotel_name}",
                })
        return items

    @classmethod
    def _normalize_item(cls, raw: dict, version_id: int, index: int) -> dict:
        """将 Agent 输出的行程项归一化为可入库的 ItineraryItem dict

        - 仅保留模型已定义字段，避免 bulk_create 因未知字段报错
        - day / order_in_day 强制为 int
        - item_type / title 兜底，兼容 name / type 等别名
        """
        if not isinstance(raw, dict):
            raw = {}
        item = {k: raw[k] for k in cls._ITEM_FIELDS if k in raw}
        item["version_id"] = version_id
        # day / order_in_day 必须有且为 int
        day_val = raw.get("day", 1)
        item["day"] = int(day_val) if day_val is not None else 1
        order_val = raw.get("order_in_day", index + 1)
        item["order_in_day"] = (
            int(order_val) if order_val is not None else index + 1
        )
        # item_type / title 兜底
        if not item.get("item_type"):
            item["item_type"] = raw.get("type") or "attraction"
        if not item.get("title"):
            item["title"] = raw.get("name") or "未命名活动"
        return item

    @staticmethod
    def _item_to_dict(item: Any) -> dict:
        """将 ItineraryItem ORM 对象转为 dict"""
        return {
            "id": item.id,
            "version_id": item.version_id,
            "day": item.day,
            "order_in_day": item.order_in_day,
            "item_type": item.item_type,
            "title": item.title,
            "description": item.description,
            "start_time": item.start_time,
            "end_time": item.end_time,
            "duration_min": item.duration_min,
            "location_name": item.location_name,
            "location_address": item.location_address,
            "longitude": item.longitude,
            "latitude": item.latitude,
            "amap_poi_id": item.amap_poi_id,
            "transport_from_prev": item.transport_from_prev,
            "travel_time_min": item.travel_time_min,
            "travel_distance_m": item.travel_distance_m,
            "cost_ticket": item.cost_ticket,
            "cost_food": item.cost_food,
            "cost_hotel": item.cost_hotel,
            "cost_transport": item.cost_transport,
            "cost_other": item.cost_other,
            "tags": item.tags,
            "image_url": item.image_url,
            "rag_refs": item.rag_refs,
            "extra": item.extra,
        }

    @classmethod
    def _version_to_dict(cls, version: Any, items: list) -> dict:
        """将版本 + 明细转为对外 dict"""
        # 从 raw_output 中提取 budget_breakdown 和 weather_info
        raw = version.raw_output if isinstance(version.raw_output, dict) else {}
        budget_breakdown = raw.get("budget_breakdown") or {}
        weather_info = raw.get("weather") or {}

        return {
            "session_id": version.session_id,
            "version": version.version,
            "parent_version": version.parent_version,
            "trigger": version.trigger,
            "total_budget": version.total_budget,
            "total_distance_km": version.total_distance_km,
            "map_data": version.map_data,
            "budget_breakdown": budget_breakdown,
            "weather_info": weather_info,
            "raw_output": version.raw_output,
            "generated_by": version.generated_by,
            "tokens_total": version.tokens_total,
            "duration_sec": version.duration_sec,
            "is_current": version.is_current,
            "created_at": version.created_at.isoformat()
            if version.created_at
            else None,
            "items": [cls._item_to_dict(it) for it in items],
        }

    @staticmethod
    def _session_to_dict(session: Any) -> dict:
        """将 ChatSession ORM 对象转为 dict"""
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "title": session.title,
            "destination": session.destination,
            "travel_days": session.travel_days,
            "budget_min": session.budget_min,
            "budget_max": session.budget_max,
            "preferences": session.preferences,
            "status": session.status,
            "created_at": session.created_at.isoformat()
            if session.created_at
            else None,
            "updated_at": session.updated_at.isoformat()
            if session.updated_at
            else None,
        }


# ============================================================
# 单例
# ============================================================
_service: Optional[ItineraryService] = None


def get_itinerary_service() -> ItineraryService:
    """获取行程服务单例"""
    global _service
    if _service is None:
        _service = ItineraryService()
    return _service
