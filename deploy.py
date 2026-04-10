"""
部署脚本 - 将项目部署到远程服务器并设置定时任务
"""
import paramiko
import os
import sys

# 服务器配置（全部通过环境变量设置，无默认值防止泄露）
HOST = os.environ.get("DEPLOY_HOST", "")
PORT = int(os.environ.get("DEPLOY_PORT", "22"))
USER = os.environ.get("DEPLOY_USER", "")
PASSWORD = os.environ.get("DEPLOY_PASSWORD", "")
REMOTE_DIR = os.environ.get("DEPLOY_DIR", "")

missing = [k for k, v in {"DEPLOY_HOST": HOST, "DEPLOY_USER": USER, "DEPLOY_PASSWORD": PASSWORD, "DEPLOY_DIR": REMOTE_DIR}.items() if not v]
if missing:
    print("❌ 请设置以下环境变量:")
    for k in missing:
        print(f"  {k}=xxx")
    print("\n  示例:")
    print('  $env:DEPLOY_HOST="your-server.com"; $env:DEPLOY_PORT="22"; $env:DEPLOY_USER="username"; $env:DEPLOY_PASSWORD="password"; $env:DEPLOY_DIR="/home/user/ai-news-agent"; python deploy.py')
    sys.exit(1)

# 本地项目目录
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))

# 需要上传的文件（排除 .git, __pycache__, data, logs 等）
UPLOAD_FILES = [
    "main.py",
    "requirements.txt",
    "config/settings.yaml",
    "config/.env.example",
    "collectors/__init__.py",
    "collectors/base.py",
    "collectors/openai_collector.py",
    "collectors/google_collector.py",
    "collectors/anthropic_collector.py",
    "collectors/meta_collector.py",
    "collectors/huggingface_collector.py",
    "collectors/general_news_collector.py",
    "collectors/china_ai_collector.py",
    "collectors/web_search_collector.py",
    "processor/__init__.py",
    "processor/gemini_client.py",
    "processor/news_processor.py",
    "delivery/__init__.py",
    "delivery/email_sender.py",
    "delivery/templates/daily_report.html",
    "scheduler/__init__.py",
    "scheduler/task_scheduler.py",
    "storage/__init__.py",
    "storage/database.py",
    "config/.env",  # 部署到服务器（已在.gitignore中）
]


def create_ssh_client():
    """创建SSH连接"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"连接服务器 {HOST}:{PORT}...")
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
    print("✅ SSH连接成功")
    return client


def exec_command(client, cmd, check=False):
    """执行远程命令"""
    print(f"  $ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    code = stdout.channel.recv_exit_status()

    if out:
        print(f"    {out}")
    if err and code != 0:
        print(f"    [stderr] {err}")
    if check and code != 0:
        raise RuntimeError(f"命令执行失败 (code={code}): {err}")
    return out, err, code


def upload_files(client):
    """上传项目文件"""
    # 先用 SSH 创建所有远程目录
    dirs = set()
    for f in UPLOAD_FILES:
        dir_path = os.path.dirname(f)
        while dir_path:
            dirs.add(dir_path)
            dir_path = os.path.dirname(dir_path)

    for d in sorted(dirs, key=len):
        remote_path = f"{REMOTE_DIR}/{d}"
        exec_command(client, f"mkdir -p {remote_path}")

    sftp = client.open_sftp()

    # 上传文件
    print(f"\n📤 上传 {len(UPLOAD_FILES)} 个文件...")
    for local_rel_path in UPLOAD_FILES:
        local_path = os.path.join(LOCAL_DIR, local_rel_path.replace("/", os.sep))
        remote_path = f"{REMOTE_DIR}/{local_rel_path}"
        if os.path.exists(local_path):
            print(f"  {local_rel_path} → {remote_path}")
            sftp.put(local_path, remote_path)
        else:
            print(f"  ⚠️ 本地文件不存在: {local_rel_path}")

    sftp.close()
    print("✅ 文件上传完成")


def setup_environment(client):
    """在服务器上安装依赖"""
    print("\n🔧 配置服务器环境...")

    # 检查 Python3
    out, _, _ = exec_command(client, "which python3 || which python")
    python_cmd = "python3" if "python3" in out else "python"

    # 安装依赖
    exec_command(client, f"cd {REMOTE_DIR} && {python_cmd} -m pip install -r requirements.txt --quiet 2>&1 || "
                         f"{python_cmd} -m pip install -r requirements.txt --user --quiet 2>&1")

    # 创建必要目录
    exec_command(client, f"mkdir -p {REMOTE_DIR}/data {REMOTE_DIR}/logs")

    # 如果 .env 不存在，提示用户
    out, _, _ = exec_command(client, f"test -f {REMOTE_DIR}/config/.env && echo 'exists' || echo 'missing'")
    if "missing" in out:
        print("\n⚠️  服务器上未找到 config/.env 文件！")
        print("请手动创建:")
        print(f"  ssh {USER}@{HOST} -p {PORT}")
        print(f"  vi {REMOTE_DIR}/config/.env")
        print("并填入以下内容:")
        print("""
AI_API_KEY=your_api_key
EMAIL_SENDER=your_email@qq.com
EMAIL_PASSWORD=your_email_auth_code
EMAIL_RECIPIENT=recipient@example.com
""")

    return python_cmd


def setup_cron(client, python_cmd):
    """设置 crontab 定时任务"""
    print("\n⏰ 设置 crontab 定时任务（每天 07:30 执行）...")

    # 获取 python 完整路径
    python_path, _, _ = exec_command(client, f"which {python_cmd}")

    cron_entry = (
        f"# AI News Agent - 每天07:30执行\n"
        f"30 7 * * * cd {REMOTE_DIR} && "
        f"{python_path} main.py run >> {REMOTE_DIR}/logs/cron.log 2>&1\n"
    )

    # 读取现有 crontab
    existing, _, _ = exec_command(client, "crontab -l 2>/dev/null || echo ''")

    # 移除旧的 AI News Agent 条目
    lines = existing.split('\n')
    new_lines = []
    skip = False
    for line in lines:
        if 'AI News Agent' in line:
            skip = True
            continue
        if skip and 'main.py' in line:
            skip = False
            continue
        if skip and not line.strip():
            skip = False
            continue
        new_lines.append(line)

    # 添加新条目
    new_cron = '\n'.join(new_lines).strip() + '\n\n' + cron_entry

    # 写入 crontab
    stdin, stdout, stderr = client.exec_command('crontab -')
    stdin.write(new_cron)
    stdin.flush()
    stdin.channel.shutdown_write()
    stdout.read()
    stderr.read()

    print("✅ crontab 设置完成")

    # 验证
    exec_command(client, "crontab -l")


def main():
    print("=" * 60)
    print("AI News Agent - 服务器部署")
    print("=" * 60)

    client = create_ssh_client()

    try:
        # 1. 上传文件
        upload_files(client)

        # 2. 安装依赖
        python_cmd = setup_environment(client)

        # 3. 设置定时任务
        setup_cron(client, python_cmd)

        print("\n" + "=" * 60)
        print("✅ 部署完成！")
        print("=" * 60)
        print(f"\n项目目录: {REMOTE_DIR}")
        print(f"定时任务: 每天 07:30 (Asia/Shanghai)")
        print(f"手动运行: ssh {USER}@{HOST} -p {PORT}")
        print(f"         cd {REMOTE_DIR} && {python_cmd} main.py run")

    finally:
        client.close()
        print("\nSSH连接已关闭")


if __name__ == "__main__":
    main()