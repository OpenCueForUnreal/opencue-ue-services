"""
UE Worker Pool Manager (OpenCue UE Agent).

Manages a pool of persistent Unreal Engine processes for rendering.
Workers are long-lived and poll for tasks via HTTP.
"""
import asyncio
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

import psutil

from .config import WorkerPoolConfig, get_config
from .models import Worker, WorkerStatus, RenderTask, TaskQueue, TaskStatus

logger = logging.getLogger(__name__)


# ======================== Process Management Constants ========================

# Startup grace period: don't check heartbeat timeout during UE startup
# After this period, worker must have sent at least one heartbeat
WORKER_STARTUP_GRACE_SEC = 300.0

# Heartbeat timeout for running workers: after startup grace, this is the timeout
WORKER_HEARTBEAT_TIMEOUT_SEC = 60.0

# Startup timeout: if worker never becomes ready after this time, mark as dead
WORKER_STARTUP_TIMEOUT_SEC = 300.0

# Background reconcile interval to detect crashed workers and respawn
WORKER_RECONCILE_INTERVAL_SEC = 10.0


def get_local_ip() -> str:
    """Get the local IP address for worker naming"""
    try:
        # Connect to an external address to get local IP (doesn't actually send data)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def kill_tree(pid: int) -> None:
    """Kill a process and all its children (process tree)"""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)

        # Kill children first
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass

        # Then kill parent
        try:
            parent.kill()
            parent.wait(timeout=5)
        except psutil.NoSuchProcess:
            pass

    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        logger.warning(f"Error killing process tree {pid}: {e}")


def is_process_running(pid: int) -> bool:
    """Check if a process is still running"""
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


