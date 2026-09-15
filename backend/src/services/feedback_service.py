"""反馈服务 - 用户反馈记录 + 基于反馈的行程重生成

职责：
    - 接收并落库用户对某版本行程的反馈（评分 / 评论 / 修改意见）
    - 基于反馈 + 当前行程，调用 Agent 重新生成新版本

说明：
    - 重生成会创建新版本，parent_version 指向当前版本
    - 反馈状态流转：submitted → processing → regenerated
"""
from __future__ import annotations

import json
from typing import Any, Optional

from loguru import logger

from ..agents.graph import get_graph
from ..core.exceptions import LLMCallError, ResourceNotFound, ValidationError
from ..db.connection import get_session_factory
from ..db.repositories import Repositories
from .itinerary_service import ItineraryService


class FeedbackService:
    """反馈与重生成服务"""

    async def submit_feedback(
        self,
        session_id: str,
        version_id: int,
        rating: Optional[int] = None,
        comment: Optional[str] = None,
        edit_instructions: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """保存用户反馈"""
        # 参数校验
        if rating is not None and not (1 <= rating <= 5):
            raise ValidationError("rating 必须在 1-5 之间")
        if not (comment or edit_instructions):
            raise ValidationError("comment 和 edit_instructions 至少需要一项")

        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)
            # 1. 校验会话存在
            session = await repos.sessions.get_by_session_id(session_id)
            if session is None:
                raise ResourceNotFound(f"会话不存在: {session_id}")
            # 校验版本存在且属于该会话
            version = await repos.versions.get_by_id(version_id)
            if version is None or version.session_id != session_id:
                raise ResourceNotFound(
                    f"版本不存在或不属于该会话: version_id={version_id}"
                )

            # 2. 创建反馈记录
            feedback = await repos.feedbacks.create(
                session_id=session_id,
                version_id=version_id,
                user_id=user_id,
                rating=rating,
                comment=comment,
                edit_instructions=edit_instructions,
                status="submitted",
            )
            await repos.commit()
            logger.info(
                f"反馈已保存: feedback_id={feedback.id}, "
                f"session={session_id}, version_id={version_id}"
            )
            return {"feedback_id": feedback.id, "status": "submitted"}
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    async def regenerate(
        self,
        session_id: str,
        feedback_id: Optional[int] = None,
        edit_instructions: Optional[str] = None,
    ) -> dict:
        """基于反馈重生成行程"""
        factory = get_session_factory()
        sess = factory()
        try:
            repos = Repositories(sess)

            # 1. 校验会话
            session = await repos.sessions.get_by_session_id(session_id)
            if session is None:
                raise ResourceNotFound(f"会话不存在: {session_id}")

            # 2. 获取当前版本 + 明细
            current_version = await repos.versions.get_current(session_id)
            if current_version is None:
                raise ResourceNotFound(f"该会话暂无可重新生成的行程: {session_id}")
            current_items = await repos.items.list_by_version(current_version.id)

            # 3. 获取反馈记录（若提供 feedback_id），并补充修改指令
            feedback: Any = None
            instructions = edit_instructions
            if feedback_id is not None:
                feedback = await repos.feedbacks.get_by_id(feedback_id)
                if feedback is None or feedback.session_id != session_id:
                    raise ResourceNotFound(
                        f"反馈不存在或不属于该会话: feedback_id={feedback_id}"
                    )
                if not instructions and feedback.edit_instructions:
                    instructions = feedback.edit_instructions
                # 标记为处理中
                await repos.feedbacks.update(feedback_id, status="processing")

            if not instructions:
                raise ValidationError(
                    "缺少修改指令：请提供 edit_instructions 或有效的 feedback_id"
                )

            # 4. 构建上下文：当前行程 + 修改指令（序列化为 JSON 字符串传给 Agent）
            current_itinerary = [
                ItineraryService._item_to_dict(it) for it in current_items
            ]
            context_payload = {
                "current_version": current_version.version,
                "current_itinerary": current_itinerary,
                "edit_instructions": instructions,
                "feedback_rating": getattr(feedback, "rating", None),
                "feedback_comment": getattr(feedback, "comment", None),
            }
            context_str = json.dumps(context_payload, ensure_ascii=False)

            # 5. 调用 LangGraph 重生成
            regen_prompt = self._build_regen_prompt(
                instructions, current_version.version
            )
            try:
                state = await get_graph().ainvoke({
                    "user_input": regen_prompt,
                    "session_id": session_id,
                    "destination": session.destination,
                    "travel_days": session.travel_days,
                    "budget_min": session.budget_min,
                    "budget_max": session.budget_max,
                    "preferences": session.preferences or {},
                    "feedback": context_str,
                })
            except Exception as exc:
                logger.opt(exception=exc).error(
                    f"重生成编排失败 session={session_id}: {exc}"
                )
                raise LLMCallError(f"行程重生成失败: {exc}") from exc

            # 6. 提取结果（LangGraph state 为普通 dict）
            arranged = state.get("arranged_itinerary") or []
            final_output = state.get("final_output") or {}
            map_data = state.get("map_data") or {}
            budget_breakdown = state.get("budget_breakdown") or {}
            total_tokens = state.get("total_tokens", 0) or 0
            errors = state.get("errors") or []

            total_budget = ItineraryService._extract_total_budget(
                budget_breakdown, final_output
            )
            total_distance = ItineraryService._extract_total_distance(
                final_output, map_data
            )

            # 7. 创建新版本（parent 指向当前版本）
            new_version = await repos.versions.create_new_version(
                session_id=session_id,
                trigger="feedback",
                parent_version=current_version.version,
                total_budget=total_budget,
                total_distance_km=total_distance,
                map_data=map_data or None,
                raw_output=final_output or None,
                tokens_total=total_tokens,
                duration_sec=0,
            )
            items_data = [
                ItineraryService._normalize_item(it, new_version.id, i)
                for i, it in enumerate(arranged)
                if isinstance(it, dict)
            ]
            if items_data:
                await repos.items.bulk_create(items_data)

            # 8. 更新反馈状态为已重生成
            if feedback is not None:
                await repos.feedbacks.update(
                    feedback.id,
                    status="regenerated",
                    regenerated_to_version=new_version.version,
                )

            await repos.commit()
            logger.info(
                f"重生成完成 session={session_id} "
                f"new_version={new_version.version} "
                f"parent={current_version.version}"
            )
            return {
                "new_version": new_version.version,
                "parent_version": current_version.version,
                "items": arranged,
                "errors": errors,
            }
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    # ============================================================
    # 工具方法
    # ============================================================
    @staticmethod
    def _build_regen_prompt(instructions: str, current_version: int) -> str:
        """构造重生成提示词"""
        return (
            f"请基于以下修改意见重新规划行程（当前为第 {current_version} 版）：\n"
            f"{instructions}"
        )


# ============================================================
# 单例
# ============================================================
_service: Optional[FeedbackService] = None


def get_feedback_service() -> FeedbackService:
    """获取反馈服务单例"""
    global _service
    if _service is None:
        _service = FeedbackService()
    return _service
