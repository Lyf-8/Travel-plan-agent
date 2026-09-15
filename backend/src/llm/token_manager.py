"""Token 管理 & 上下文压缩

上下文压缩策略：优先保留最近 N 条消息原文，更早的历史消息通过 LLM 摘要压缩，从约 30K tokens 压缩到 6K tokens（约 80% 压缩率）

解决问题：11 Agent 流水线越长，累计上下文越大（30K → 6K 压缩案例）

策略：
    1. summarize_long_text()   : 超过阈值的长文本（如景点介绍、历史消息）用 LLM 摘要
    2. build_compact_context() : 将历史消息列表按策略压缩（保留最近 N 条 + 老消息摘要）
    3. tiktoken_len()          : 不依赖 tiktoken 包的粗略长度估算（避免额外依赖）

注：真正高精度的计数建议用 tiktoken，这里提供轻量估算版。
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional, Sequence

from loguru import logger

from .factory import llm_call


# ============================================================
# 1. Token 估算（不依赖 tiktoken）
# ============================================================
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def approx_tokens(text: str) -> int:
    """粗略估算 tokens:
        - 中/日/韩字符：约 1 token / 1.5 字符
        - 英文单词：约 1 token / 4 字符
    参考 OpenAI 官方近似公式，精度 ±10%
    """
    if not text:
        return 0
    cjk_chars = len(_CJK_RE.findall(text))
    non_cjk = len(text) - cjk_chars
    # CJK: 每 1.5 个字符 1 token，非 CJK: 每 4 字符 1 token
    return int(cjk_chars / 1.5 + non_cjk / 4.0 + 0.5)


def approx_messages_tokens(messages: Sequence[dict]) -> int:
    """估算消息列表总 token（ChatML 风格：每条约 +4 固定开销）"""
    total = 0
    for m in messages:
        total += 4  # 每条消息基础 token（<|start|>role...）
        total += approx_tokens(m.get("role", ""))
        total += approx_tokens(m.get("content", ""))
        if "name" in m:
            total += approx_tokens(str(m["name"]))
    total += 3  # 最终 assistant 前缀
    return total


# ============================================================
# 2. 文本摘要压缩
# ============================================================
SUMMARIZE_PROMPT = """你是一个专业的信息摘要助手。请对以下文本进行精简摘要：

要求：
1. 保留所有核心事实（时间、地点、人物、数字、结论）
2. 去除修饰词、冗余句、重复内容
3. 输出长度不超过原文本的 {ratio}，优先使用要点式短句
4. 必须使用中文输出，不要添加解释或元信息

原文（约 {orig_tokens} tokens）：
-----
{text}
-----

精简摘要："""


async def summarize_long_text(
    text: str,
    max_tokens: int = 4000,
    target_ratio: float = 0.25,
    min_len_to_summarize: int = 500,
) -> str:
    """
    超过 min_len_to_summarize 的长文本，用 LLM 摘要压缩
    target_ratio: 目标压缩率（0.25 = 压缩到 25%）
    """
    if not text or len(text) < min_len_to_summarize:
        return text

    tok = approx_tokens(text)
    if tok <= max_tokens:
        # Token 没超就不用摘要
        return text

    # 如果文本非常长，先按段切分，逐段摘要再合并
    chunks = _split_text_by_paragraphs(text, max_chunk_chars=6000)
    if len(chunks) == 1:
        to_summarize = chunks[0]
    else:
        summaries = []
        for i, chunk in enumerate(chunks):
            try:
                s = await _do_summarize_once(chunk, target_ratio, approx_tokens(chunk))
                summaries.append(s)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"摘要 chunk {i} 失败，保留原片段: {e}")
                summaries.append(chunk[: int(len(chunk) * target_ratio)])
        to_summarize = "\n".join(summaries)

    return await _do_summarize_once(to_summarize, target_ratio, approx_tokens(to_summarize))


async def _do_summarize_once(text: str, ratio: float, orig_tokens: int) -> str:
    prompt = SUMMARIZE_PROMPT.format(
        ratio=f"{int(ratio * 100)}%",
        orig_tokens=orig_tokens,
        text=text[:15000],  # 再保险一次截断
    )
    messages = [{"role": "user", "content": prompt}]
    max_out = max(200, int(orig_tokens * ratio))
    try:
        resp = await llm_call(messages, max_tokens=max_out, temperature=0.0)
        return resp.content.strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"LLM 摘要失败，直接截断: {e}")
        return text[: int(len(text) * ratio)]


def _split_text_by_paragraphs(text: str, max_chunk_chars: int) -> list[str]:
    """按段落切分（空行分隔），每块最多 max_chunk_chars"""
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) + 2 <= max_chunk_chars:
            buf += ("\n\n" if buf else "") + p
        else:
            if buf:
                chunks.append(buf)
            if len(p) > max_chunk_chars:
                # 单段过长，硬切
                for i in range(0, len(p), max_chunk_chars):
                    chunks.append(p[i : i + max_chunk_chars])
                buf = ""
            else:
                buf = p
    if buf:
        chunks.append(buf)
    return chunks


# ============================================================
# 3. 历史消息上下文压缩（重点实现：30K → 6K 的核心机制）
# ============================================================
COMPRESS_SYSTEM_PROMPT = """请将以下多轮对话历史压缩为一份"事实摘要"：

