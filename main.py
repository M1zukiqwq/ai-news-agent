"""
AI News Agent - 每日AI资讯自动推送系统
主入口文件
"""
import sys
import os
import asyncio
import argparse
import signal
import warnings
from pathlib import Path
from datetime import datetime

import yaml
from dotenv import load_dotenv
from loguru import logger

# 抑制 SSL 验证关闭时的警告（verify=False）
warnings.filterwarnings("ignore", message="Unverified HTTPS request")
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    pass

# 确保项目根目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent))


def setup_logging(config: dict):
    """配置日志系统"""
    log_config = config.get("logging", {})
    level = log_config.get("level", "INFO")
    log_dir = log_config.get("log_dir", "logs")
    retention = f"{log_config.get('retention_days', 30)} days"

    # 确保日志目录存在
    Path(log_dir).mkdir(exist_ok=True)

    # 移除默认handler
    logger.remove()

    # 控制台输出
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
               "<level>{message}</level>",
    )

    # 文件输出
    logger.add(
        os.path.join(log_dir, "agent_{time:YYYY-MM-DD}.log"),
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
        rotation="10 MB",
        retention=retention,
        encoding="utf-8",
    )


def load_config() -> dict:
    """加载配置文件"""
    config_path = Path(__file__).parent / "config" / "settings.yaml"

    # 加载 .env 文件
    env_path = Path(__file__).parent / "config" / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"加载环境变量: {env_path}")
    else:
        logger.warning(f".env 文件不存在: {env_path}，请参考 .env.example 创建")

    # 加载 YAML 配置
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 替换环境变量占位符
    config = _resolve_env_vars(config)

    return config


def _resolve_env_vars(config: dict) -> dict:
    """递归替换配置中的 ${ENV_VAR} 占位符"""
    if isinstance(config, dict):
        return {k: _resolve_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [_resolve_env_vars(item) for item in config]
    elif isinstance(config, str):
        if config.startswith("${") and config.endswith("}"):
            env_var = config[2:-1]
            value = os.environ.get(env_var, config)
            if value == config:
                logger.warning(f"环境变量未设置: {env_var}")
            return value
        return config
    return config


def create_components(config: dict):
    """创建所有组件实例"""
    from processor import GeminiClient
    from storage.database import Database
    from delivery import EmailSender
    from scheduler import TaskScheduler

    # 初始化 AI 客户端
    ai_config = config.get("ai", {})
    ai_client = GeminiClient(ai_config)

    # 初始化数据库
    storage_config = config.get("storage", {})
    db_path = storage_config.get("db_path", "data/news_history.db")
    # 确保数据目录存在
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    database = Database(db_path)

    # 初始化邮件发送器
    email_config = config.get("email", {})
    email_sender = EmailSender(email_config)

    # 初始化调度器
    scheduler = TaskScheduler(config, ai_client, database, email_sender)

    return ai_client, database, email_sender, scheduler


async def run_daemon(config: dict):
    """守护进程模式：启动调度器，持续运行"""
    ai_client, database, email_sender, scheduler = create_components(config)

    logger.info("🤖 AI News Agent 启动（守护模式）")
    logger.info(f"调度时间: 每日 {config.get('schedule', {}).get('daily_time', '09:00')}")

    # 启动调度器
    scheduler.start()

    # 优雅退出
    stop_event = asyncio.Event()

    def signal_handler(sig, frame):
        logger.info(f"收到信号 {sig}，准备退出...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Agent 运行中，按 Ctrl+C 退出...")

    try:
        await stop_event.wait()
    finally:
        scheduler.stop()
        await ai_client.close()
        logger.info("AI News Agent 已停止")


async def run_once(config: dict):
    """单次执行模式：立即执行一次采集推送"""
    ai_client, database, email_sender, scheduler = create_components(config)

    logger.info("🤖 AI News Agent 启动（单次执行模式）")

    try:
        await scheduler.run_daily_task()
    finally:
        await ai_client.close()


async def run_test(config: dict):
    """测试模式：测试配置和连接"""
    logger.info("🧪 测试模式 - 检查配置和连接")
    logger.info("-" * 40)

    # 测试 AI API
    ai_config = config.get("ai", {})
    logger.info(f"AI API: {ai_config.get('base_url', 'N/A')}")
    logger.info(f"AI Model: {ai_config.get('model', 'N/A')}")
    logger.info(f"AI API Key: {'***' + ai_config.get('api_key', '')[-4:] if ai_config.get('api_key') else '未设置'}")

    try:
        from processor import GeminiClient
        client = GeminiClient(ai_config)
        response = await client.generate("请用一句话介绍你自己。")
        logger.info(f"✅ AI API 连接成功: {response[:50]}...")
        await client.close()
    except Exception as e:
        logger.error(f"❌ AI API 连接失败: {e}")

    logger.info("")

    # 测试邮件配置
    email_config = config.get("email", {})
    logger.info(f"SMTP: {email_config.get('smtp_host', 'N/A')}:{email_config.get('smtp_port', 'N/A')}")
    logger.info(f"发件人: {email_config.get('sender', 'N/A')}")
    logger.info(f"收件人: {email_config.get('recipients', [])}")

    logger.info("")

    # 测试数据库
    storage_config = config.get("storage", {})
    db_path = storage_config.get("db_path", "data/news_history.db")
    try:
        from storage.database import Database
        db = Database(db_path)
        logger.info(f"✅ 数据库初始化成功: {db_path}")
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {e}")

    logger.info("")

    # 测试采集器
    collectors_config = config.get("collectors", {})
    enabled_collectors = [k for k, v in collectors_config.items() if v.get("enabled", False)]
    logger.info(f"启用的采集器: {', '.join(enabled_collectors)}")

    logger.info("-" * 40)
    logger.info("🧪 测试完成")


def main():
    parser = argparse.ArgumentParser(description="AI News Agent - 每日AI资讯自动推送系统")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "schedule", "test"],
        help="运行模式: run=单次执行, schedule=定时调度, test=测试配置 (默认: run)",
    )
    args = parser.parse_args()

    # 加载配置
    config = load_config()

    # 配置日志
    setup_logging(config)

    logger.info(f"AI News Agent v1.0 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if args.command == "test":
        asyncio.run(run_test(config))
    elif args.command == "run":
        asyncio.run(run_once(config))
    elif args.command == "schedule":
        asyncio.run(run_daemon(config))


if __name__ == "__main__":
    main()