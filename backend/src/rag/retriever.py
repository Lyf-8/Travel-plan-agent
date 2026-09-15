"""混合检索器：向量检索 + 关键词重排 + RAG 缓存

关键实现点：
    1. Embedding 层：优先本地 sentence-transformers，不可用则回退 OpenAI Embedding API
    2. 检索层：Top-K 向量召回后，再按 BM25/关键词匹配度做 rerank
    3. 缓存层：高频查询命中 RAGCache，减少重复向量检索
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional, Sequence

from loguru import logger

from ..core.config import get_settings
from ..core.exceptions import RAGError
from .cache import RAGCache, get_rag_cache
from .vector_store import SearchHit, VectorPoint, VectorStore, get_vector_store


# ============================================================
# Embedding 封装（优先本地模型，备选 OpenAI API）
# ============================================================
class EmbeddingProvider:
    """统一 Embedding 调用接口"""

    def __init__(self) -> None:
        settings = get_settings()
        self._local_model = None
        self._local_model_name = settings.EMBEDDING_MODEL_NAME
        self._device = settings.EMBEDDING_DEVICE
        self._batch_size = settings.EMBEDDING_BATCH_SIZE
        self._use_openai_fallback = bool(settings.OPENAI_API_KEY)
        self._openai_embedding_model = settings.OPENAI_EMBEDDING_MODEL
        self._vector_size: Optional[int] = None

    # ---------- 懒加载本地模型（避免 import 阶段卡加载）----------
    def _ensure_local(self) -> bool:
        if self._local_model is not None:
            return True
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"加载本地 Embedding 模型: {self._local_model_name} ({self._device})")
            self._local_model = SentenceTransformer(
                self._local_model_name, device=self._device
            )
            # 探测一次向量维度
            dummy = self._local_model.encode(["test"], convert_to_numpy=True)
            self._vector_size = int(dummy.shape[1])
            logger.info(f"本地 Embedding 维度: {self._vector_size}")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"本地 Embedding 加载失败: {e}，回退 OpenAI Embedding API")
            self._local_model = None
            return False

    @property
    def vector_size(self) -> int:
        if self._vector_size is None:
            if self._ensure_local():
                pass  # _vector_size 在 _ensure_local 设置了
            elif self._use_openai_fallback:
                # text-embedding-3-small = 1536  (small)，假设默认
                self._vector_size = 512 if "small" not in self._openai_embedding_model else 1536
            else:
                # 兜底：bge-small-zh 为 512 维
                self._vector_size = 512
        return self._vector_size

    # ---------- 对外：encode ----------
    async def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if self._ensure_local():
            return await asyncio.get_running_loop().run_in_executor(
                None, self._encode_local, list(texts)
            )
        if self._use_openai_fallback:
            return await self._encode_openai(list(texts))
        raise RAGError("无可用 Embedding 后端（本地模型未加载且 OPENAI_API_KEY 未配置）")

    def _encode_local(self, texts: list[str]) -> list[list[float]]:
        assert self._local_model is not None
        embs = self._local_model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [list(map(float, row)) for row in embs]

    async def _encode_openai(self, texts: list[str]) -> list[list[float]]:
        from openai import AsyncOpenAI
        from ..core.config import get_settings as _get  # 防止循环别名
        s = _get()
        client = AsyncOpenAI(api_key=s.OPENAI_API_KEY, base_url=s.OPENAI_BASE_URL)
        # OpenAI 对超长文本会自动处理，但仍需分批
        batch_size = 128
        result: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            resp = await client.embeddings.create(
                input=batch, model=self._openai_embedding_model
            )
            batch_result = [d.embedding for d in resp.data]
            result.extend(batch_result)
        # 探测维度
        if self._vector_size is None and result:
            self._vector_size = len(result[0])
        return result


# ============================================================
# 混合检索器
# ============================================================
@dataclass
class RAGRetrieveResult:
    """检索结果（对外统一结构）"""
    hits: list[SearchHit]
    from_cache: bool = False

    @property
    def context_text(self) -> str:
        """把多条命中合成上下文，方便拼进 Prompt"""
        parts = []
        for i, h in enumerate(self.hits, 1):
            title = h.metadata.get("title") or f"片段{i}"
            source = h.metadata.get("source_type") or "unknown"
            parts.append(f"【{title}】(来源:{source})\n{h.text}")
        return "\n\n".join(parts)


class Retriever:
    """混合检索器：向量召回 → 关键词重排 → 缓存读写"""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedding: Optional[EmbeddingProvider] = None,
        cache: Optional[RAGCache] = None,
    ) -> None:
        self.store = vector_store or get_vector_store()
        self.embedding = embedding or get_embedding_provider()
        self.cache = cache or get_rag_cache()
        self.settings = get_settings()

    async def ensure_ready(self) -> None:
        """首次使用前调用，确保向量库和 Embedding 初始化完毕"""
        await self.store.ensure_collection(self.embedding.vector_size)

    # ============================================================
    # 1. 写入文档（入库）
    # ============================================================
    async def ingest(self, points: Sequence[VectorPoint]) -> list[str]:
        """写入向量库（如果 points 没带 embedding 会自动计算）"""
        await self.ensure_ready()
        ids = await self.store.add_documents(
            points,
            embed_fn=self.embedding.encode,
            batch_size=self.settings.EMBEDDING_BATCH_SIZE,
        )
        return ids

    # ============================================================
    # 2. 检索（主入口）
    # ============================================================
    async def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        city: Optional[str] = None,
        category: Optional[str] = None,
        extra_filters: Optional[dict] = None,
        use_cache: bool = True,
    ) -> RAGRetrieveResult:
        if not query.strip():
            return RAGRetrieveResult(hits=[])

        k = top_k or self.settings.RAG_TOP_K

        # ---------- a. 缓存优先 ----------
        if use_cache:
            cached = await self.cache.get(query=query, city=city, category=category)
            if cached is not None:
                logger.debug(f"[RAG] 缓存命中: {query[:30]}")
                return RAGRetrieveResult(hits=cached, from_cache=True)

        # ---------- b. 向量召回 (raw_top_k = k*3 为了重排) ----------
        await self.ensure_ready()
        qv = (await self.embedding.encode([query]))[0]
        filters: dict = {}
        if city:
            filters["city"] = city
        if category:
            filters["category"] = category
        if extra_filters:
            filters.update(extra_filters)

        raw_hits = await self.store.search(
            qv,
            top_k=max(k * 3, k),
            filters=filters or None,
        )
        if not raw_hits:
            return RAGRetrieveResult(hits=[])

        # ---------- c. 关键词重排（BM25-lite）----------
        reranked = self._keyword_rerank(query, raw_hits, k)

        # ---------- d. 写回缓存 ----------
        if use_cache:
            await self.cache.set(query=query, hits=reranked, city=city, category=category)

        return RAGRetrieveResult(hits=reranked, from_cache=False)

    # ============================================================
    # 3. 辅助：基于关键词匹配的轻量重排（BM25 简化版）
    # ============================================================
    @staticmethod
    def _keyword_rerank(query: str, hits: list[SearchHit], k: int) -> list[SearchHit]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return hits[:k]

        # 全局 IDF：在当前候选命中中估算（文档频率 DF）
        df: Counter = Counter()
        for h in hits:
            for tok in set(_tokenize(h.text + " " + str(h.metadata.get("title", "")))):
                df[tok] += 1

        N = max(len(hits), 1)
        scored: list[tuple[float, SearchHit]] = []
        for h in hits:
            text = h.text + " " + str(h.metadata.get("title", ""))
            doc_tokens = _tokenize(text)
            if not doc_tokens:
                scored.append((h.score, h))
                continue
            tf = Counter(doc_tokens)
            doc_len = len(doc_tokens)
            score_kw = 0.0
            for qt in q_tokens:
                if qt not in tf:
                    continue
                import math
                idf = math.log((N - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5) + 1)
                term_tf = tf.get(qt, 0) / doc_len
                score_kw += term_tf * idf
            # 合并分数：向量相似度 (0~1) + 归一化关键词得分（给个相对权重）
            combined = 0.7 * float(h.score) + 0.3 * min(score_kw, 1.0)
            scored.append((combined, h))

        scored.sort(key=lambda x: x[0], reverse=True)
        # 更新 score 字段为合并后分数
        out: list[SearchHit] = []
        for new_score, h in scored[:k]:
            h.score = new_score
            out.append(h)
        return out


# ---------- 工具：简易中英文分词（切词 + 去停用词）----------
_STOPWORDS = set("""
的 了 在 和 是 就 都 而 及 与 或 等 也 还 但 但 并 被 把 让 将
a an the of to in for on with and or is are was were be been
this that these those i you he she it we they me him her us them
""".split())


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    # 中文：按连续 CJK 单字拆分；英文：按标点/空格切词转小写
    tokens: list[str] = []
    buf = ""
    for ch in text:
        cp = ord(ch)
        is_cjk = 0x4E00 <= cp <= 0x9FFF or 0x3040 <= cp <= 0x30FF or 0xAC00 <= cp <= 0xD7AF
        is_alnum = ch.isalnum()
        if is_cjk:
            if buf:
                tokens.append(buf.lower())
                buf = ""
            tokens.append(ch)
        elif is_alnum:
            buf += ch
        else:
            if buf:
                tokens.append(buf.lower())
                buf = ""
    if buf:
        tokens.append(buf.lower())
    return [t for t in tokens if t and t not in _STOPWORDS and len(t) > 0]


# ============================================================
# 单例
# ============================================================
_emb: Optional[EmbeddingProvider] = None
_retriever: Optional[Retriever] = None


def get_embedding_provider() -> EmbeddingProvider:
    global _emb
    if _emb is None:
        _emb = EmbeddingProvider()
    return _emb


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever
