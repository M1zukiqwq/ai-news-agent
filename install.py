"""安装依赖的辅助脚本"""
import subprocess
import sys
import os

# 设置代理
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7890'

packages = [
    'httpx>=0.27.0',
    'beautifulsoup4>=4.12.0',
    'feedparser>=6.0.0',
    'PyYAML>=6.0',
    'python-dotenv>=1.0.0',
    'Jinja2>=3.1.0',
    'APScheduler>=3.10.0',
    'loguru>=0.7.0',
    'openai>=1.0.0',
    'lxml>=4.9.0',
]

mirrors = [
    'https://pypi.tuna.tsinghua.edu.cn/simple',
    'https://mirrors.aliyun.com/pypi/simple/',
    'https://pypi.org/simple',
]

for mirror in mirrors:
    print(f"\n尝试镜像源: {mirror}")
    cmd = [
        sys.executable, '-m', 'pip', 'install',
        *packages,
        '-i', mirror,
        '--trusted-host', mirror.split('//')[1].split('/')[0],
    ]
    result = subprocess.run(cmd, env=os.environ.copy())
    if result.returncode == 0:
        print("\n✅ 安装成功！")
        sys.exit(0)
    print(f"❌ 镜像 {mirror} 安装失败，尝试下一个...")

print("\n❌ 所有镜像源均安装失败，请手动安装依赖")
sys.exit(1)