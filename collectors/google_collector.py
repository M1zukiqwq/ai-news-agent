"""
Google / DeepMind 新闻采集器
采集 Google AI Blog 和 DeepMind Blog
"""
from typing import Optional
from loguru import logger

from .base import BaseCollector
from storage.database import NewsItem


class GoogleCollector(BaseCollector):
    """Google / DeepMind 新闻采集器"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.urls = config.get("urls", [
            "https://blog.google/technology/ai/",
            "https://deepmind.google/blog/",
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

        # 通用文章选择器
        articles = (
            soup.select("article") or
            soup.select("a[href*='/blog/']") or
            soup.select("[class*='post']") or
            soup.select("[class*='card']") or
            soup.select("[class*='item']") or
            soup.select("[class*='feed'] > div") or
            soup.select("[class*='article']")
        )

        seen_urls = set()
        for article in articles[:15]:
            try:
                item = self._parse_article(article, url, seen_urls)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[Google] 解析文章失败: {e}")
                continue

        return items

    def _parse_article(self, element, base_url: str, seen_urls: set) -> Optional[NewsItem]:
        link_tag = element.find("a", href=True) if element.name != "a" else element
        if not link_tag:
            return None

        href = link_tag.get("href", "")
        if not href or href in seen_urls:
            return None

        # 构建完整URL
        if href.startswith("/"):
            if "deepmind" in base_url:
                full_url = f"https://deepmind.google{href}"
            else:
                full_url = f"https://blog.google{href}"
        elif href.startswith("http"):
            full_url = href
        else:
            return None

        seen_urls.add(href)

        # 获取标题
        title_tag = (
            element.find(["h1", "h2", "h3", "h4"]) or
            element.find("[class*='title']") or
            element.find("[class*='headline']") or
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

        # 判断来源
        source = "DeepMind" if "deepmind" in full_url else "Google AI"

        return NewsItem(
            title=title,
            url=full_url,
            source=source,
            published_date=published_date,
            summary=summary[:300] if summary else None,
        )