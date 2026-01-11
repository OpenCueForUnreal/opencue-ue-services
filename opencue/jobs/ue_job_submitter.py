"""
UE5 作业提交脚本 - 使用 PyOutline 向 OpenCue 提交渲染作业

使用方法:
    python ue_job_submitter.py --template Seq1 --job-id abc123
    python ue_job_submitter.py --test  # 提交测试作业
"""
import argparse
import json
import uuid
from pathlib import Path
from typing import Optional

# PyOutline 导入 (需要安装: pip install pyoutline opencue)
try:
    from outline import Outline
    from outline.modules.shell import Shell
    import opencue
except ImportError as e:
    print("请先安装 OpenCue Python 客户端:")
    print("  pip install pyoutline opencue")
    raise e

from outline_config import config, get_ue_editor_cmd


class UEMRQShellCommand(Shell):
    """
    自定义 UE5 渲染 Shell 命令层
    
    继承自 Shell 以便 OpenCue 识别为可执行命令
    """
    
    def __init__(
        self,
        name: str,
        job_id: str,
        map_path: str,
        level_sequence: str,
        movie_quality: int = 2,
        movie_format: str = "mp4",
        mrq_server_base_url: Optional[str] = None,
        **kwargs
    ):
        """
        Args:
            name: Layer 名称
            job_id: 作业 ID (用于 UE 回调)
            map_path: 地图资产路径
            level_sequence: 关卡序列资产路径
            movie_quality: 画质等级 (0=LOW, 1=MEDIUM, 2=HIGH, 3=EPIC)
            movie_format: 输出格式 (mp4/mov)
            mrq_server_base_url: MRQ Server 回调地址
        """
        self.job_id = job_id
        self.map_path = map_path
        self.level_sequence = level_sequence
        self.movie_quality = movie_quality
        self.movie_format = movie_format
        self.mrq_server_base_url = mrq_server_base_url
        
        # 构建命令
        command = self._build_ue_command()
        
        # 调用父类初始化
        Shell.__init__(self, name, command=command, **kwargs)
        
        # 设置资源需求
        self.set_cores(config.default_cores)
        self.set_memory(config.default_memory_gb * 1024 * 1024)  # 转换为 KB
    
    def _build_ue_command(self) -> str:
        """构建 UE5 命令行"""
        ue_cmd = get_ue_editor_cmd(config)
        
        # 构建地图 URL (包含 GameMode)
        map_url = self.map_path
        if config.game_mode_class:
            map_url = f"{map_url}?game={config.game_mode_class}"
        
        cmd_parts = [
            f'"{ue_cmd}"',
            f'"{config.uproject}"',
            map_url,
            "-game",
            f"-LevelSequence={self.level_sequence}",
            f"-MoviePipelineLocalExecutorClass={config.executor_class}",
            f"-MovieQuality={self.movie_quality}",
            f"-MovieFormat={self.movie_format}",
            f"-JobId={self.job_id}",
        ]
        
        if self.mrq_server_base_url:
            cmd_parts.append(f"-MRQServerBaseUrl={self.mrq_server_base_url}")
        
        # 添加无头渲染参数
        cmd_parts.extend([
            "-RenderOffscreen",
            "-Unattended",
            "-NOSPLASH",
            "-NoLoadingScreen",
            "-notexturestreaming",
        ])
        
        return " ".join(cmd_parts)


def submit_ue_job(
    template_id: str,
    map_path: str,
    level_sequence: str,
    job_id: Optional[str] = None,
    movie_quality: int = 2,
    movie_format: str = "mp4",
    mrq_server_base_url: Optional[str] = None,
    user: Optional[str] = None,
) -> str:
    """
    提交 UE5 渲染作业到 OpenCue
    
    Args:
        template_id: 模板 ID (用于命名)
        map_path: 地图资产路径
        level_sequence: 关卡序列资产路径
        job_id: 作业 ID，如果不提供则自动生成
        movie_quality: 画质等级
        movie_format: 输出格式
        mrq_server_base_url: MRQ Server 回调地址
        user: 提交用户名
        
    Returns:
        提交的作业 ID
    """
    if job_id is None:
        job_id = str(uuid.uuid4())
    
    if user is None:
        import getpass
        user = getpass.getuser()
    
    # 创建 Outline 作业
    job_name = f"ue_render_{template_id}_{job_id[:8]}"
    outline = Outline(job_name, show=config.show_name, user=user)
    
    # 添加 UE 渲染层
    render_layer = UEMRQShellCommand(
        name=f"render_{template_id}",
        job_id=job_id,
        map_path=map_path,
        level_sequence=level_sequence,
        movie_quality=movie_quality,
        movie_format=movie_format,
        mrq_server_base_url=mrq_server_base_url,
    )
    outline.add_layer(render_layer)
    
    # 提交作业
    jobs = outline.submit()
    
    print(f"作业已提交: {job_name}")
    print(f"作业 ID: {job_id}")
    print(f"OpenCue Job IDs: {[j.id() for j in jobs]}")
    
    return job_id


def submit_test_job() -> str:
    """提交一个简单的测试作业验证 OpenCue 连接"""
    job_id = str(uuid.uuid4())
    job_name = f"test_opencue_{job_id[:8]}"
    
    import getpass
    user = getpass.getuser()
    
    outline = Outline(job_name, show=config.show_name, user=user)
    
    # 简单的 echo 命令测试
    test_layer = Shell(
        "test_layer",
        command="echo 'OpenCue connection test successful!' && sleep 5"
    )
    test_layer.set_cores(1)
    outline.add_layer(test_layer)
    
    jobs = outline.submit()
    
    print(f"测试作业已提交: {job_name}")
    print(f"OpenCue Job IDs: {[j.id() for j in jobs]}")
    
    return job_id


def main():
    parser = argparse.ArgumentParser(description="提交 UE5 渲染作业到 OpenCue")
    parser.add_argument("--test", action="store_true", help="提交测试作业")
    parser.add_argument("--template", type=str, help="模板 ID")
    parser.add_argument("--map-path", type=str, help="地图资产路径")
    parser.add_argument("--level-sequence", type=str, help="关卡序列资产路径")
    parser.add_argument("--job-id", type=str, help="作业 ID (可选)")
    parser.add_argument("--quality", type=int, default=2, 
                        help="画质等级 (0=LOW, 1=MEDIUM, 2=HIGH, 3=EPIC)")
    parser.add_argument("--format", type=str, default="mp4", 
                        choices=["mp4", "mov"], help="输出格式")
    parser.add_argument("--mrq-server", type=str, help="MRQ Server 回调地址")
    
    args = parser.parse_args()
    
    if args.test:
        submit_test_job()
    elif args.template and args.map_path and args.level_sequence:
        submit_ue_job(
            template_id=args.template,
            map_path=args.map_path,
            level_sequence=args.level_sequence,
            job_id=args.job_id,
            movie_quality=args.quality,
            movie_format=args.format,
            mrq_server_base_url=args.mrq_server,
        )
    else:
        parser.print_help()
        print("\n示例:")
        print("  python ue_job_submitter.py --test")
        print("  python ue_job_submitter.py --template Seq1 "
              "--map-path /Game/Maps/Map0.Map0 "
              "--level-sequence /Game/Seqs/Seq1.Seq1")


if __name__ == "__main__":
    main()
