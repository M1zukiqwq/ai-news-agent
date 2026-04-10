"""
中国AI厂商新闻采集器
采集通义千问、豆包、GLM、Kimi、DeepSeek、百度文心、MiniMax、百川等中国AI厂商的最新动态
"""
import re
from datetime import datetime
from typing import Optional
from loguru import logger

from .base import BaseCollector
from storage.database import NewsItem


# 各厂商配置
CHINA_AI_SOURCES = {
    "qwen": {
        "name": "通义千问",
        "urls": [
            "https://qwenlm.github.io/blog/",
        ],
        "base_url": "https://qwenlm.github.io",
    },
    "doubao": {
        "name": "豆包",
        "urls": [
            "https://team.doubao.com/",
        ],
        "base_url": "https://team.doubao.com",
    },
    "glm": {
        "name": "智谱GLM",
        "urls": [
            "https://zhipu.ai/news",
            "https://zhipu.ai/product",
        ],
        "base_url": "https://zhipu.ai",
    },
    "kimi": {
        "name": "Kimi",
        "urls": [
            "https://platform.moonshot.cn/docs",
        ],
        "base_url": "https://platform.moonshot.cn",
    },
    "deepseek": {
        "name": "DeepSeek",
        "urls": [
            "https://api-doc.deepseek.com/",
        ],
        "base_url": "https://api-doc.deepseek.com",
    },
    "ernie": {
        "name": "百度文心",
        "urls": [
            "https://yiyan.baidu.com/",
        ],
        "base_url": "https://yiyan.baidu.com",
    },
    "minimax": {
        "name": "MiniMax",
        "urls": [
            "https://www.minimaxi.com/",
        ],
        "base_url": "https://www.minimaxi.com",
    },
    "baichuan": {
        "name": "百川智能",
        "urls": [
            "https://www.baichuan-ai.com/",
        ],
        "base_url": "https://www.baichuan-ai.com",
    },
}


class ChinaAICollector(BaseCollector):
    """中国AI厂商新闻采集器"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.sources_config = config.get("sources", CHINA_AI_SOURCES)
        # 允许配置中指定启用的厂商
        self.enabled_sources = config.get("enabled_sources", list(CHINA_AI_SOURCES.keys()))

    async def collect(self) -> list[NewsItem]:
        items = []
        for source_key, source_info in self.sources_config.items():
            if source_key not in self.enabled_sources:
                continue
            try:
                source_items = await self._collect_source(source_key, source_info)
                items.extend(source_items)
                logger.debug(f"[中国AI] {source_info['name']}: 采集到 {len(source_items)} 条")
            except Exception as e:
                logger.warning(f"[中国AI] {source_info['name']} 采集失败: {e}")
        return items

    async def _collect_source(self, source_key: str, source_info: dict) -> list[NewsItem]:
        """采集单个厂商的信息"""
        items = []
        for url in source_info.get("urls", []):
            page_items = await self._collect_page(url, source_info)
            items.extend(page_items)
        return items

    async def _collect_page(self, url: str, source_info: dict) -> list[NewsItem]:
        """采集单个页面"""
        html = await self.fetch_page(url)
        if not html:
            return []

        soup = self.parse_html(html)
        items = []

        source_name = source_info.get("name", "中国AI")
        base_url = source_info.get("base_url", "")

        # 通用文章选择器
        articles = (
            soup.select("article") or
            soup.select("[class*='post']") or
            soup.select("[class*='card']") or
            soup.select("[class*='item']") or
            soup.select("[class*='blog']") or
            soup.select("[class*='news']") or
            soup.select("[class*='update']") or
            soup.select("[class*='release']") or
            soup.select("[class*='entry']") or
            soup.select("a[href]")
        )

        seen_urls = set()
        for article in articles[:15]:
            try:
                item = self._parse_article(article, seen_urls, source_name, base_url)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[{source_name}] 解析文章失败: {e}")
                continue

        return items

    def _parse_article(self, element, seen_urls: set, source_name: str, base_url: str) -> Optional[NewsItem]:
        """解析文章元素"""
        # 获取链接
        link_tag = element.find("a", href=True) if element.name != "a" else element
        if not link_tag:
            return None

        href = link_tag.get("href", "")
        if not href or href in seen_urls:
            return None

        # 构建完整URL
        if href.startswith("/"):
            full_url = f"{base_url}{href}"
        elif href.startswith("http"):
            full_url = href
        else:
            return None

        # 过滤非内容链接
        skip_patterns = ["javascript:", "mailto:", "#", ".css", ".js", ".png", ".jpg", ".svg"]
        if any(href.startswith(p) for p in skip_patterns):
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
            source=source_name,
            published_date=published_date,
            summary=summary[:300] if summary else None,
        )