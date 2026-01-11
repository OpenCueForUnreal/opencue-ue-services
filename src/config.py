"""
Configuration management for OpenCue UE Worker Pool
Loads from environment variables, .env file, or JSON config
"""
import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv


@dataclass
class WorkerPoolConfig:
    """UE Worker Pool configuration"""

    # Worker Pool HTTP service
    host: str = "0.0.0.0"
    port: int = 9100

    # UE process management
    ue_root: str = ""
    uproject: str = ""
    executor_class: str = "/Script/OpenCueForUnreal.MoviePipelineOpenCuePIEExecutor"
    game_mode_class: str = "/Script/MovieRenderPipelineCore.MoviePipelineGameMode"

    # Pool sizing
    min_workers: int = 1
    max_workers: int = 4

    # Timeouts (seconds)
    worker_startup_timeout: float = 120.0
    worker_idle_timeout: float = 300.0  # Kill idle workers after 5 min
    heartbeat_timeout: float = 30.0
    task_timeout: float = 3600.0  # 1 hour max per task

    # Paths
    data_root: str = "./data"
    log_root: str = "./logs"

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "WorkerPoolConfig":
        """Load config from environment variables"""
        if env_file:
            load_dotenv(env_file)
        else:
            # Try to find .env in common locations
            for path in [".env", "../.env", "config/.env"]:
                if Path(path).exists():
                    load_dotenv(path)
                    break

        return cls(
            host=os.getenv("WORKER_POOL_HOST", "0.0.0.0"),
            port=int(os.getenv("WORKER_POOL_PORT", "9100")),
            ue_root=os.getenv("UE_ROOT", ""),
            uproject=os.getenv("UPROJECT", ""),
            executor_class=os.getenv(
                "EXECUTOR_CLASS",
                "/Script/OpenCueForUnreal.MoviePipelineOpenCuePIEExecutor"
            ),
            game_mode_class=os.getenv(
                "GAME_MODE_CLASS",
                "/Script/MovieRenderPipelineCore.MoviePipelineGameMode"
            ),
            min_workers=int(os.getenv("MIN_WORKERS", "1")),
            max_workers=int(os.getenv("MAX_WORKERS", "4")),
            worker_startup_timeout=float(os.getenv("WORKER_STARTUP_TIMEOUT", "120")),
            worker_idle_timeout=float(os.getenv("WORKER_IDLE_TIMEOUT", "300")),
            heartbeat_timeout=float(os.getenv("HEARTBEAT_TIMEOUT", "30")),
            task_timeout=float(os.getenv("TASK_TIMEOUT", "3600")),
            data_root=os.getenv("DATA_ROOT", "./data"),
            log_root=os.getenv("LOG_ROOT", "./logs"),
        )

    @classmethod
    def from_json(cls, json_path: str) -> "WorkerPoolConfig":
        """Load config from JSON file"""
        with open(json_path, "r") as f:
            data = json.load(f)

        # Extract worker_pool section if present
        if "worker_pool" in data:
            data = data["worker_pool"]

        return cls(**data)


@dataclass
class CuebotConfig:
    """OpenCue Cuebot configuration"""
    host: str = "localhost"
    port: int = 8443
    show_name: str = "UE_RENDER"

    @classmethod
    def from_env(cls) -> "CuebotConfig":
        return cls(
            host=os.getenv("CUEBOT_HOST", "localhost"),
            port=int(os.getenv("CUEBOT_PORT", "8443")),
            show_name=os.getenv("OPENCUE_SHOW", "UE_RENDER"),
        )


@dataclass
class MRQServerConfig:
    """MRQ Server configuration for progress reporting"""
    base_url: str = "http://127.0.0.1:8080/"

    @classmethod
    def from_env(cls) -> "MRQServerConfig":
        url = os.getenv("MRQ_SERVER_BASE_URL", "http://127.0.0.1:8080/")
        if not url.endswith("/"):
            url += "/"
        return cls(base_url=url)


@dataclass
class OpenCueConfig:
    """Combined configuration for all components"""
    worker_pool: WorkerPoolConfig = field(default_factory=WorkerPoolConfig)
    cuebot: CuebotConfig = field(default_factory=CuebotConfig)
    mrq_server: MRQServerConfig = field(default_factory=MRQServerConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "OpenCueConfig":
        """
        Load configuration from file or environment.
        Priority: config_path > env vars > defaults
        """
        if config_path and Path(config_path).exists():
            with open(config_path, "r") as f:
                data = json.load(f)

            worker_pool = WorkerPoolConfig(**data.get("worker_pool", {}))
            cuebot = CuebotConfig(**data.get("cuebot", {}))
            mrq_server = MRQServerConfig(**data.get("mrq_server", {}))

            return cls(worker_pool=worker_pool, cuebot=cuebot, mrq_server=mrq_server)

        # Fall back to environment variables
        return cls(
            worker_pool=WorkerPoolConfig.from_env(),
            cuebot=CuebotConfig.from_env(),
            mrq_server=MRQServerConfig.from_env(),
        )


# Global config instance (lazy loaded)
_config: Optional[OpenCueConfig] = None


def get_config(config_path: Optional[str] = None) -> OpenCueConfig:
    """Get or create the global config instance"""
    global _config
    if _config is None:
        _config = OpenCueConfig.load(config_path)
    return _config
