#!/usr/bin/env python3
"""
OpenCue Unified Launcher

Manages the lifecycle of all OpenCue + UE components:
- Cuebot (master role only)
- RQD (Render Queue Daemon)
- UE Worker Pool Service

Usage:
    # Master node (runs Cuebot + RQD + Worker Pool)
    python opencue_launcher.py start --role=master

    # Worker node (runs RQD + Worker Pool only)
    python opencue_launcher.py start --role=worker --cuebot=192.168.1.100:8443

    # Check status
    python opencue_launcher.py status

    # Stop all services
    python opencue_launcher.py stop
"""
import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("opencue_launcher")


class Role(str, Enum):
    MASTER = "master"
    WORKER = "worker"


@dataclass
class ServiceConfig:
    """Configuration for managed services"""
    # Paths
    cuebot_jar: str = ""
    rqd_executable: str = ""

    # Cuebot
    cuebot_host: str = "localhost"
    cuebot_port: int = 8443
    cuebot_db_host: str = "localhost"
    cuebot_db_port: int = 5432
    cuebot_db_name: str = "cuebot"
    cuebot_db_user: str = "cuebot"
    cuebot_db_pass: str = ""

    # Worker Pool
    worker_pool_port: int = 9100

    # Paths
    log_dir: str = "./logs"
    pid_dir: str = "./pids"

    @classmethod
    def from_json(cls, path: str) -> "ServiceConfig":
        """Load config from JSON file"""
        with open(path, "r") as f:
            data = json.load(f)
        return cls(**data.get("launcher", {}))

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        """Load config from environment variables"""
        return cls(
            cuebot_jar=os.getenv("CUEBOT_JAR", ""),
            rqd_executable=os.getenv("RQD_EXECUTABLE", "rqd"),
            cuebot_host=os.getenv("CUEBOT_HOST", "localhost"),
            cuebot_port=int(os.getenv("CUEBOT_PORT", "8443")),
            cuebot_db_host=os.getenv("CUEBOT_DB_HOST", "localhost"),
            cuebot_db_port=int(os.getenv("CUEBOT_DB_PORT", "5432")),
            cuebot_db_name=os.getenv("CUEBOT_DB_NAME", "cuebot"),
            cuebot_db_user=os.getenv("CUEBOT_DB_USER", "cuebot"),
            cuebot_db_pass=os.getenv("CUEBOT_DB_PASS", ""),
            worker_pool_port=int(os.getenv("WORKER_POOL_PORT", "9100")),
            log_dir=os.getenv("LOG_DIR", "./logs"),
            pid_dir=os.getenv("PID_DIR", "./pids"),
        )


