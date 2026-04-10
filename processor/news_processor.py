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

    def _title_deduplicate(self, items: list[NewsItem]) -> list[NewsItem]:
        """
        标题级去重：相似标题只保留信息最丰富的一条
        通过标题关键词重叠度判断
        """
        if len(items) <= 1:
            return items

        def title_similarity(a: str, b: str) -> float:
            """简单的标题相似度计算"""
            # 提取关键词（去掉常见停用词）
            stop_words = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "is", "are",
                         "was", "were", "be", "been", "new", "ai", "的", "了", "在", "是", "和", "与"}
            words_a = set(a.lower().split()) - stop_words
            words_b = set(b.lower().split()) - stop_words
            if not words_a or not words_b:
                return 0.0
            intersection = words_a & words_b
            return len(intersection) / min(len(words_a), len(words_b))

        kept = []
        removed = 0
        for item in items:
            is_dup = False
            for existing in kept:
                sim = title_similarity(item.title, existing.title)
                if sim >= 0.65:
                    # 保留摘要更长或来源更权威的
                    existing_len = len(existing.summary or "")
                    item_len = len(item.summary or "")
                    if item_len > existing_len:
                        kept.remove(existing)
                        kept.append(item)
                    is_dup = True
                    removed += 1
                    break
            if not is_dup:
                kept.append(item)

        if removed > 0:
            logger.info(f"📊 标题去重: {len(items)} → {len(kept)} 条（合并 {removed} 条相似新闻）")
        return kept

    async def _ai_merge_duplicates(self, items: list[NewsItem]) -> list[NewsItem]:
        """
        AI 智能合并：让 AI 判断哪些新闻是关于同一事件的，
        并将它们合并为一条更完整的报道
        """
        if len(items) <= 3:
            return items

        # 构建新闻列表给 AI
        news_list = []
        for idx, item in enumerate(items, 1):
            info = f"{idx}. [{item.source}] {item.title}"
            if item.summary:
                info += f"\n   摘要: {item.summary[:150]}"
            news_list.append(info)

        prompt = f"""以下是今天采集到的 {len(items)} 条AI新闻。请检查是否存在关于同一事件/同一话题的重复报道。

{chr(10).join(news_list)}

如果有重复报道，返回需要合并的条目索引组（保留信息最完整的一条）。
返回JSON格式：
{{"merge_groups": [{{"keep": 1, "remove": [2, 5]}}], "reason": "合并原因简述"}}
如果没有重复，返回：{{"merge_groups": [], "reason": "无重复"}}"""

        try:
            result = await self.gemini.generate_json(
                prompt=prompt,
                system_prompt="你是新闻去重专家，只合并明确报道同一事件的新闻。谨慎判断，宁可保留也不要误删。",
                max_tokens=1024,
            )

            if isinstance(result, dict) and "raw_response" in result:
                return items

            merge_groups = result.get("merge_groups", []) if isinstance(result, dict) else []
            if not merge_groups:
                return items

            remove_indices = set()
            for group in merge_groups:
                for rm_idx in group.get("remove", []):
                    remove_indices.add(rm_idx - 1)

            if not remove_indices:
                return items

            merged = [item for idx, item in enumerate(items) if idx not in remove_indices]
            logger.info(
                f"📊 AI合并去重: {len(items)} → {len(merged)} 条"
                f"（AI建议合并 {len(remove_indices)} 条: {result.get('reason', '')}）"
            )
            return merged

        except Exception as e:
            logger.debug(f"📊 AI合并去重失败（不影响流程）: {e}")
            return items

    async def process_items(self, items: list[NewsItem]) -> list[NewsItem]:
        """
        批量处理新闻条目：
        1. 标题去重
        2. AI智能合并
        3. 数据库去重
        4. 保存到数据库
        5. 生成AI摘要和分类
        确保每条新闻都被保留，AI处理失败时使用原始摘要
        """
        if not items:
            logger.info("没有需要处理的新闻")
            return []

        total_collected = len(items)
        logger.info(f"📊 开始处理: 共采集 {total_collected} 条原始新闻")

        # 第0步：标题级快速去重
        items = self._title_deduplicate(items)
        logger.info(f"📊 标题去重后: {len(items)} 条")

        # 第0.5步：AI智能合并重复报道
        items = await self._ai_merge_duplicates(items)
        logger.info(f"📊 AI合并后: {len(items)} 条")

        # 第一步：数据库去重并保存新条目
        new_items = []
        duplicate_count = 0
        for item in items:
            if not self.db.is_duplicate(item):
                if self.db.save_news(item):
                    new_items.append(item)
            else:
                duplicate_count += 1

        logger.info(f"📊 数据库去重结果: {duplicate_count} 条重复, {len(new_items)} 条新新闻")

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