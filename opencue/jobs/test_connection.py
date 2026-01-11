"""
OpenCue 连接测试脚本
验证 Cuebot 连接和基本功能
"""
import os
import sys

# 加载环境变量
from pathlib import Path
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

# 设置 Cuebot 地址
os.environ.setdefault("CUEBOT_HOSTS", os.getenv("CUEBOT_HOST", "localhost"))

try:
    import opencue
    from outline import Outline
    from outline.modules.shell import Shell
except ImportError as e:
    print("错误：请先安装依赖")
    print("  pip install -r requirements.txt")
    sys.exit(1)


def test_connection():
    """测试与 Cuebot 的连接"""
    print("=" * 50)
    print("OpenCue 连接测试")
    print("=" * 50)
    
    cuebot_host = os.getenv("CUEBOT_HOSTS", "localhost")
    print(f"\nCuebot 地址: {cuebot_host}")
    
    try:
        # 尝试获取 shows 列表
        shows = opencue.api.getShows()
        print(f"✓ 连接成功！")
        print(f"  已有 Shows: {[s.name() for s in shows]}")
        return True
    except Exception as e:
        print(f"✗ 连接失败: {e}")
        print("\n请检查：")
        print("  1. Cuebot 是否已启动")
        print("  2. CUEBOT_HOST 配置是否正确")
        print("  3. 防火墙是否允许 8443 端口")
        return False


def submit_test_job():
    """提交一个简单的测试作业"""
    print("\n" + "=" * 50)
    print("提交测试作业")
    print("=" * 50)
    
    import getpass
    user = getpass.getuser()
    
    # 创建简单的 echo 作业
    ol = Outline("opencue_test", show="testing", user=user)
    
    test_layer = Shell(
        "echo_test",
        command="echo Hello from OpenCue! && timeout /t 3"  # Windows 命令
    )
    test_layer.set_cores(1)
    ol.add_layer(test_layer)
    
    try:
        jobs = ol.submit()
        print(f"✓ 作业提交成功！")
        print(f"  Job IDs: {[j.id() for j in jobs]}")
        return True
    except Exception as e:
        print(f"✗ 作业提交失败: {e}")
        return False


if __name__ == "__main__":
    # 测试连接
    connected = test_connection()
    
    if connected:
        # 询问是否提交测试作业
        response = input("\n是否提交测试作业? (y/n): ").strip().lower()
        if response == "y":
            submit_test_job()
    
    print("\n测试完成。")
