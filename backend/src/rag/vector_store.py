"""向量库封装：双后端（Qdrant 生产 / ChromaDB 开发轻量）

设计：
    - 定义 VectorStore 抽象基类
    - 实现 QdrantVectorStore（生产用，支持分布式）
    - 实现 ChromaVectorStore（开发/单机用，零依赖外部服务）
    - 用工厂函数 get_vector_store() 根据配置 VECTOR_DB_BACKEND 自动选择
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from loguru import logger

from ..core.config import get_settings
from ..core.exceptions import ConfigError, RAGError


@dataclass
class VectorPoint:
    """待入库的一条数据（写入侧）"""
    text: str                                  # 原始文本
    embedding: Optional[list[float]] = None    # 若为 None 由 add_documents 自动计算
    metadata: dict = field(default_factory=dict)
    # metadata 约定字段：
    #   "doc_id"      : 文档 ID（对应 SQLite rag_documents.doc_id，用于关联）
    #   "title"       : 标题
    #   "city"        : 城市过滤
    #   "category"    : 分类过滤
    #   "source_type" : 来源类型（wiki / amap_poi ...）


@dataclass
class SearchHit:
    """检索结果（查询侧）"""
    score: float                              # 相似度得分（越大越相似）
    text: str                                 # 命中的文本片段
    metadata: dict = field(default_factory=dict)
    id: Optional[str] = None


# ============================================================
# 抽象基类
# ============================================================
class VectorStore(ABC):
    """向量库抽象接口"""

    backend_name: str = "abstract"

    @abstractmethod
    def is_ready(self) -> bool: ...

    @abstractmethod
    async def ensure_collection(self, vector_size: int) -> None:
        """确保 collection 存在，不存在则创建"""
        ...

    @abstractmethod
    async def add_documents(
        self,
        points: Sequence[VectorPoint],
        embed_fn,  # Callable[[list[str]], list[list[float]]]
        batch_size: int = 64,
    ) -> list[str]:
        """批量写入文档，返回 point_ids 列表"""
        ...

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[SearchHit]:
        """
        向量检索 + 元数据过滤
        filters: { "city": "北京", "category": "attraction", ... }
        """
        ...

    @abstractmethod
    async def delete_by_ids(self, ids: Sequence[str]) -> int:
        """按 IDs 删除，返回删除数"""
        ...

    @abstractmethod
    async def count(self) -> int: ...


# ============================================================
# ChromaDB 实现（默认：零配置即可跑）
# ============================================================
class ChromaVectorStore(VectorStore):
    backend_name = "chroma"

    def __init__(self) -> None:
        settings = get_settings()
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError as e:
            raise ConfigError("chromadb 未安装，请执行 pip install chromadb") from e

        persist_dir = Path(settings.CHROMA_PERSIST_DIR)
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist_dir.resolve()),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection_name = settings.CHROMA_COLLECTION_NAME
        self._collection = None
        logger.info(f"ChromaDB 已加载: persist_dir={persist_dir.resolve()}")

    def is_ready(self) -> bool:
        return self._client is not None

    async def ensure_collection(self, vector_size: int) -> None:
        try:
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.debug(f"Chroma collection 就绪: {self._collection_name}")
        except Exception as e:  # noqa: BLE001
            raise RAGError(f"Chroma collection 创建失败: {e}") from e

    async def add_documents(
        self,
        points: Sequence[VectorPoint],
        embed_fn,
        batch_size: int = 64,
    ) -> list[str]:
        if self._collection is None:
            raise RAGError("Chroma collection 未初始化，请先调用 ensure_collection()")

        if not points:
            return []

        all_ids: list[str] = []
        for start in range(0, len(points), batch_size):
            batch = list(points[start : start + batch_size])
            texts = [p.text for p in batch]
            # 如有未 embedding 的，批量计算
            missing_idx = [i for i, p in enumerate(batch) if p.embedding is None]
            if missing_idx:
                missing_texts = [batch[i].text for i in missing_idx]
                embs = await _maybe_async(embed_fn, missing_texts)
                for i, emb in zip(missing_idx, embs):
                    batch[i].embedding = list(emb)

            ids = [str(p.metadata.get("doc_id") or uuid.uuid4().hex) for p in batch]
            embs = [p.embedding or [] for p in batch]
            metas = [p.metadata for p in batch]

            self._collection.upsert(
                ids=ids,
                embeddings=embs,
                documents=texts,
                metadatas=metas,
            )
            all_ids.extend(ids)
        logger.debug(f"Chroma 写入 {len(all_ids)} 条")
        return all_ids

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[SearchHit]:
        if self._collection is None:
            raise RAGError("Chroma collection 未初始化")

        # Chroma filters: $and
        where: Optional[dict] = None
        if filters:
            items = [f for f in ({k: v} for k, v in filters.items() if v is not None)]
            if len(items) == 1:
                where = items[0]
            elif len(items) > 1:
                where = {"$and": items}

        result = self._collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits: list[SearchHit] = []
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        for _id, text, meta, dist in zip(ids, docs, metas, dists):
            # Chroma 默认使用 cosine distance（0 表示完全相同），转为相似度 score
            score = 1.0 - float(dist)
            hits.append(SearchHit(score=score, text=text, metadata=meta or {}, id=_id))
        return hits

    async def delete_by_ids(self, ids: Sequence[str]) -> int:
        if not ids or self._collection is None:
            return 0
        self._collection.delete(ids=list(ids))
        return len(ids)

    async def count(self) -> int:
        if self._collection is None:
            return 0
        return self._collection.count()


# ============================================================
# Qdrant 实现（生产用）
# ============================================================
class QdrantVectorStore(VectorStore):
    backend_name = "qdrant"

    def __init__(self) -> None:
        settings = get_settings()
        try:
            from qdrant_client import QdrantClient, models
        except ImportError as e:
            raise ConfigError("qdrant-client 未安装，请执行 pip install qdrant-client") from e

        kwargs: dict[str, Any] = {"host": settings.QDRANT_HOST, "port": settings.QDRANT_PORT}
        if settings.QDRANT_API_KEY:
            kwargs["api_key"] = settings.QDRANT_API_KEY
        self._client: QdrantClient = QdrantClient(**kwargs)
        self._models = models
        self._collection_name = settings.QDRANT_COLLECTION_NAME
        self._vector_size = settings.QDRANT_VECTOR_SIZE
        logger.info(f"Qdrant 连接完成: {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")

    def is_ready(self) -> bool:
        return self._client is not None

    async def ensure_collection(self, vector_size: int) -> None:
        m = self._models
        try:
            exists = self._client.collection_exists(self._collection_name)
        except Exception as e:  # noqa: BLE001
            raise RAGError(f"Qdrant 连接异常: {e}") from e
        if not exists:
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=m.VectorParams(
                    size=vector_size, distance=m.Distance.COSINE
                ),
            )
            logger.info(f"Qdrant collection 已创建: {self._collection_name}, dim={vector_size}")
        else:
            logger.debug(f"Qdrant collection 已存在: {self._collection_name}")

    async def add_documents(
        self,
        points: Sequence[VectorPoint],
        embed_fn,
        batch_size: int = 64,
    ) -> list[str]:
        from qdrant_client.models import PointStruct

        if not points:
            return []

        all_ids: list[str] = []
        for start in range(0, len(points), batch_size):
            batch = list(points[start : start + batch_size])
            missing_idx = [i for i, p in enumerate(batch) if p.embedding is None]
            if missing_idx:
                embs = await _maybe_async(embed_fn, [batch[i].text for i in missing_idx])
                for i, emb in zip(missing_idx, embs):
                    batch[i].embedding = list(emb)

            structs: list[PointStruct] = []
            for p in batch:
                pid = p.metadata.get("doc_id") or uuid.uuid4().hex
                structs.append(PointStruct(
                    id=pid,
                    vector=p.embedding or [],
                    payload={**p.metadata, "text": p.text},
                ))
                all_ids.append(str(pid))
            self._client.upsert(
                collection_name=self._collection_name, points=structs
            )
        logger.debug(f"Qdrant 写入 {len(all_ids)} 条")
        return all_ids

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[SearchHit]:
        m = self._models
        qfilter = None
        if filters:
            conditions = []
            for k, v in filters.items():
                if v is None:
                    continue
                conditions.append(m.FieldCondition(key=k, match=m.MatchValue(value=v)))
            if conditions:
                qfilter = m.Filter(must=conditions) if len(conditions) > 1 else conditions[0]

        results = self._client.search(
            collection_name=self._collection_name,
            query_vector=query_vector,
            limit=top_k,
            query_filter=qfilter,
            with_payload=True,
        )
        hits: list[SearchHit] = []
        for r in results:
            payload = r.payload or {}
            text = str(payload.pop("text", ""))
            hits.append(SearchHit(
                score=float(r.score),
                text=text,
                metadata=payload,
                id=str(r.id),
            ))
        return hits

    async def delete_by_ids(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        self._client.delete(
            collection_name=self._collection_name,
            points_selector=self._models.PointIdsList(points=list(ids)),
        )
        return len(ids)

    async def count(self) -> int:
        from qdrant_client.models import Filter
        r = self._client.count(
            collection_name=self._collection_name, count_filter=Filter()
        )
        return int(r.count)


# ============================================================
# 工厂
# ============================================================
_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        settings = get_settings()
        backend = (settings.VECTOR_DB_BACKEND or "chroma").lower()
        if backend == "qdrant":
            _store = QdrantVectorStore()
        else:
            _store = ChromaVectorStore()
    return _store


async def _maybe_async(fn, args):
    """兼容同步 / 异步 embedding 函数"""
    import asyncio
    result = fn(args)
    if asyncio.iscoroutine(result):
        return await result
    return result