class ServiceManager:
    """Manages the lifecycle of OpenCue services"""

    def __init__(self, config: ServiceConfig, role: Role, cuebot_addr: Optional[str] = None):
        self.config = config
        self.role = role
        self.cuebot_addr = cuebot_addr or f"{config.cuebot_host}:{config.cuebot_port}"
        self._processes: Dict[str, subprocess.Popen] = {}
        self._shutdown = False

        # Ensure directories exist
        Path(config.log_dir).mkdir(parents=True, exist_ok=True)
        Path(config.pid_dir).mkdir(parents=True, exist_ok=True)

    def _write_pid(self, name: str, pid: int) -> None:
        """Write PID file"""
        pid_file = Path(self.config.pid_dir) / f"{name}.pid"
        pid_file.write_text(str(pid))

    def _read_pid(self, name: str) -> Optional[int]:
        """Read PID file"""
        pid_file = Path(self.config.pid_dir) / f"{name}.pid"
        if pid_file.exists():
            try:
                return int(pid_file.read_text().strip())
            except ValueError:
                return None
        return None

    def _remove_pid(self, name: str) -> None:
        """Remove PID file"""
        pid_file = Path(self.config.pid_dir) / f"{name}.pid"
        if pid_file.exists():
            pid_file.unlink()

    def _start_process(
        self,
        name: str,
        cmd: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> subprocess.Popen:
        """Start a subprocess"""
        log_file = Path(self.config.log_dir) / f"{name}.log"

        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        logger.info(f"Starting {name}: {' '.join(cmd[:3])}...")

        with open(log_file, "w") as log_f:
            process = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                env=full_env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

        self._processes[name] = process
        self._write_pid(name, process.pid)
        logger.info(f"{name} started with PID {process.pid}")

        return process

    def start_cuebot(self) -> Optional[subprocess.Popen]:
        """Start Cuebot (master role only)"""
        if self.role != Role.MASTER:
            logger.info("Skipping Cuebot (not master role)")
            return None

        if not self.config.cuebot_jar:
            logger.warning("CUEBOT_JAR not set, skipping Cuebot")
            return None

        cmd = [
            "java",
            "-jar", self.config.cuebot_jar,
            f"--server.port={self.config.cuebot_port}",
            f"--datasource.cue-data-source.jdbc-url=jdbc:postgresql://{self.config.cuebot_db_host}:{self.config.cuebot_db_port}/{self.config.cuebot_db_name}",
            f"--datasource.cue-data-source.username={self.config.cuebot_db_user}",
        ]

        if self.config.cuebot_db_pass:
            cmd.append(f"--datasource.cue-data-source.password={self.config.cuebot_db_pass}")

        return self._start_process("cuebot", cmd)

    def start_rqd(self) -> Optional[subprocess.Popen]:
        """Start RQD (Render Queue Daemon)"""
        if not self.config.rqd_executable:
            logger.warning("RQD_EXECUTABLE not set, skipping RQD")
            return None

        env = {
            "CUEBOT_HOSTNAME": self.cuebot_addr.split(":")[0],
        }

        cmd = [self.config.rqd_executable]

        return self._start_process("rqd", cmd, env)

    def start_worker_pool(self) -> subprocess.Popen:
        """Start UE Worker Pool Service"""
        # Run the worker service as a Python module
        cmd = [
            sys.executable,
            "-m", "src.ue_worker_service",
            "--host", "0.0.0.0",
            "--port", str(self.config.worker_pool_port),
        ]

        return self._start_process("worker_pool", cmd)

    def start_all(self) -> None:
        """Start all services"""
        logger.info(f"Starting services (role={self.role.value})...")

        # Start in order: Cuebot -> RQD -> Worker Pool
        if self.role == Role.MASTER:
            self.start_cuebot()
            time.sleep(5)  # Wait for Cuebot to initialize

        self.start_rqd()
        time.sleep(2)

        self.start_worker_pool()

        logger.info("All services started")

    def stop_process(self, name: str, graceful: bool = True) -> None:
        """Stop a single process"""
        process = self._processes.get(name)
        if not process:
            # Try to find by PID file
            pid = self._read_pid(name)
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM if graceful else signal.SIGKILL)
                    logger.info(f"Sent signal to {name} (PID {pid})")
                except ProcessLookupError:
                    pass
                self._remove_pid(name)
            return

        logger.info(f"Stopping {name}...")

        if graceful:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning(f"{name} did not exit gracefully, killing...")
                process.kill()
        else:
            process.kill()

        process.wait(timeout=5)
        del self._processes[name]
        self._remove_pid(name)
        logger.info(f"{name} stopped")

    def stop_all(self) -> None:
        """Stop all services"""
        logger.info("Stopping all services...")

        # Stop in reverse order
        for name in ["worker_pool", "rqd", "cuebot"]:
            try:
                self.stop_process(name)
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")

        logger.info("All services stopped")

    def get_status(self) -> Dict[str, str]:
        """Get status of all services"""
        status = {}

        for name in ["cuebot", "rqd", "worker_pool"]:
            process = self._processes.get(name)
            if process:
                if process.poll() is None:
                    status[name] = f"running (PID {process.pid})"
                else:
                    status[name] = f"exited ({process.returncode})"
            else:
                pid = self._read_pid(name)
                if pid:
                    try:
                        os.kill(pid, 0)  # Check if process exists
                        status[name] = f"running (PID {pid})"
                    except ProcessLookupError:
                        status[name] = "dead (stale PID)"
                else:
                    status[name] = "stopped"

        return status

    def monitor(self) -> None:
        """Monitor services and restart if needed"""
        logger.info("Starting service monitor (Ctrl+C to stop)...")

        def signal_handler(signum, frame):
            self._shutdown = True
            logger.info("Shutdown signal received")

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        while not self._shutdown:
            for name, process in list(self._processes.items()):
                if process.poll() is not None:
                    logger.warning(f"{name} exited with code {process.returncode}")

                    # Attempt restart
                    if not self._shutdown:
                        logger.info(f"Restarting {name}...")
                        del self._processes[name]

                        if name == "cuebot":
                            self.start_cuebot()
                        elif name == "rqd":
                            self.start_rqd()
                        elif name == "worker_pool":
                            self.start_worker_pool()

            time.sleep(5)

        self.stop_all()


