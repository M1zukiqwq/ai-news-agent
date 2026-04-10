"""
SQLite 存储模块 - 管理新闻历史记录和去重
"""
import sqlite3
import hashlib
import os
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger


@dataclass
class NewsItem:
    """标准化新闻条目"""
    title: str
    url: str
    source: str  # 来源厂商/平台
    published_date: Optional[str] = None
    summary: Optional[str] = None
    original_content: Optional[str] = None
    category: Optional[str] = None  # 分类：模型发布、产品更新、研究论文等
    importance: str = "normal"  # high, normal, low
    ai_summary: Optional[str] = None  # Gemini 生成的中文摘要
    collected_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def content_hash(self) -> str:
        """生成内容唯一标识，用于去重"""
        content = f"{self.title}:{self.url}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()


class Database:
    """SQLite 数据库管理"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        # 确保目录存在
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else '.', exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    published_date TEXT,
                    summary TEXT,
                    original_content TEXT,
                    category TEXT,
                    importance TEXT DEFAULT 'normal',
                    ai_summary TEXT,
                    content_hash TEXT UNIQUE NOT NULL,
                    collected_at TEXT NOT NULL,
                    sent_at TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_hash 
                ON news(content_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_date 
                ON news(collected_at)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS send_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    send_date TEXT NOT NULL,
                    news_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            logger.info(f"数据库初始化完成: {self.db_path}")

    def is_duplicate(self, item: NewsItem) -> bool:
        """检查新闻是否已存在（去重）"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM news WHERE content_hash = ?",
                (item.content_hash,)
            )
            return cursor.fetchone() is not None

    def save_news(self, item: NewsItem) -> bool:
        """保存新闻条目，返回是否为新条目"""
        if self.is_duplicate(item):
            logger.debug(f"跳过重复新闻: {item.title[:50]}...")
            return False

        with self._get_conn() as conn:
            try:
                conn.execute("""
                    INSERT INTO news (title, url, source, published_date, summary,
                                     original_content, category, importance, ai_summary,
                                     content_hash, collected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.title, item.url, item.source, item.published_date,
                    item.summary, item.original_content, item.category,
                    item.importance, item.ai_summary, item.content_hash,
                    item.collected_at
                ))
                logger.info(f"保存新闻: [{item.source}] {item.title[:50]}...")
                return True
            except sqlite3.IntegrityError:
                logger.debug(f"重复新闻（并发插入）: {item.title[:50]}...")
                return False

    def save_news_batch(self, items: list[NewsItem]) -> int:
        """批量保存新闻，返回新增数量"""
        new_count = 0
        for item in items:
            if self.save_news(item):
                new_count += 1
        return new_count

    def update_ai_summary(self, content_hash: str, ai_summary: str, category: str, importance: str):
        """更新AI摘要和分类"""
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE news SET ai_summary = ?, category = ?, importance = ?
                WHERE content_hash = ?
            """, (ai_summary, category, importance, content_hash))

    def get_unsent_news(self, date: Optional[str] = None) -> list[NewsItem]:
        """获取未发送的新闻"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT * FROM news 
                WHERE sent_at IS NULL 
                AND date(collected_at) >= date(?)
                ORDER BY 
                    CASE importance 
                        WHEN 'high' THEN 1 
                        WHEN 'normal' THEN 2 
                        WHEN 'low' THEN 3 
                    END,
                    collected_at DESC
            """, (date,))
            rows = cursor.fetchall()

        return [self._row_to_item(row) for row in rows]

    def mark_as_sent(self, items: list[NewsItem]):
        """标记新闻为已发送"""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            for item in items:
                conn.execute(
                    "UPDATE news SET sent_at = ? WHERE content_hash = ?",
                    (now, item.content_hash)
                )

    def log_send(self, news_count: int, status: str, error_message: Optional[str] = None):
        """记录发送日志"""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO send_logs (send_date, news_count, status, error_message)
                VALUES (?, ?, ?, ?)
            """, (datetime.now().isoformat(), news_count, status, error_message))

    def cleanup_old_news(self, days: int = 30):
        """清理旧数据"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            result = conn.execute(
                "DELETE FROM news WHERE collected_at < ?",
                (cutoff,)
            )
            logger.info(f"清理了 {result.rowcount} 条超过 {days} 天的旧新闻")

    def _row_to_item(self, row: sqlite3.Row) -> NewsItem:
        """将数据库行转换为 NewsItem"""
        return NewsItem(
            title=row['title'],
            url=row['url'],
            source=row['source'],
            published_date=row['published_date'],
            summary=row['summary'],
            original_content=row['original_content'],
            category=row['category'],
            importance=row['importance'],
            ai_summary=row['ai_summary'],
            collected_at=row['collected_at'],
        )