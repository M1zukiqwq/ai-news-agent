"""
综合AI新闻采集器
通过 RSS Feed 采集 AI 行业新闻
"""
from datetime import datetime
from typing import Optional
import feedparser
from loguru import logger

from .base import BaseCollector
from storage.database import NewsItem


class GeneralNewsCollector(BaseCollector):
    """综合 AI 新闻 RSS 采集器"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.feeds = config.get("feeds", [
            "https://techcrunch.com/category/artificial-intelligence/feed/",
            "https://www.artificialintelligence-news.com/feed/",
        ])

    async def collect(self) -> list[NewsItem]:
        items = []
        for feed_url in self.feeds:
            feed_items = await self._collect_feed(feed_url)
            items.extend(feed_items)
        return items

    async def _collect_feed(self, feed_url: str) -> list[NewsItem]:
        """解析 RSS Feed"""
        try:
            # 使用 httpx 获取内容，再用 feedparser 解析
            client = await self.get_client()
            response = await client.get(feed_url)
            response.raise_for_status()

            # feedparser 解析
            feed = feedparser.parse(response.text)

            if not feed.entries:
                logger.warning(f"[综合资讯] Feed无内容: {feed_url}")
                return []

            items = []
            for entry in feed.entries[:10]:  # 每个Feed最多10条
                try:
                    item = self._parse_entry(entry, feed.feed.get("title", ""))
                    if item:
                        items.append(item)
                except Exception as e:
                    logger.debug(f"[综合资讯] 解析条目失败: {e}")
                    continue

            return items

        except Exception as e:
            logger.warning(f"[综合资讯] 获取Feed失败 {feed_url}: {e}")
            return []

    def _parse_entry(self, entry, feed_title: str) -> Optional[NewsItem]:
        """解析 RSS 条目"""
        title = entry.get("title", "")
        if not title:
            return None

        url = entry.get("link", "")
        if not url:
            return None

        # 获取摘要
        summary = ""
        if hasattr(entry, "summary"):
            summary = entry.summary
        elif hasattr(entry, "description"):
            summary = entry.description
        # 清理HTML标签
        summary = self._clean_html(summary)
        summary = self.clean_text(summary)

        # 获取发布日期
        published_date = None
        if hasattr(entry, "published"):
            published_date = entry.published
        elif hasattr(entry, "updated"):
            published_date = entry.updated

        # 判断来源
        source = feed_title if feed_title else "AI News"
        if "techcrunch" in url.lower():
            source = "TechCrunch"
        elif "artificialintelligence-news" in url.lower():
            source = "AI News"

        return NewsItem(
            title=title,
            url=url,
            source=source,
            published_date=published_date,
            summary=summary[:500] if summary else None,
        )

    @staticmethod
    def _clean_html(html: str) -> str:
        """简单清理HTML标签"""
        import re
        clean = re.sub(r'<[^>]+>', ' ', html)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()