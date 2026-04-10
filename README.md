# 🤖 AI News Agent

每日自动采集各大 AI 厂商最新发布信息，通过 AI 智能摘要整理后推送到邮箱。

## ✨ 功能特性

- **8大采集源**：OpenAI、Google/DeepMind、Anthropic、Meta AI、HuggingFace、综合RSS、中国AI厂商、联网搜索
- **日期过滤**：只保留最近1天内的新闻，确保时效性
- **AI 智能处理**：通过 Gemini/Kimi 等大模型生成中文摘要和分类
- **邮件推送**：精美的 HTML 邮件，按厂商分组展示
- **定时执行**：每天 07:30 自动运行（支持 crontab）
- **一键部署**：`deploy.py` 自动上传 + 安装依赖 + 配置定时任务

## 📁 项目结构

```
Agent/
├── collectors/              # 数据采集器
│   ├── base.py              # 采集器基类（含日期过滤）
│   ├── openai_collector.py  # OpenAI Blog
│   ├── google_collector.py  # Google/DeepMind Blog
│   ├── anthropic_collector.py # Anthropic News
│   ├── meta_collector.py    # Meta AI Blog
│   ├── huggingface_collector.py # HuggingFace 热门模型
│   ├── general_news_collector.py # 综合RSS（14个源）
│   ├── china_ai_collector.py # 中国AI厂商（8家）
│   └── web_search_collector.py # 联网搜索（Google/Bing）
├── processor/               # AI 处理
│   ├── gemini_client.py     # AI 客户端（支持自定义URL）
│   └── news_processor.py    # 去重、摘要、分类
├── delivery/                # 邮件推送
│   ├── email_sender.py      # SMTP 发送
│   └── templates/           # HTML 邮件模板
├── storage/                 # 数据存储
│   └── database.py          # SQLite 历史记录
├── scheduler/               # 定时调度
│   └── task_scheduler.py    # APScheduler
├── config/
│   ├── settings.yaml        # 主配置文件
│   └── .env.example         # 环境变量模板
├── deploy.py                # 一键部署脚本
├── main.py                  # 主入口
└── requirements.txt         # 依赖列表
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp config/.env.example config/.env
```

编辑 `config/.env`：

```env
AI_API_KEY=your_api_key          # AI模型API Key
EMAIL_SENDER=your_email@qq.com   # 发件邮箱
EMAIL_PASSWORD=your_auth_code    # 邮箱授权码
EMAIL_RECIPIENT=recipient@xxx.com # 收件邮箱
```

### 3. 运行

```bash
# 测试连接
python main.py test

# 单次运行（采集+推送）
python main.py run

# 启动定时调度
python main.py schedule
```

## 🔧 部署到服务器

```powershell
# 设置服务器信息（全部通过环境变量，无硬编码）
$env:DEPLOY_HOST="your-server.com"
$env:DEPLOY_PORT="22"
$env:DEPLOY_USER="username"
$env:DEPLOY_PASSWORD="password"
$env:DEPLOY_DIR="/home/user/ai-news-agent"

python deploy.py
```

部署脚本会自动：
- 创建远程目录并上传项目文件
- 安装 Python 依赖
- 配置 crontab 定时任务

## ⚙️ 配置说明

### AI 模型（支持自定义URL）

```yaml
ai:
  base_url: "https://api.moonshot.cn/v1"  # 可替换为任意 OpenAI 兼容接口
  api_key: "${AI_API_KEY}"                  # 从 .env 读取
  model: "kimi-k2.5"
```

### 采集器

每个采集器支持独立配置 `max_age_days`：

```yaml
collectors:
  openai:
    enabled: true
    max_age_days: 1    # 只保留1天内的新闻
```

### 数据源列表

| 采集器 | 来源 | 说明 |
|--------|------|------|
| OpenAI | openai.com/blog | 官方博客 |
| Google/DeepMind | blog.google, deepmind.google | AI 博客 |
| Anthropic | anthropic.com/news | 官方动态 |
| Meta AI | ai.meta.com/blog | FAIR 博客 |
| HuggingFace | huggingface.co | 热门模型 |
| 综合RSS | 14个RSS源 | TechCrunch/TheVerge/36kr/机器之心等 |
| 中国AI | 8家厂商 | 通义千问/豆包/GLM/Kimi/DeepSeek/文心/MiniMax/百川 |
| 联网搜索 | Google News + Bing | 关键词实时搜索 |

## 📝 技术栈

- **Python 3.10+**
- **httpx** - 异步 HTTP 请求
- **BeautifulSoup4** + **feedparser** - 网页/RSS 解析
- **OpenAI SDK** - AI 模型调用（兼容接口）
- **Jinja2** - 邮件模板渲染
- **APScheduler** - 定时任务调度
- **SQLite** - 历史记录存储
- **loguru** - 日志管理
- **paramiko** - SSH 部署

##  License

MIT