class UEWorkerPool:
    """
    Manages a pool of UE worker processes.

    Each worker runs with -MRQWorkerMode flag and polls the HTTP service
    for render tasks via GET /workers/{id}/lease

    Features:
    - Automatic worker spawning to maintain min_workers
    - Heartbeat monitoring with grace period for startup
    - Process tree killing for clean termination
    - Orphan process cleanup on startup
    - Round-robin task distribution across workers
    """

    def __init__(self, config: Optional[WorkerPoolConfig] = None):
        self.config = config or get_config().worker_pool
        self.task_queue = TaskQueue()
        self._processes: Dict[str, subprocess.Popen] = {}
        self._shutdown_event = asyncio.Event()
        self._monitor_task: Optional[asyncio.Task] = None

        # Worker spawn tracking
        self._spawn_times: Dict[str, float] = {}  # worker_id -> spawn timestamp
        self._worker_index: int = 0  # Counter for worker naming
        self._host_ip: str = get_local_ip()

        # Log directory
        self._log_dir = Path(self.config.log_root)

    def _generate_worker_id(self) -> str:
        """Generate a worker ID with host IP and index for easy debugging"""
        # Format: 192.168.1.100-w0, 192.168.1.100-w1, etc.
        worker_id = f"{self._host_ip}-w{self._worker_index}"
        self._worker_index += 1
        return worker_id

    def get_ue_editor_cmd(self) -> str:
        """Get the UE Editor command line executable path"""
        ue_root = Path(self.config.ue_root)

        # Windows
        win_path = ue_root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
        if win_path.exists():
            return str(win_path)

        # Linux
        linux_path = ue_root / "Engine" / "Binaries" / "Linux" / "UnrealEditor-Cmd"
        if linux_path.exists():
            return str(linux_path)

        raise FileNotFoundError(f"UnrealEditor-Cmd not found in {ue_root}")

    def build_worker_command(self, worker: Worker) -> List[str]:
        """Build command line arguments for launching a UE worker"""
        ue_cmd = self.get_ue_editor_cmd()

        # Log file path
        log_path = self._log_dir / f"worker_{worker.worker_id}.log"

        cmd = [
            ue_cmd,
            self.config.uproject,
            # Worker mode flags (matching UE's OpenCueWorkerSubsystem)
            "-MRQWorkerMode",
            f"-MRQWorkerId={worker.worker_id}",
            f"-WorkerPoolBaseUrl=http://127.0.0.1:{self.config.port}/",
            f"-MoviePipelineLocalExecutorClass={self.config.executor_class}",
            # Editor headless flags
            "-Unattended",
            "-NoLoadingScreen",
            "-notexturestreaming",
            "-stdout",
            f"-ABSLOG={str(log_path.absolute())}",
        ]

        return cmd

    async def spawn_worker(self, worker_id: Optional[str] = None) -> Worker:
        """
        Spawn a new UE worker process.

        Uses optimistic startup strategy:
        - Workers start as IDLE and are immediately available for jobs
        - If UE hasn't fully initialized when it receives a job, UE-side lease polling will wait
        - Heartbeat mechanism provides health monitoring
        """
        # Generate worker ID with IP+index if not provided
        wid = worker_id or self._generate_worker_id()

        worker = Worker.create(wid)
        worker.host = self._host_ip
        self.task_queue.register_worker(worker)

        cmd = self.build_worker_command(worker)

        # Ensure log directory exists
        self._log_dir.mkdir(parents=True, exist_ok=True)

        log_file = self._log_dir / f"worker_{worker.worker_id}.log"

        try:
            # Disable proxy for localhost connections - UE inherits system proxy settings
            spawn_env = os.environ.copy()
            spawn_env["NO_PROXY"] = "localhost,127.0.0.1"

            with open(log_file, "w") as log_f:
                process = subprocess.Popen(
                    cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    env=spawn_env,
                    # Don't create a new console window on Windows
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )

            now = time.time()
            worker.process_id = process.pid
            worker.started_at = datetime.utcnow()
            # Conservative startup: worker stays STARTING until UE sends ready signal
            # This avoids assigning tasks to workers that failed to start
            worker.status = WorkerStatus.STARTING
            self._processes[worker.worker_id] = process
            self._spawn_times[worker.worker_id] = now

            cmd_str = subprocess.list2cmdline(cmd)
            logger.info("=" * 80)
            logger.info(f"[UE-WORKER-POOL] Spawned worker {wid} with PID {process.pid}")
            logger.info(f"[LOG-PATH] {log_file}")
            logger.info(f"[CMD] {cmd_str}")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"Failed to spawn worker {worker.worker_id}: {e}")
            worker.status = WorkerStatus.DEAD
            raise

        return worker

    async def kill_worker(self, worker_id: str, graceful: bool = True) -> bool:
        """Kill a worker process using process tree termination"""
        worker = self.task_queue.get_worker(worker_id)
        if not worker:
            return False

        process = self._processes.get(worker_id)
        pid = worker.process_id

        worker.status = WorkerStatus.STOPPING

        try:
            if pid:
                logger.info(f"Killing worker {worker_id} with PID {pid}")
                kill_tree(pid)

            if process:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass

            worker.status = WorkerStatus.DEAD
            worker.stopped_at = datetime.utcnow()

            # Cleanup
            if worker_id in self._processes:
                del self._processes[worker_id]
            if worker_id in self._spawn_times:
                del self._spawn_times[worker_id]

            logger.info(f"Worker {worker_id} terminated")
            return True

        except Exception as e:
            logger.error(f"Failed to kill worker {worker_id}: {e}")
            worker.status = WorkerStatus.DEAD
            return False

    def _cleanup_orphan_processes(self) -> None:
        """
        Clean up orphan UE worker processes from previous daemon runs.
        This handles cases where the daemon crashed but UE processes kept running.
        """
        needle_mode = "MRQWorkerMode"
        needle_url = f"-WorkerPoolBaseUrl=http://127.0.0.1:{self.config.port}/"

        killed = 0
        for proc in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                if not cmdline:
                    continue

                cmd_join = " ".join(cmdline)
                if needle_mode not in cmd_join:
                    continue
                if needle_url.lower() not in cmd_join.lower():
                    continue

                pid = int(proc.info["pid"])
                logger.info(f"Found orphan UE worker process {pid}, killing...")
                kill_tree(pid)
                killed += 1
            except Exception as e:
                logger.warning(f"Failed to check/kill process: {e}")

        if killed:
            logger.info(f"Cleaned up {killed} orphan UE worker processes")

    async def _reconcile(self) -> None:
        """
        Reconcile worker pool state:
        - Detect crashed/dead processes
        - Check heartbeat timeouts
        - Respawn workers to maintain min count
        """
        now = time.time()
        dead_ids: List[str] = []

        for worker_id, worker in list(self.task_queue._workers.items()):
            pid = worker.process_id
            spawn_time = self._spawn_times.get(worker_id, 0)
            age_since_spawn = now - spawn_time if spawn_time > 0 else float("inf")

            # Check if process died
            if pid and not is_process_running(pid):
                if worker.current_task_id:
                    logger.error(f"Worker {worker_id} died with bound task {worker.current_task_id}")
                else:
                    logger.warning(f"Worker {worker_id} died with no bound task")

                worker.process_id = None
                worker.status = WorkerStatus.DEAD
                worker.current_task_id = None
                dead_ids.append(worker_id)
                continue

            # Check heartbeat timeout (only after startup grace period)
            if worker.status in (WorkerStatus.IDLE, WorkerStatus.BUSY):
                if age_since_spawn >= WORKER_STARTUP_GRACE_SEC:
                    elapsed = (datetime.utcnow() - worker.last_heartbeat).total_seconds()
                    if elapsed > WORKER_HEARTBEAT_TIMEOUT_SEC:
                        logger.error(
                            f"Worker {worker_id} heartbeat timeout ({elapsed:.1f}s), "
                            f"task={worker.current_task_id}"
                        )
                        if pid:
                            kill_tree(pid)
                        worker.process_id = None
                        worker.status = WorkerStatus.DEAD
                        worker.current_task_id = None
                        dead_ids.append(worker_id)
                        continue

            # Check startup timeout (workers that never became ready)
            if worker.status == WorkerStatus.STARTING:
                if age_since_spawn > WORKER_STARTUP_TIMEOUT_SEC:
                    logger.error(f"Worker {worker_id} startup timeout ({age_since_spawn:.1f}s)")
                    if pid:
                        kill_tree(pid)
                    worker.process_id = None
                    worker.status = WorkerStatus.DEAD
                    dead_ids.append(worker_id)
                    continue

            # Mark as dead if no process
            if worker.process_id is None and worker.status != WorkerStatus.DEAD:
                worker.status = WorkerStatus.DEAD
                dead_ids.append(worker_id)

        # Re-queue tasks from dead workers
        for worker_id in dead_ids:
            worker = self.task_queue.get_worker(worker_id)
            if worker and worker.current_task_id:
                task = self.task_queue.get_task(worker.current_task_id)
                if task and task.status in (TaskStatus.ASSIGNED, TaskStatus.RUNNING):
                    task.status = TaskStatus.PENDING
                    task.assigned_worker_id = None
                    logger.info(f"Re-queued task {task.task_id} from dead worker {worker_id}")

            # Cleanup process tracking
            if worker_id in self._processes:
                del self._processes[worker_id]
            if worker_id in self._spawn_times:
                del self._spawn_times[worker_id]

        # Count live workers and respawn to maintain min
        live_workers = [
            w for w in self.task_queue.get_all_workers()
            if w.status in (WorkerStatus.IDLE, WorkerStatus.BUSY, WorkerStatus.STARTING)
        ]
        missing = self.config.min_workers - len(live_workers)

        # Prefer respawning with same IDs to keep stable worker identifiers
        for worker_id in dead_ids[:missing]:
            try:
                await self.spawn_worker(worker_id=worker_id)
                missing -= 1
            except Exception as e:
                logger.error(f"Failed to respawn worker {worker_id}: {e}")

        # Spawn new workers if still missing
        while missing > 0:
            try:
                await self.spawn_worker()
                missing -= 1
            except Exception as e:
                logger.error(f"Failed to spawn new worker: {e}")
                break

    async def _monitor_workers(self) -> None:
        """Background task to monitor worker health"""
        while not self._shutdown_event.is_set():
            try:
                await self._reconcile()
            except Exception as e:
                logger.error(f"Error in worker reconcile: {e}")

            await asyncio.sleep(WORKER_RECONCILE_INTERVAL_SEC)

    async def scale_workers(self, target_count: int) -> None:
        """Scale the worker pool to target count"""
        target_count = max(self.config.min_workers, min(target_count, self.config.max_workers))

        current_workers = [
            w for w in self.task_queue.get_all_workers()
            if w.status not in (WorkerStatus.DEAD, WorkerStatus.STOPPING)
        ]
        current_count = len(current_workers)

        if current_count < target_count:
            # Scale up
            for _ in range(target_count - current_count):
                try:
                    await self.spawn_worker()
                except Exception as e:
                    logger.error(f"Failed to spawn worker during scale-up: {e}")
                    break

        elif current_count > target_count:
            # Scale down (kill idle workers first)
            idle_workers = self.task_queue.get_idle_workers()
            to_kill = current_count - target_count

            for worker in idle_workers[:to_kill]:
                await self.kill_worker(worker.worker_id)

    async def start(self) -> None:
        """Start the worker pool"""
        logger.info(f"Starting UE Worker Pool (min={self.config.min_workers}, max={self.config.max_workers})")
        logger.info(f"Host IP: {self._host_ip}")

        # Cleanup orphan processes from previous runs
        self._cleanup_orphan_processes()

        # Spawn initial workers
        await self.scale_workers(self.config.min_workers)

        # Start monitor
        self._monitor_task = asyncio.create_task(self._monitor_workers())

    async def shutdown(self) -> None:
        """Shutdown the worker pool"""
        logger.info("Shutting down UE Worker Pool...")

        self._shutdown_event.set()

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # Kill all workers
        for worker_id in list(self._processes.keys()):
            await self.kill_worker(worker_id)

        logger.info("UE Worker Pool shutdown complete")

    # ======================== Task Management Methods ========================

    def add_task(self, task: RenderTask) -> None:
        """Add a task to the queue"""
        self.task_queue.add_task(task)
        logger.info(f"Task {task.task_id} added to queue (job={task.job_id})")

    def get_task(self, task_id: str) -> Optional[RenderTask]:
        """Get a task by ID"""
        return self.task_queue.get_task(task_id)

    def try_lease_task(self, worker_id: str) -> Optional[RenderTask]:
        """
        Try to lease a pending task to a worker.
        Returns the task if successful, None if no tasks available.

        Only IDLE workers can receive tasks. STARTING workers must call
        mark_worker_ready first.
        """
        worker = self.task_queue.get_worker(worker_id)
        if not worker:
            # Unknown worker trying to lease - reject
            # Workers must be registered via spawn_worker or mark_worker_ready
            logger.warning(f"Unknown worker {worker_id} trying to lease task")
            return None

        # Update heartbeat
        worker.update_heartbeat()

        # Only IDLE workers can receive tasks
        if worker.status != WorkerStatus.IDLE:
            return None

        # Find a pending task
        task = self.task_queue.get_pending_task()
        if not task:
            return None

        # Assign the task
        if self.task_queue.assign_task_to_worker(task.task_id, worker_id):
            logger.info(f"Leased task {task.task_id} to worker {worker_id}")
            return task

        return None

    def update_worker_heartbeat(self, worker_id: str, busy: Optional[bool] = None) -> bool:
        """Update worker heartbeat and optionally busy status"""
        worker = self.task_queue.get_worker(worker_id)
        if not worker:
            return False

        worker.update_heartbeat()

        # Update busy status if provided (only for IDLE/BUSY workers)
        if busy is not None and worker.status in (WorkerStatus.IDLE, WorkerStatus.BUSY):
            if busy and worker.status == WorkerStatus.IDLE:
                worker.status = WorkerStatus.BUSY
            elif not busy and worker.status == WorkerStatus.BUSY:
                worker.status = WorkerStatus.IDLE
                worker.current_task_id = None

        return True

    def mark_worker_ready(self, worker_id: str) -> bool:
        """
        Mark a STARTING worker as ready (IDLE).
        Called by UE when OpenCueWorkerSubsystem finishes initialization.

        Returns True if worker was successfully marked ready.
        """
        worker = self.task_queue.get_worker(worker_id)
        if not worker:
            # Auto-register unknown workers (for externally launched UE)
            worker = Worker.create(worker_id)
            worker.host = self._host_ip
            worker.status = WorkerStatus.IDLE
            self.task_queue.register_worker(worker)
            logger.info(f"Auto-registered external worker {worker_id} as ready")
            return True

        if worker.status == WorkerStatus.STARTING:
            worker.status = WorkerStatus.IDLE
            worker.update_heartbeat()
            logger.info(f"Worker {worker_id} is now ready (STARTING -> IDLE)")
            return True
        elif worker.status == WorkerStatus.IDLE:
            # Already ready, just update heartbeat
            worker.update_heartbeat()
            return True
        else:
            logger.warning(f"Worker {worker_id} cannot be marked ready, current status: {worker.status}")
            return False

    def complete_task(
        self,
        worker_id: str,
        task_id: str,
        success: bool,
        video_directory: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """Mark a task as completed by a worker"""
        worker = self.task_queue.get_worker(worker_id)
        if not worker:
            return False

        task = self.task_queue.get_task(task_id)
        if not task or task.assigned_worker_id != worker_id:
            return False

        result = self.task_queue.complete_task(
            task_id, success, video_directory, error_message
        )

        if result:
            status_str = "completed" if success else "failed"
            logger.info(f"Task {task_id} {status_str} by worker {worker_id}")

        return result

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task"""
        return self.task_queue.cancel_task(task_id)

    def get_status(self) -> Dict:
        """Get pool status summary"""
        workers = self.task_queue.get_all_workers()
        tasks = self.task_queue.get_all_tasks()

        return {
            "host_ip": self._host_ip,
            "workers": {
                "total": len(workers),
                "idle": len([w for w in workers if w.status == WorkerStatus.IDLE]),
                "busy": len([w for w in workers if w.status == WorkerStatus.BUSY]),
                "starting": len([w for w in workers if w.status == WorkerStatus.STARTING]),
                "dead": len([w for w in workers if w.status == WorkerStatus.DEAD]),
            },
            "tasks": {
                "total": len(tasks),
                "pending": len([t for t in tasks if t.status == TaskStatus.PENDING]),
                "assigned": len([t for t in tasks if t.status == TaskStatus.ASSIGNED]),
                "running": len([t for t in tasks if t.status == TaskStatus.RUNNING]),
                "completed": len([t for t in tasks if t.status == TaskStatus.COMPLETED]),
                "failed": len([t for t in tasks if t.status == TaskStatus.FAILED]),
            },
        }
