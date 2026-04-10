"""
HuggingFace 新闻采集器
采集 HuggingFace 热门模型和新模型发布信息
"""
from datetime import datetime
from typing import Optional
from loguru import logger

from .base import BaseCollector
from storage.database import NewsItem


class HuggingFaceCollector(BaseCollector):
    """HuggingFace 热门模型采集器"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.trending_url = config.get(
            "trending_models_url",
            "https://huggingface.co/api/trending"
        )

    async def collect(self) -> list[NewsItem]:
        items = []
        
        # 采集热门模型
        trending_items = await self._collect_trending_models()
        items.extend(trending_items)
        
        # 采集最新模型
        new_items = await self._collect_new_models()
        items.extend(new_items)
        
        return items

    async def _collect_trending_models(self) -> list[NewsItem]:
        """通过API获取热门模型"""
        data = await self.fetch_json(self.trending_url)
        if not data:
            return []

        items = []
        models = data if isinstance(data, list) else data.get("models", [])
        
        for model in models[:15]:
            try:
                item = self._parse_model(model)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[HuggingFace] 解析热门模型失败: {e}")
                continue

        return items

    async def _collect_new_models(self) -> list[NewsItem]:
        """获取最新发布的模型"""
        # 使用 HuggingFace API 搜索最新模型
        url = "https://huggingface.co/api/models"
        params = {
            "sort": "lastModified",
            "direction": "-1",
            "limit": "15",
        }
        
        data = await self.fetch_json(url, params=params)
        if not data:
            return []

        items = []
        models = data if isinstance(data, list) else []
        
        for model in models[:15]:
            try:
                item = self._parse_model(model)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"[HuggingFace] 解析新模型失败: {e}")
                continue

        return items

    def _parse_model(self, model: dict) -> Optional[NewsItem]:
        """解析模型数据"""
        if isinstance(model, str):
            model_id = model
            model_data = {}
        elif isinstance(model, dict):
            model_id = model.get("id", model.get("modelId", ""))
            model_data = model
        else:
            return None

        if not model_id:
            return None

        # 构建URL
        full_url = f"https://huggingface.co/{model_id}"

        # 获取模型信息
        author = model_id.split("/")[0] if "/" in model_id else "Unknown"
        
        # 获取描述
        description = model_data.get("description", "")
        pipeline_tag = model_data.get("pipeline_tag", "")
        tags = model_data.get("tags", [])
        
        # 构建摘要
        summary_parts = []
        if pipeline_tag:
            summary_parts.append(f"任务类型: {pipeline_tag}")
        if tags:
            relevant_tags = [t for t in tags[:5] if not t.startswith("region:")]
            if relevant_tags:
                summary_parts.append(f"标签: {', '.join(relevant_tags)}")
        summary = " | ".join(summary_parts) if summary_parts else f"by {author}"

        # 获取修改时间
        last_modified = model_data.get("lastModified", model_data.get("createdAt", ""))

        # 获取下载量和点赞
        downloads = model_data.get("downloads", 0)
        likes = model_data.get("likes", 0)
        
        # 生成更友好的标题
        model_name = model_id.split("/")[-1] if "/" in model_id else model_id
        title = f"🔧 {model_id}"
        if downloads:
            title += f" ({self._format_number(downloads)} 下载)"
        
        return NewsItem(
            title=title,
            url=full_url,
            source="HuggingFace",
            published_date=last_modified if last_modified else None,
            summary=summary[:300] if summary else None,
            category="模型发布",
        )

    @staticmethod
    def _format_number(n: int) -> str:
        """格式化数字"""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)