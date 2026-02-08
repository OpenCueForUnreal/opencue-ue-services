"""
OpenCue + UE5 集成配置
从环境变量或默认值加载配�?
"""
import os
from pathlib import Path
from dataclasses import dataclass

@dataclass
class OpenCueConfig:
    # Cuebot 服务器地址
    cuebot_host: str = "localhost"
    cuebot_port: int = 8443
    
    # Show 配置 (OpenCue 概念: Show -> Job -> Layer -> Frame)
    show_name: str = "UE_RENDER"
    
    # UE5 配置
    ue_root: str = ""
    uproject: str = ""
    executor_class: str = "/Script/OpenCueForUnrealCmdline.MoviePipelineOpenCueCmdExecutor"
    game_mode_class: str = "/Script/MovieRenderPipelineCore.MoviePipelineGameMode"
    
    # 资源配置
    default_cores: int = 8
    default_memory_gb: int = 16
    default_gpu_memory_mb: int = 8192
    
    @classmethod
    def from_env(cls) -> "OpenCueConfig":
        """从环境变量加载配�?""
        return cls(
            cuebot_host=os.getenv("CUEBOT_HOST", "localhost"),
            cuebot_port=int(os.getenv("CUEBOT_PORT", "8443")),
            show_name=os.getenv("OPENCUE_SHOW", "UE_RENDER"),
            ue_root=os.getenv("UE_ROOT", ""),
            uproject=os.getenv("UPROJECT", ""),
            executor_class=os.getenv("EXECUTOR_CLASS",
                "/Script/OpenCueForUnrealCmdline.MoviePipelineOpenCueCmdExecutor"),
            game_mode_class=os.getenv("GAME_MODE_CLASS",
                "/Script/MovieRenderPipelineCore.MoviePipelineGameMode"),
            default_cores=int(os.getenv("DEFAULT_CORES", "8")),
            default_memory_gb=int(os.getenv("DEFAULT_MEMORY_GB", "16")),
            default_gpu_memory_mb=int(os.getenv("DEFAULT_GPU_MEMORY_MB", "8192")),
        )


def get_ue_editor_cmd(config: OpenCueConfig) -> str:
    """获取 UE Editor 命令行可执行文件路径"""
    ue_root = Path(config.ue_root)
    
    # Windows
    win_path = ue_root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    if win_path.exists():
        return str(win_path)
    
    # Linux
    linux_path = ue_root / "Engine" / "Binaries" / "Linux" / "UnrealEditor-Cmd"
    if linux_path.exists():
        return str(linux_path)
    
    raise FileNotFoundError(f"UnrealEditor-Cmd not found in {ue_root}")


# 全局配置实例
config = OpenCueConfig.from_env()

