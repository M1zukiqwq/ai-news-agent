"""
采集器基类 - 定义统一接口和通用工具方法
"""
import asyncio
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from storage.database import NewsItem


class BaseCollector(ABC):
    """采集器抽象基类"""

    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", self.__class__.__name__)
        self.enabled = config.get("enabled", True)
        self.max_age_days = config.get("max_age_days", 7)  # 默认只保留7天内的新闻
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        """获取异步HTTP客户端（懒加载）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
                }
            )
        return self._client

    async def close(self):
        """关闭HTTP客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @abstractmethod
    async def collect(self) -> list[NewsItem]:
        """采集新闻，返回标准化新闻条目列表"""
        pass

    async def fetch_page(self, url: str) -> Optional[str]:
        """获取网页HTML内容"""
        try:
            client = await self.get_client()
            response = await client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as e:
            logger.warning(f"[{self.name}] 获取页面失败 {url}: {e}")
            return None

    async def fetch_json(self, url: str, params: dict = None) -> Optional[dict]:
        """获取JSON API响应"""
        try:
            client = await self.get_client()
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"[{self.name}] 获取JSON失败 {url}: {e}")
            return None

    def parse_html(self, html: str) -> BeautifulSoup:
        """解析HTML"""
        return BeautifulSoup(html, "lxml")

    def clean_text(self, text: str) -> str:
        """清理文本：去除多余空白"""
        if not text:
            return ""
        return " ".join(text.split()).strip()

    def is_recent_news(self, published_date: Optional[str]) -> bool:
        """
        检查新闻日期是否在 max_age_days 天内
        支持多种日期格式，无法解析时默认返回 True（保留）
        """
        if not published_date:
            return True  # 没有日期的新闻保留

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self.max_age_days)

        date = self._parse_date(published_date)
        if date is None:
            return True  # 解析失败的新闻保留

        # 确保 timezone-aware 比较
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)

        is_recent = date >= cutoff
        if not is_recent:
            logger.debug(f"[{self.name}] 跳过过期新闻 ({published_date})")
        return is_recent

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """尝试解析多种日期格式"""
        if not date_str:
            return None

        date_str = date_str.strip()

        # 常见日期格式列表
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",       # ISO 8601 with timezone
            "%Y-%m-%dT%H:%M:%S.%f%z",    # ISO 8601 with microseconds
            "%Y-%m-%dT%H:%M:%S",         # ISO 8601 without timezone
            "%Y-%m-%dT%H:%M:%S.%f",      # ISO 8601 with microseconds, no tz
            "%Y-%m-%d %H:%M:%S",         # Common datetime
            "%Y-%m-%d",                   # Date only
            "%a, %d %b %Y %H:%M:%S %z",  # RFC 2822 (RSS standard)
            "%a, %d %b %Y %H:%M:%S",     # RFC 2822 without timezone
            "%d %b %Y",                   # e.g., "10 Apr 2026"
            "%B %d, %Y",                  # e.g., "April 10, 2026"
            "%b %d, %Y",                  # e.g., "Apr 10, 2026"
            "%Y/%m/%d",                   # e.g., "2026/04/10"
            "%m/%d/%Y",                   # e.g., "04/10/2026"
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        # 尝试提取日期部分
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
        if date_match:
            try:
                return datetime.strptime(date_match.group(1), "%Y-%m-%d")
            except ValueError:
                pass

        logger.debug(f"[{self.name}] 无法解析日期: {date_str}")
        return None

    def filter_recent(self, items: list[NewsItem]) -> list[NewsItem]:
        """过滤出最近N天的新闻"""
        before = len(items)
        filtered = [item for item in items if self.is_recent_news(item.published_date)]
        after = len(filtered)
        if before > after:
            logger.info(f"[{self.name}] 日期过滤: {before} → {after} 条（跳过 {before - after} 条过期新闻）")
        return filtered

    async def safe_collect(self) -> list[NewsItem]:
        """安全的采集执行，自动捕获异常 + 日期过滤"""
        if not self.enabled:
            logger.info(f"[{self.name}] 采集器已禁用，跳过")
            return []
        try:
            logger.info(f"[{self.name}] 开始采集...")
            items = await self.collect()
            # 日期过滤
            items = self.filter_recent(items)
            logger.info(f"[{self.name}] 采集完成，获取 {len(items)} 条近期新闻")
            return items
        except Exception as e:
            logger.error(f"[{self.name}] 采集异常: {e}", exc_info=True)
            return []
