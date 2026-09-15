"""行程相关 Pydantic 模型

包含行程明细、版本、反馈、重生成等数据结构，
供 ``api/routers/itinerary.py`` 使用。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ItineraryItemSchema(BaseModel):
    """行程明细项（对应 ItineraryItem ORM，所有字段可选）"""

    id: Optional[int] = None
    version_id: Optional[int] = None
    day: Optional[int] = None
    order_in_day: Optional[int] = None
    item_type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_min: Optional[int] = None
    location_name: Optional[str] = None
    location_address: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    amap_poi_id: Optional[str] = None
    transport_from_prev: Optional[str] = None
    travel_time_min: Optional[int] = None
    travel_distance_m: Optional[int] = None
    cost_ticket: Optional[float] = None
    cost_food: Optional[float] = None
    cost_hotel: Optional[float] = None
    cost_transport: Optional[float] = None
    cost_other: Optional[float] = None
    tags: Optional[list] = None
    image_url: Optional[str] = None
    rag_refs: Optional[list] = None
    extra: Optional[dict] = None
    created_at: Optional[datetime] = None


class ItineraryVersionSchema(BaseModel):
    """行程版本（含明细列表）"""

    version: int
    trigger: Optional[str] = None
    total_budget: Optional[float] = None
    total_distance_km: Optional[float] = None
    map_data: Optional[dict] = None
    budget_breakdown: Optional[dict] = None
    weather_info: Optional[dict] = None
    raw_output: Optional[dict] = None
    is_current: Optional[bool] = None
    created_at: Optional[datetime] = None
    items: list[ItineraryItemSchema] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    """反馈提交请求"""

    version_id: int = Field(..., description="行程版本 ID")
    rating: int = Field(..., ge=1, le=5, description="评分 1-5")
    comment: str = Field(..., description="文字反馈")
    edit_instructions: Optional[str] = Field(default=None, description="修改指令（重生成时输入给 Agent）")


class FeedbackResponse(BaseModel):
    """反馈提交响应"""

    feedback_id: int
    status: str


class RegenerateRequest(BaseModel):
    """重生成请求"""

    feedback_id: Optional[int] = Field(default=None, description="关联反馈 ID")
    edit_instructions: Optional[str] = Field(default=None, description="修改指令")


class RegenerateResponse(BaseModel):
    """重生成响应"""

    new_version: int
    items: list[ItineraryItemSchema] = Field(default_factory=list)


class VersionListItem(BaseModel):
    """版本列表项"""

    version: int
    trigger: Optional[str] = None
    is_current: Optional[bool] = None
    created_at: Optional[datetime] = None
