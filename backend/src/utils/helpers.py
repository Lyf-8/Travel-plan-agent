"""通用工具函数"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any, Optional


def generate_uuid() -> str:
    """生成无横线 UUID"""
    return uuid.uuid4().hex


def now_iso() -> str:
    """当前 ISO 时间字符串"""
    return datetime.now().isoformat()


def safe_json_loads(text: str, default: Any = None) -> Any:
    """安全 JSON 解析，失败返回 default"""
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def extract_json_from_text(text: str) -> Optional[dict]:
    """从可能包含 markdown 代码块的文本中提取 JSON dict"""
    if not text:
        return None
    # 1. 直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, TypeError):
        pass
    # 2. 提取 ```json ... ``` 代码块
    pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    matches = re.findall(pattern, text)
    for m in matches:
        try:
            obj = json.loads(m)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, TypeError):
            continue
    # 3. 正则查找第一个 {...} 块
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def truncate(text: str, max_len: int = 200, suffix: str = "...") -> str:
    """截断文本"""
    if not text or len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix


def mask_sensitive(value: Optional[str], visible: int = 4) -> str:
    """脱敏处理（如 API Key 只显示前几位）"""
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible)


def safe_float(value: Any, default: float = 0.0) -> float:
    """安全转 float"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """安全转 int"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def merge_dicts(*dicts: Optional[dict]) -> dict:
    """合并多个 dict（后者覆盖前者）"""
    result: dict = {}
    for d in dicts:
        if d:
            result.update(d)
    return result