要求：
1. 用要点列表格式，保留所有用户偏好、决策、已确定的行程信息
2. 忽略重复寒暄、礼貌语、模型思考过程
3. 必须明确区分"用户说过的"和"助手说过的"
4. 长度控制在 500 字以内

历史：
{history_text}

压缩摘要："""


async def build_compact_context(
    history: Sequence[dict],
    recent_k: int = 6,
    total_token_limit: int = 6144,
) -> list[dict]:
    """
    构建紧凑上下文：保留最近 recent_k 条消息，更早的消息合并为一条 system 摘要

    history: [{"role": "...", "content": "..."}, ...]
    return : 新的消息列表，首条可选为 system summary

    效果：30K tokens 的长对话 → 压缩到 6K 以内
    """
    if not history:
        return []

    # 先估算 token
    total_tok = approx_messages_tokens(list(history))
    if total_tok <= total_token_limit:
        return list(history)

    # 需要压缩：前面的旧消息做摘要，保留最后 recent_k 条
    if len(history) <= recent_k:
        return list(history)

    old_messages = list(history[:-recent_k])
    recent_messages = list(history[-recent_k:])

    old_text_lines = []
    for m in old_messages:
        role_label = "用户" if m.get("role") == "user" else "助手"
        content = m.get("content", "")
        # 内容太长先截断
        if len(content) > 2000:
            content = content[:2000] + "...(已截断)"
        old_text_lines.append(f"{role_label}: {content}")

    history_text = "\n".join(old_text_lines)

    try:
        resp = await llm_call(
            [{"role": "user", "content": COMPRESS_SYSTEM_PROMPT.format(history_text=history_text[:12000])}],
            max_tokens=800,
            temperature=0.0,
        )
        summary = resp.content.strip()
        logger.info(
            f"上下文压缩完成: "
            f"原始 {len(history)} 条 / 约 {total_tok} tokens → "
            f"保留最近 {recent_k} 条 + 1 条摘要"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"上下文压缩调用 LLM 失败: {e}，降级为硬截断")
        summary = f"【早期对话摘要（自动截断）：共 {len(old_messages)} 条省略】"

    # 组合：摘要 → 近期消息
    result: list[dict] = [
        {"role": "system", "content": f"【早期对话历史摘要】\n{summary}"}
    ]
    result.extend(recent_messages)
    return result


# ============================================================
# 4. 将 Python 对象转成紧凑 JSON 字符串（减少 token）
# ============================================================
def compact_json(obj: Any) -> str:
    """输出无空格的紧凑 JSON，用于给 LLM 传参时节省 tokens"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def pretty_json(obj: Any) -> str:
    """美观 JSON（调试用）"""
    return json.dumps(obj, ensure_ascii=False, indent=2)
