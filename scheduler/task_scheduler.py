"""
定时任务调度器
使用 APScheduler 实现每日定时采集和推送
"""
import asyncio
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from collectors import COLLECTOR_MAP
from processor import GeminiClient, NewsProcessor
from delivery import EmailSender
from storage.database import Database


class TaskScheduler:
    """任务调度器"""

    def __init__(
        self,
        config: dict,
        gemini_client: GeminiClient,
        database: Database,
        email_sender: EmailSender,
    ):
        self.config = config
        self.gemini = gemini_client
        self.db = database
        self.email = email_sender
        self.processor = NewsProcessor(gemini_client, database)

        # 调度配置
        schedule_config = config.get("schedule", {})
        self.daily_time = schedule_config.get("daily_time", "09:00")
        self.timezone = schedule_config.get("timezone", "Asia/Shanghai")

        # 创建调度器
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)

    def _parse_time(self) -> dict:
        """解析配置时间"""
        parts = self.daily_time.split(":")
        hour = int(parts[0]) if len(parts) > 0 else 9
        minute = int(parts[1]) if len(parts) > 1 else 0
        return {"hour": hour, "minute": minute}

    def start(self):
        """启动调度器"""
        time_config = self._parse_time()

        # 添加每日定时任务
        self.scheduler.add_job(
            self.run_daily_task,
            trigger=CronTrigger(
                hour=time_config["hour"],
                minute=time_config["minute"],
                timezone=self.timezone,
            ),
            id="daily_ai_news",
            name="每日AI新闻采集推送",
            replace_existing=True,
        )

        logger.info(
            f"调度器启动: 每日 {time_config['hour']:02d}:{time_config['minute']:02d} "
            f"({self.timezone}) 执行采集推送任务"
        )

        self.scheduler.start()

    def stop(self):
        """停止调度器"""
        self.scheduler.shutdown(wait=False)
        logger.info("调度器已停止")

    async def run_daily_task(self):
        """执行每日任务：采集 → 处理 → 推送"""
        logger.info("=" * 60)
        logger.info("开始执行每日AI新闻采集推送任务")
        logger.info("=" * 60)

        start_time = datetime.now()

        try:
            # 第一步：采集所有数据源
            all_items = await self._collect_all()

            if not all_items:
                logger.info("今日未采集到任何新闻")
                self.db.log_send(0, "success", "今日无新闻")
                return

            logger.info(f"📊 采集阶段完成，共获取 {len(all_items)} 条原始新闻")

            # 第二步：去重、保存、AI处理
            processed_items = await self.processor.process_items(all_items)

            if not processed_items:
                logger.info("📊 过滤后无新新闻需要推送")
                self.db.log_send(0, "success", "无新新闻")
                return

            logger.info(f"处理阶段完成，共 {len(processed_items)} 条新闻待推送")

            # 第三步：按重要度排序
            sorted_items = self.processor.sort_by_importance(processed_items)

            # 第四步：生成每日总结
            daily_summary = await self.processor.generate_daily_summary(sorted_items)

            # 第五步：按来源分组
            grouped = self.processor.group_by_source(sorted_items)

            # 第六步：发送邮件
            success = self.email.send_daily_report(
                items=sorted_items,
                daily_summary=daily_summary,
                grouped_by_source=grouped,
            )

            if success:
                # 标记为已发送
                self.db.mark_as_sent(sorted_items)
                self.db.log_send(len(sorted_items), "success")
                logger.info("✅ 每日推送任务完成！")
            else:
                self.db.log_send(len(sorted_items), "failed", "邮件发送失败")
                logger.error("❌ 邮件发送失败")

        except Exception as e:
            logger.error(f"每日任务执行异常: {e}", exc_info=True)
            self.db.log_send(0, "error", str(e))

        finally:
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"任务执行耗时: {duration:.1f} 秒")
            logger.info("=" * 60)

    async def _collect_all(self):
        """并发采集所有启用的数据源"""
        collectors_config = self.config.get("collectors", {})
        
        # 创建所有启用的采集器实例
        active_collectors = []
        for name, collector_class in COLLECTOR_MAP.items():
            collector_config = collectors_config.get(name, {})
            if collector_config.get("enabled", False):
                collector = collector_class(collector_config)
                active_collectors.append(collector)
                logger.info(f"启用采集器: {collector.name}")

        if not active_collectors:
            logger.warning("没有启用任何采集器")
            return []

        # 并发采集
        tasks = [collector.safe_collect() for collector in active_collectors]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 关闭所有采集器的HTTP客户端
        for collector in active_collectors:
            await collector.close()

        # 合并结果
        all_items = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"采集器异常: {result}")
                continue
            if isinstance(result, list):
                all_items.extend(result)

        return all_items