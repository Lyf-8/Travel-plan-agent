"""输入校验工具"""
from __future__ import annotations

import re
from typing import Optional

# 城市名白名单（可扩展）
_VALID_CITIES: set[str] = {
    "北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "成都", "重庆",
    "西安", "武汉", "长沙", "厦门", "青岛", "大连", "昆明", "大理", "丽江",
    "三亚", "桂林", "西藏", "拉萨", "哈尔滨", "沈阳", "天津", "济南", "郑州",
    "福州", "南昌", "合肥", "太原", "石家庄", "呼和浩特", "乌鲁木齐", "兰州",
    "银川", "西宁", "贵阳", "南宁", "海口", "珠海", "佛山", "东莞", "无锡",
    "宁波", "温州", "青岛", "烟台", "威海",
}


def validate_city(city: Optional[str]) -> Optional[str]:
    """校验城市名，返回标准名或 None"""
    if not city or not isinstance(city, str):
        return None
    city = city.strip()
    # 直接命中
    if city in _VALID_CITIES:
        return city
    # 模糊匹配：包含关系
    for valid in _VALID_CITIES:
        if city in valid or valid in city:
            return valid
    return None  # 未命中白名单也不报错，仅返回 None


def validate_travel_days(days: Optional[int]) -> int:
    """校验旅行天数（1-30）"""
    if days is None:
        return 0
    try:
        d = int(days)
    except (TypeError, ValueError):
        return 0
    if d < 1:
        return 0
    if d > 30:
        return 30
    return d


def validate_budget(min_val: Optional[float], max_val: Optional[float]) -> tuple[float, float]:
    """校验预算范围，返回 (min, max)"""
    mn = 0.0 if min_val is None else max(0.0, float(min_val))
    mx = 0.0 if max_val is None else max(0.0, float(max_val))
    if mn > mx and mx > 0:
        mn, mx = mx, mn
    return mn, mx


def validate_email(email: Optional[str]) -> bool:
    """简单邮箱校验"""
    if not email:
        return False
    pattern = r"^[\w.+-]+@[\w-]+\.[\w.-]+$"
    return bool(re.match(pattern, email))


def sanitize_input(text: Optional[str], max_len: int = 2000) -> str:
    """清洗用户输入：去首尾空白、截断、移除控制字符"""
    if not text:
        return ""
    text = text.strip()
    # 移除控制字符（保留换行和制表符）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    if len(text) > max_len:
        text = text[:max_len]
    return text
