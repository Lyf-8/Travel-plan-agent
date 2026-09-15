"""外部百科抓取工具（RAG 渐进积累策略的补充：缓存优先，外部搜索兜底）

目标：
    当用户问"故宫是何时建成的？"时，本地知识库没命中就调用 Wikipedia / 百度百科接口
    抓取后再回写到本地 RAG 缓存，下次相同查询可直接命中。

为了降低依赖，这里提供两个方案：
    1. 在线抓取：requests + BeautifulSoup 解析任意百科页面简介
    2. Wikipedia OpenSearch API：官方开放接口，免费稳定
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from ..core.exceptions import ToolCallError


WIKIPEDIA_API = "https://zh.wikipedia.org/w/api.php"
WIKIPEDIA_PAGE_PREFIX = "https://zh.wikipedia.org/wiki/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class WikiResult:
    """标准化搜索结果"""
    title: str
    snippet: str                # 简介（首段文本）
    url: str
    source: str                 # wikipedia / baike / generic
    related_terms: list[str] = None  # type: ignore[assignment]


class WikiSearch:
    """百科搜索 & 页面简介抓取"""

    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout

    # ============================================================
    # 1. 主入口：搜索 + 摘要
    # ============================================================
    async def search(
        self,
        query: str,
        limit: int = 5,
        prefer_source: str = "wikipedia",
    ) -> list[WikiResult]:
        """多源搜索：优先维基百科，失败回退通用抓取"""
        results: list[WikiResult] = []
        try:
            if prefer_source == "wikipedia":
                results = await self._wikipedia_search(query, limit=limit)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Wikipedia 搜索失败: {e}")

        if not results:
            # 兜底：尝试用维基标题构造直接简介抓取
            results = await self._fallback_direct_lookup(query)
        return results

    # ============================================================
    # 2. Wikipedia OpenSearch（官方，免费稳定）
    # ============================================================
    async def _wikipedia_search(self, query: str, limit: int = 5) -> list[WikiResult]:
        params = {
            "action": "opensearch",
            "search": query,
            "limit": limit,
            "format": "json",
            "namespace": "0",
        }
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(WIKIPEDIA_API, params=params, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            data = resp.json()
        if len(data) < 4:
            return []
        titles, snippets, urls = data[1], data[2], data[3]
        out: list[WikiResult] = []
        for t, s, u in zip(titles, snippets, urls):
            # 简介经常为空，尝试再抓一次页面首段
            if not s:
                s = await self._fetch_page_intro(url=t)
            out.append(WikiResult(
                title=t,
                snippet=s or "",
                url=u,
                source="wikipedia",
                related_terms=[],
            ))
        return out

    # ============================================================
    # 3. 直接抓页面的第一段介绍
    # ============================================================
    async def _fetch_page_intro(self, url: Optional[str] = None, title: Optional[str] = None) -> str:
        """抓维基百科/百科页面首个 <p> 标签的纯文本"""
        if not url and title:
            url = WIKIPEDIA_PAGE_PREFIX + quote_plus(title)
        if not url:
            return ""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
                html = resp.text
            soup = BeautifulSoup(html, "lxml")
            # 维基百科正文在 .mw-parser-output 下的第一个有效 <p>
            body = soup.select_one(".mw-parser-output") or soup.body or soup
            paragraphs = body.find_all("p")
            for p in paragraphs:
                text = _clean_text(p.get_text())
                if len(text) >= 40:   # 跳过太短的元信息段落
                    return text
        except Exception as e:  # noqa: BLE001
            logger.debug(f"抓取页面简介失败 {url}: {e}")
        return ""

    # ============================================================
    # 4. 兜底：直接按词条猜测维基标题，抓页面
    # ============================================================
    async def _fallback_direct_lookup(self, query: str) -> list[WikiResult]:
        # 常见城市+景点组合，尝试直接标题查询
        intro = await self._fetch_page_intro(title=query)
        if not intro:
            return []
        url = WIKIPEDIA_PAGE_PREFIX + quote_plus(query)
        return [WikiResult(title=query, snippet=intro, url=url, source="wikipedia", related_terms=[])]


def _clean_text(text: str) -> str:
    text = re.sub(r"\[\d+\]", "", text)          # 去掉 [1] 引用标注
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


_instance: Optional[WikiSearch] = None


def get_wiki_search() -> WikiSearch:
    global _instance
    if _instance is None:
        _instance = WikiSearch()
    return _instance
