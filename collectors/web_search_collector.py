"""
联网搜索采集器
通过搜索引擎实时搜索最新AI新闻，支持 Google News、Bing News 等
"""
import re
from datetime import datetime
from typing import Optional
from loguru import logger

from .base import BaseCollector
from storage.database import NewsItem


class WebSearchCollector(BaseCollector):
    """联网搜索采集器 - 通过搜索引擎获取最新AI新闻"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.queries = config.get("queries", [
            "AI model release 2026",
            "artificial intelligence latest news",
            "new AI model launch",
        ])
        self.search_engines = config.get("engines", ["google_news", "bing_news"])

    async def collect(self) -> list[NewsItem]:
        items = []
        for engine in self.search_engines:
            try:
                if engine == "google_news":
                    engine_items = await self._collect_google_news()
                elif engine == "bing_news":
                    engine_items = await self._collect_bing_news()
                else:
                    logger.warning(f"[联网搜索] 未知搜索引擎: {engine}")
                    continue
                items.extend(engine_items)
            except Exception as e:
                logger.warning(f"[联网搜索] {engine} 搜索失败: {e}")

        # 去重（同一URL）
        seen = set()
        unique = []
        for item in items:
            if item.url not in seen:
                seen.add(item.url)
                unique.append(item)

        return unique

    async def _collect_google_news(self) -> list[NewsItem]:
        """通过 Google News RSS 搜索"""
        items = []
        for query in self.queries:
            try:
                # Google News RSS feed (无需API Key)
                rss_url = f"https://news.google.com/rss/search?q={query}+when:7d&hl=en-US&gl=US&ceid=US:en"
                html = await self.fetch_page(rss_url)
                if not html:
                    continue

                items.extend(self._parse_rss_results(html, "Google News"))
            except Exception as e:
                logger.debug(f"[联网搜索] Google News 查询失败 '{query}': {e}")

        logger.info(f"[联网搜索] Google News: {len(items)} 条")
        return items

    async def _collect_bing_news(self) -> list[NewsItem]:
        """通过 Bing News 搜索"""
        items = []
        for query in self.queries:
            try:
                # Bing News 搜索
                search_url = f"https://www.bing.com/news/search?q={query}&qft=interval%3d%227%22&form=PTFTNR"
                html = await self.fetch_page(search_url)
                if not html:
                    continue

                items.extend(self._parse_bing_results(html))
            except Exception as e:
                logger.debug(f"[联网搜索] Bing News 查询失败 '{query}': {e}")

        logger.info(f"[联网搜索] Bing News: {len(items)} 条")
        return items

    def _parse_rss_results(self, xml_content: str, source_name: str) -> list[NewsItem]:
        """解析RSS搜索结果"""
        items = []
        try:
            import feedparser
            feed = feedparser.parse(xml_content)
            for entry in feed.entries[:15]:
                title = entry.get("title", "")
                url = entry.get("link", "")
                if not title or not url:
                    continue

                summary = ""
                if hasattr(entry, "summary"):
                    summary = self._clean_html(entry.summary)
                    summary = self.clean_text(summary)[:500]

                published_date = None
                if hasattr(entry, "published"):
                    published_date = entry.published
                elif hasattr(entry, "updated"):
                    published_date = entry.updated

                items.append(NewsItem(
                    title=title,
                    url=url,
                    source=source_name,
                    published_date=published_date,
                    summary=summary or None,
                ))
        except Exception as e:
            logger.debug(f"[联网搜索] RSS解析失败: {e}")

        return items

    def _parse_bing_results(self, html: str) -> list[NewsItem]:
        """解析 Bing News HTML 结果"""
        soup = self.parse_html(html)
        items = []

        # Bing News 卡片
        cards = (
            soup.select(".news-card") or
            soup.select("[class*='card']") or
            soup.select(".algocore")
        )

        seen_urls = set()
        for card in cards[:20]:
            try:
                link_tag = card.find("a", href=True)
                if not link_tag:
                    continue

                url = link_tag.get("href", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                title_tag = card.find(["h2", "h3", "h4"]) or link_tag
                title = self.clean_text(title_tag.get_text()) if title_tag else ""
                if not title or len(title) < 5:
                    continue

                summary_tag = card.find("p")
                summary = self.clean_text(summary_tag.get_text())[:500] if summary_tag else None

                # Bing 有时在 snippet 中包含日期
                date_tag = card.find("[class*='date']") or card.find("span", class_="news-digest")
                published_date = None
                if date_tag:
                    published_date = self.clean_text(date_tag.get_text())

                items.append(NewsItem(
                    title=title,
                    url=url,
                    source="Bing News",
                    published_date=published_date,
                    summary=summary,
                ))
            except Exception as e:
                logger.debug(f"[联网搜索] Bing解析失败: {e}")

        return items

    @staticmethod
    def _clean_html(html: str) -> str:
        """清理HTML标签"""
        clean = re.sub(r'<[^>]+>', ' ', html)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()