def cmd_start(args):
    """Handle 'start' command"""
    role = Role(args.role)

    config_path = args.config
    if config_path and Path(config_path).exists():
        config = ServiceConfig.from_json(config_path)
    else:
        config = ServiceConfig.from_env()

    manager = ServiceManager(config, role, args.cuebot)

    try:
        manager.start_all()

        if args.foreground:
            manager.monitor()
        else:
            # Daemon mode - just print status and exit
            status = manager.get_status()
            for name, state in status.items():
                print(f"{name}: {state}")

    except KeyboardInterrupt:
        logger.info("Interrupted")
        manager.stop_all()


def cmd_stop(args):
    """Handle 'stop' command"""
    config_path = args.config
    if config_path and Path(config_path).exists():
        config = ServiceConfig.from_json(config_path)
    else:
        config = ServiceConfig.from_env()

    manager = ServiceManager(config, Role.WORKER)  # Role doesn't matter for stop
    manager.stop_all()


def cmd_status(args):
    """Handle 'status' command"""
    config_path = args.config
    if config_path and Path(config_path).exists():
        config = ServiceConfig.from_json(config_path)
    else:
        config = ServiceConfig.from_env()

    manager = ServiceManager(config, Role.WORKER)
    status = manager.get_status()

    print("Service Status:")
    print("-" * 40)
    for name, state in status.items():
        print(f"  {name}: {state}")

    # Try to get Worker Pool status
    try:
        import requests
        response = requests.get(f"http://127.0.0.1:{config.worker_pool_port}/status", timeout=2)
        if response.status_code == 200:
            pool_status = response.json()
            print("\nWorker Pool Details:")
            print(f"  Workers: {pool_status.get('workers', {})}")
            print(f"  Tasks: {pool_status.get('tasks', {})}")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="OpenCue Unified Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start as master (Cuebot + RQD + Worker Pool)
  python opencue_launcher.py start --role=master

  # Start as worker (RQD + Worker Pool only)
  python opencue_launcher.py start --role=worker --cuebot=192.168.1.100:8443

  # Start in foreground with monitoring
  python opencue_launcher.py start --role=master --foreground

  # Check status
  python opencue_launcher.py status

  # Stop all services
  python opencue_launcher.py stop
"""
    )

    parser.add_argument(
        "--config",
        help="Path to JSON config file"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Start command
    start_parser = subparsers.add_parser("start", help="Start services")
    start_parser.add_argument(
        "--role",
        choices=["master", "worker"],
        default="worker",
        help="Node role (master runs Cuebot)"
    )
    start_parser.add_argument(
        "--cuebot",
        help="Cuebot address (host:port) for worker mode"
    )
    start_parser.add_argument(
        "--foreground", "-f",
        action="store_true",
        help="Run in foreground with monitoring"
    )
    start_parser.set_defaults(func=cmd_start)

    # Stop command
    stop_parser = subparsers.add_parser("stop", help="Stop services")
    stop_parser.set_defaults(func=cmd_stop)

    # Status command
    status_parser = subparsers.add_parser("status", help="Show status")
    status_parser.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
