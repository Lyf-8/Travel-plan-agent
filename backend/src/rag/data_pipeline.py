"""知识库数据构建流水线

任务：
    - 将"景点百科文本 / 高德 POI 详情 / 网页抓取内容" → 分块 → embedding → 入向量库 + 元数据写 SQLite
    - 支持增量（基于 doc_id 去重）与重建
    - 对外：build_knowledge_from_sources()

渐进积累策略：
    1. Agent3 景点检索时，如果命中的景点本地百科资料不丰富 → 触发 wiki_search
    2. 将抓到的简介通过 pipeline 写入向量库 → 下次同样查询直接命中
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional, Sequence

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import get_session_factory
from ..db.repositories import Repositories
from ..tools.wiki_search import WikiResult
from .retriever import Retriever, get_retriever
from .vector_store import VectorPoint


# ============================================================
# 分块器（chunk_size + overlap）
# ============================================================
@dataclass
class Chunk:
    index: int
    text: str
    start: int
    end: int


def split_into_chunks(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    """按字符边界分块，相邻块保留 overlap 上下文重叠"""
    if not text:
        return []
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    length = len(text)
    if length <= chunk_size:
        return [Chunk(index=0, text=text, start=0, end=length)]

    step = max(chunk_size - chunk_overlap, 1)
    chunks: list[Chunk] = []
    idx = 0
    pos = 0
    while pos < length:
        end = min(pos + chunk_size, length)
        # 尝试在换行或句子标点处切开（更自然）
        if end < length:
            cut_candidates = [
                text.rfind("\n", pos, end),
                text.rfind("。", pos, end),
                text.rfind("！", pos, end),
                text.rfind("？", pos, end),
                text.rfind(". ", pos, end),
            ]
            cut = max(cut_candidates)
            if cut > pos + chunk_size // 2:
                end = cut + 1
        chunk_text = text[pos:end].strip()
        if chunk_text:
            chunks.append(Chunk(index=idx, text=chunk_text, start=pos, end=end))
            idx += 1
        if end >= length:
            break
        pos += step
    return chunks


def make_doc_id(prefix: str, key: str) -> str:
    """生成稳定 doc_id：prefix + sha1(key) 前缀"""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


# ============================================================
# Pipeline 主类
# ============================================================
class KnowledgeDataPipeline:
    """知识库构建流水线"""

    def __init__(
        self,
        retriever: Optional[Retriever] = None,
    ) -> None:
        self.retriever = retriever or get_retriever()

    # ============================================================
    # 1. 批量入向量库 + SQLite 元数据
    # ============================================================
    async def ingest_documents(
        self,
        title: str,
        content: str,
        *,
        source_type: str,               # wiki / amap_poi / scrapy / manual
        source_id: Optional[str] = None,
        city: Optional[str] = None,
        category: Optional[str] = None,
        image_url: Optional[str] = None,
        session: Optional[AsyncSession] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> int:
        """
        一条"文档"入库：
        1) 分块
        2) 每块写向量库
        3) 每块元数据写 rag_documents 表
        返回写入 chunk 数
        """
        if not content.strip():
            return 0

        base_key = f"{source_type}|{source_id or title}|{city or ''}"
        base_doc_id = make_doc_id(source_type, base_key)

        # 分块
        chunks = split_into_chunks(content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not chunks:
            return 0

        points: list[VectorPoint] = []
        rag_docs: list[dict] = []
        for c in chunks:
            doc_id = f"{base_doc_id}-{c.index:03d}"
            meta = {
                "doc_id": doc_id,
                "title": title,
                "city": city,
                "category": category,
                "source_type": source_type,
                "source_id": source_id,
                "chunk_index": c.index,
                "image_url": image_url,
            }
            points.append(VectorPoint(text=c.text, metadata=meta))
            rag_docs.append({
                "doc_id": doc_id,
                "title": title,
                "content_snippet": c.text[:200],
                "source_type": source_type,
                "source_id": source_id,
                "category": category,
                "city": city,
                "chunk_index": c.index,
            })

        # 写向量库
        ids = await self.retriever.ingest(points)

        # 写 SQLite 元数据
        inserted_rag_count = 0
        own_session = False
        sess = session
        try:
            if sess is None:
                factory = get_session_factory()
                sess = factory()
                own_session = True
            repos = Repositories(sess)
            inserted_rag_count = await repos.rag_docs.bulk_upsert(rag_docs)
            if own_session:
                await sess.commit()
        except Exception as e:  # noqa: BLE001
            logger.error(f"写入 RAG 元数据失败: {e}")
            if own_session:
                await sess.rollback()
        finally:
            if own_session and sess is not None:
                await sess.close()

        logger.info(
            f"知识库写入完成: title={title[:20]} "
            f"chunks={len(chunks)} vector_ids={len(ids)} rag_meta_inserted={inserted_rag_count}"
        )
        return len(chunks)

    # ============================================================
    # 2. 从 Wikipedia 搜索结果直接入库（外部搜索兜底写入）
    # ============================================================
    async def ingest_from_wiki_results(
        self,
        results: Sequence[WikiResult],
        city: Optional[str] = None,
        category: str = "attraction",
        session: Optional[AsyncSession] = None,
    ) -> int:
        """把 WikiSearch.search 返回的结果写入本地 RAG 缓存"""
        total = 0
        for r in results:
            if not r.snippet:
                continue
            n = await self.ingest_documents(
                title=r.title,
                content=r.snippet,
                source_type="wiki",
                source_id=r.url,
                city=city,
                category=category,
                session=session,
            )
            total += n
        return total


_instance: Optional[KnowledgeDataPipeline] = None


def get_data_pipeline() -> KnowledgeDataPipeline:
    global _instance
    if _instance is None:
        _instance = KnowledgeDataPipeline()
    return _instance
