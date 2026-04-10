"""
新闻处理器
使用 AI 对采集到的新闻进行去重、摘要、分类和重要度评估
支持并发批次处理以加速
确保采集数量和推送数量一致
"""
import asyncio
import json
from typing import Optional
from loguru import logger

from .gemini_client import GeminiClient
from storage.database import NewsItem, Database


SYSTEM_PROMPT = """你是一个专业的AI行业新闻分析师。你的任务是：
1. 为AI相关新闻生成简洁的中文摘要（每条2-3句话）
2. 对新闻进行分类
3. 评估新闻的重要程度

分类选项：
- 模型发布：新的AI模型发布或更新
- 产品更新：AI产品功能更新或新功能
- 研究论文：重要的AI研究突破或论文
- 行业动态：公司收购、融资、合作等
- 开源项目：开源AI工具、框架发布
- 政策法规：AI相关的政策法规变化
- 其他：不属于以上类别的AI新闻

重要程度：
- high：重大模型发布、重大技术突破、影响行业的大事件
- normal：一般性更新、产品改进
- low：次要新闻、常规更新

请严格按照JSON格式返回结果。"""


class NewsProcessor:
    """新闻智能处理器"""

    def __init__(self, gemini_client: GeminiClient, database: Database):
        self.gemini = gemini_client
        self.db = database

    async def process_items(self, items: list[NewsItem]) -> list[NewsItem]:
        """
        批量处理新闻条目：
        1. 数据库去重
        2. 保存到数据库
        3. 生成AI摘要和分类
        确保每条新闻都被保留，AI处理失败时使用原始摘要
        """
        if not items:
            logger.info("没有需要处理的新闻")
            return []

        total_collected = len(items)
        logger.info(f"📊 开始处理: 共采集 {total_collected} 条原始新闻")

        # 第一步：去重并保存新条目
        new_items = []
        duplicate_count = 0
        for item in items:
            if not self.db.is_duplicate(item):
                if self.db.save_news(item):
                    new_items.append(item)
            else:
                duplicate_count += 1

        logger.info(f"📊 去重结果: {duplicate_count} 条重复, {len(new_items)} 条新新闻")

        if not new_items:
            logger.info("所有新闻均为重复，无需处理")
            return []

        logger.info(f"📊 开始为 {len(new_items)} 条新闻生成AI摘要...")

        # 第二步：并发批量生成AI摘要
        # 关键：确保每条新闻都被保留，即使AI处理失败
        processed_items = []
        batch_size = 10  # 每批处理10条
        max_concurrent = 3  # 最多3个并发请求

        # 创建所有批次
        batches = [
            new_items[i:i + batch_size]
            for i in range(0, len(new_items), batch_size)
        ]

        logger.info(f"📊 分为 {len(batches)} 批处理（每批最多 {batch_size} 条，并发 {max_concurrent}）")

        # 使用信号量控制并发数
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_semaphore(batch, batch_idx):
            async with semaphore:
                logger.info(f"📊 处理第 {batch_idx + 1}/{len(batches)} 批（{len(batch)} 条）...")
                result = await self._process_batch(batch)
                logger.info(f"📊 第 {batch_idx + 1}/{len(batches)} 批完成，返回 {len(result)} 条")
                return result

        # 并发执行所有批次
        tasks = [
            process_with_semaphore(batch, idx)
            for idx, batch in enumerate(batches)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 合并结果 — 即使异常也尽量保留
        failed_batches = 0
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"📊 第 {idx + 1} 批处理异常: {result}")
                # 异常时仍然保留原始条目
                fallback_items = batches[idx]
                for item in fallback_items:
                    if not item.ai_summary:
                        item.ai_summary = item.summary or "摘要生成失败"
                    if not item.category:
                        item.category = "其他"
                processed_items.extend(fallback_items)
                failed_batches += 1
            elif isinstance(result, list):
                processed_items.extend(result)

        ai_success = sum(
            1 for item in processed_items 
            if item.ai_summary and item.ai_summary != "摘要生成失败"
        )
        logger.info(
            f"📊 AI处理完成: 输入 {len(new_items)} 条, 输出 {len(processed_items)} 条, "
            f"AI摘要成功 {ai_success} 条, 失败 {len(processed_items) - ai_success} 条, "
            f"异常批次 {failed_batches}/{len(batches)}"
        )

        # 确保数量一致：如果出现数量差异，用原始条目补充
        if len(processed_items) < len(new_items):
            missing_count = len(new_items) - len(processed_items)
            logger.warning(f"📊 发现 {missing_count} 条新闻在处理中丢失，正在恢复...")
            processed_urls = {item.url for item in processed_items}
            for item in new_items:
                if item.url not in processed_urls:
                    if not item.ai_summary:
                        item.ai_summary = item.summary or "摘要生成失败"
                    if not item.category:
                        item.category = "其他"
                    processed_items.append(item)
            logger.info(f"📊 恢复完成，最终 {len(processed_items)} 条新闻")

        return processed_items

    async def _process_batch(self, items: list[NewsItem]) -> list[NewsItem]:
        """
        批量生成AI摘要
        确保返回的条目数量与输入一致
        """
        if not items:
            return []

        # 构建提示词
        news_list = []
        for idx, item in enumerate(items, 1):
            news_info = f"{idx}. 标题: {item.title}\n"
            news_info += f"   来源: {item.source}\n"
            if item.summary:
                news_info += f"   原始摘要: {item.summary[:200]}\n"
            if item.url:
                news_info += f"   链接: {item.url}\n"
            news_list.append(news_info)

        prompt = f"""分析以下{len(items)}条AI新闻，生成中文摘要、分类和重要程度。

{"".join(news_list)}

严格返回JSON数组，不要多余文字：
[{{"index":1,"ai_summary":"2-3句中文摘要","category":"分类","importance":"high/normal/low"}}]"""

        try:
            result = await self.gemini.generate_json(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                max_tokens=2048,
            )

            # 解析结果
            if isinstance(result, dict) and "raw_response" in result:
                logger.warning(f"AI返回非JSON格式，{len(items)} 条新闻使用原始摘要")
                for item in items:
                    if not item.ai_summary:
                        item.ai_summary = item.summary or "摘要生成失败"
                    if not item.category:
                        item.category = "其他"
                return items

            ai_results = result if isinstance(result, list) else [result]

            # 构建索引映射，处理AI可能返回的数量不一致
            matched = 0
            for result_item in ai_results:
                idx = result_item.get("index", 0) - 1
                if 0 <= idx < len(items):
                    item = items[idx]
                    item.ai_summary = result_item.get("ai_summary", item.summary)
                    item.category = result_item.get("category", "其他")
                    item.importance = result_item.get("importance", "normal")
                    matched += 1

                    # 更新数据库
                    self.db.update_ai_summary(
                        content_hash=item.content_hash,
                        ai_summary=item.ai_summary,
                        category=item.category,
                        importance=item.importance,
                    )

            # 为AI没有返回结果的条目设置默认值
            for item in items:
                if not item.ai_summary:
                    item.ai_summary = item.summary or "摘要生成失败"
                    logger.debug(f"新闻缺少AI摘要: {item.title[:40]}...")
                if not item.category:
                    item.category = "其他"

            if matched < len(items):
                logger.warning(
                    f"AI返回 {len(ai_results)} 条结果，期望 {len(items)} 条，"
                    f"{len(items) - matched} 条使用原始摘要"
                )

            logger.info(f"成功处理 {len(items)} 条新闻（AI匹配 {matched} 条）")

        except Exception as e:
            logger.error(f"批量生成AI摘要失败: {e}，{len(items)} 条新闻使用原始摘要")
            # 失败时仍然返回所有原始条目
            for item in items:
                if not item.ai_summary:
                    item.ai_summary = item.summary or "摘要生成失败"
                if not item.category:
                    item.category = "其他"

        return items

    async def generate_daily_summary(self, items: list[NewsItem]) -> str:
        """生成每日总结"""
        if not items:
            return "今日暂无重要AI新闻。"

        # 构建新闻概览
        news_overview = "\n".join([
            f"- [{item.source}] {item.title} ({item.importance})"
            for item in items[:30]
        ])

        prompt = f"""用3-5句中文总结今日AI新闻重点：

{news_overview}

直接输出总结文字。"""

        try:
            summary = await self.gemini.generate(prompt=prompt, max_tokens=512)
            return summary.strip()
        except Exception as e:
            logger.error(f"生成每日总结失败: {e}")
            return f"今日共收集到 {len(items)} 条AI相关新闻。"

    def group_by_source(self, items: list[NewsItem]) -> dict[str, list[NewsItem]]:
        """按来源分组"""
        groups = {}
        for item in items:
            source = item.source or "其他"
            if source not in groups:
                groups[source] = []
            groups[source].append(item)
        return groups

    def group_by_category(self, items: list[NewsItem]) -> dict[str, list[NewsItem]]:
        """按分类分组"""
        groups = {}
        for item in items:
            category = item.category or "其他"
            if category not in groups:
                groups[category] = []
            groups[category].append(item)
        return groups

    def sort_by_importance(self, items: list[NewsItem]) -> list[NewsItem]:
        """按重要程度排序"""
        order = {"high": 0, "normal": 1, "low": 2}
        return sorted(items, key=lambda x: order.get(x.importance, 1))