"""
邮件发送模块
支持 HTML 模板渲染，通过 SMTP 发送
"""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path
from datetime import datetime
from typing import Optional

from jinja2 import Environment, FileSystemLoader
from loguru import logger

from storage.database import NewsItem


class EmailSender:
    """邮件发送器"""

    def __init__(self, config: dict):
        self.smtp_host = config.get("smtp_host", "smtp.qq.com")
        self.smtp_port = config.get("smtp_port", 465)
        self.use_ssl = config.get("use_ssl", True)
        self.sender = config.get("sender", "")
        self.password = config.get("password", "")
        self.recipients = config.get("recipients", [])

        # Jinja2 模板环境
        template_dir = Path(__file__).parent / "templates"
        self.env = Environment(loader=FileSystemLoader(str(template_dir)))
        logger.info(f"邮件发送器初始化: {self.smtp_host}:{self.smtp_port}")

    def send_daily_report(
        self,
        items: list[NewsItem],
        daily_summary: str,
        grouped_by_source: dict[str, list[NewsItem]],
    ) -> bool:
        """
        发送每日报告邮件
        
        Args:
            items: 所有新闻条目
            daily_summary: 每日总结
            grouped_by_source: 按来源分组的新闻
            
        Returns:
            是否发送成功
        """
        if not items:
            logger.info("没有新闻需要发送")
            return True

        today = datetime.now().strftime("%Y年%m月%d日")
        subject = f"🤖 AI日报 - {today}（共{len(items)}条）"

        # 渲染HTML
        html_content = self._render_html(
            items=items,
            daily_summary=daily_summary,
            grouped_by_source=grouped_by_source,
            date_str=today,
        )

        # 渲染纯文本（备用）
        text_content = self._render_text(items, daily_summary)

        # 发送邮件
        return self._send_email(subject, html_content, text_content)

    def _render_html(
        self,
        items: list[NewsItem],
        daily_summary: str,
        grouped_by_source: dict[str, list[NewsItem]],
        date_str: str,
    ) -> str:
        """渲染HTML邮件"""
        try:
            template = self.env.get_template("daily_report.html")
            html = template.render(
                date_str=date_str,
                total_count=len(items),
                daily_summary=daily_summary,
                grouped_news=grouped_by_source,
                importance_high=sum(1 for i in items if i.importance == "high"),
                importance_normal=sum(1 for i in items if i.importance == "normal"),
                importance_low=sum(1 for i in items if i.importance == "low"),
                sources=list(grouped_by_source.keys()),
            )
            return html
        except Exception as e:
            logger.error(f"渲染HTML模板失败: {e}")
            return self._fallback_html(items, date_str, daily_summary)

    def _fallback_html(self, items: list[NewsItem], date_str: str, daily_summary: str) -> str:
        """HTML渲染失败时的备用模板"""
        html = f"""<html><body>
        <h1>🤖 AI日报 - {date_str}</h1>
        <p>{daily_summary}</p>
        <hr>"""
        for item in items:
            html += f"""<div style="margin-bottom: 16px; padding: 12px; border: 1px solid #ddd;">
                <h3><a href="{item.url}">{item.title}</a></h3>
                <p>来源: {item.source} | 分类: {item.category or '未分类'} | 重要程度: {item.importance}</p>
                <p>{item.ai_summary or item.summary or ''}</p>
            </div>"""
        html += "</body></html>"
        return html

    def _render_text(self, items: list[NewsItem], daily_summary: str) -> str:
        """渲染纯文本邮件"""
        text = f"AI日报\n{'=' * 50}\n\n{daily_summary}\n\n"
        for item in items:
            text += f"【{item.source}】{item.title}\n"
            text += f"链接: {item.url}\n"
            if item.ai_summary:
                text += f"摘要: {item.ai_summary}\n"
            text += f"分类: {item.category or '未分类'} | 重要程度: {item.importance}\n"
            text += "-" * 40 + "\n"
        return text

    def _send_email(self, subject: str, html_content: str, text_content: str) -> bool:
        """发送邮件"""
        if not self.recipients:
            logger.warning("没有配置收件人")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)
            msg["Date"] = formatdate(localtime=True)

            # 添加纯文本和HTML内容
            msg.attach(MIMEText(text_content, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            # 连接SMTP服务器并发送
            if self.use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context) as server:
                    server.login(self.sender, self.password)
                    server.sendmail(self.sender, self.recipients, msg.as_string())
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.sender, self.password)
                    server.sendmail(self.sender, self.recipients, msg.as_string())

            logger.info(f"邮件发送成功: {subject} -> {self.recipients}")
            return True

        except Exception as e:
            logger.error(f"邮件发送失败: {e}", exc_info=True)
            return False