"""
OpenAI 新闻采集器
采集 OpenAI 官方博客和发布页面
"""
import re
from datetime import datetime
from typing import Optional
from loguru import logger

from .base import BaseCollector
from storage.database import NewsItem


class OpenAICollector(BaseCollector):
    """OpenAI 官方新闻采集器"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.urls = config.get("urls", [
            "https://openai.com/blog",
            "https://openai.com/research",
        ])

    async def collect(self) -> list[NewsItem]:
        items = []
        for url in self.urls:
            page_items = await self._collect_page(url)
            items.extend(page_items)
        return items

    async def _collect_page(self, url: str) -> list[NewsItem]:
        html = await self.fetch_page(url)
        if not html:
            return []

        soup = self.parse_html(html)
        items = []

        # 尝试多种选择器以适应网页结构变化
        articles = (
            soup.select("article") or
            soup.select("a[href*='/blog/']") or
            soup.select("[class*='post']") or
            soup.select("[class*='card']") or
            soup.select("[class*='item']")
        )

        seen_urls = set()
        for article in articles[:15]:  # 限制每页最多15条
            try:
                item = self._parse_article(article, seen_urls)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[OpenAI] 解析文章失败: {e}")
                continue

        return items

    def _parse_article(self, element, seen_urls: set) -> Optional[NewsItem]:
        # 尝试获取链接
        link_tag = element.find("a", href=True) if element.name != "a" else element
        if not link_tag:
            return None

        href = link_tag.get("href", "")
        if not href or href in seen_urls:
            return None

        # 构建完整URL
        if href.startswith("/"):
            full_url = f"https://openai.com{href}"
        elif href.startswith("http"):
            full_url = href
        else:
            return None

        seen_urls.add(href)

        # 获取标题
        title_tag = (
            element.find(["h1", "h2", "h3", "h4"]) or
            element.find("[class*='title']") or
            link_tag
        )
        title = self.clean_text(title_tag.get_text()) if title_tag else ""

        if not title or len(title) < 5:
            return None

        # 获取摘要
        summary_tag = element.find("p")
        summary = self.clean_text(summary_tag.get_text()) if summary_tag else None

        # 获取日期
        date_tag = (
            element.find("time") or
            element.find("[class*='date']") or
            element.find("[class*='time']")
        )
        published_date = None
        if date_tag:
            datetime_attr = date_tag.get("datetime")
            if datetime_attr:
                published_date = str(datetime_attr)
            else:
                published_date = self.clean_text(date_tag.get_text())

        return NewsItem(
            title=title,
            url=full_url,
            source="OpenAI",
            published_date=published_date,
            summary=summary[:300] if summary else None,
        )