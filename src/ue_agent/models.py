"""
Data models for OpenCue UE Agent (worker pool / persistent workers).

Task and Worker state management with status transitions.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, field


class TaskStatus(str, Enum):
    """Task lifecycle status"""
    PENDING = "pending"      # Queued, waiting for worker
    ASSIGNED = "assigned"    # Assigned to worker, not yet started
    RUNNING = "running"      # Actively rendering
    COMPLETED = "completed"  # Successfully finished
    FAILED = "failed"        # Failed with error
    CANCELED = "canceled"    # Canceled by user


class WorkerStatus(str, Enum):
    """Worker process status"""
    STARTING = "starting"    # UE process launching
    IDLE = "idle"            # Ready for tasks
    BUSY = "busy"            # Processing a task
    STOPPING = "stopping"    # Graceful shutdown
    DEAD = "dead"            # Process terminated


@dataclass
class RenderTask:
    """
    A render task to be executed by a UE worker.

    Matches the FOpenCueTaskInfo structure in UE.
    """
    task_id: str
    job_id: str
    level_sequence: str
    map_path: str = ""
    movie_quality: int = 1  # 0=LOW, 1=MEDIUM, 2=HIGH, 3=EPIC
    movie_format: str = "mp4"
    extra_params: Dict[str, str] = field(default_factory=dict)

    # Status tracking
    status: TaskStatus = TaskStatus.PENDING
    assigned_worker_id: Optional[str] = None
    progress_percent: float = 0.0
    progress_eta_seconds: int = -1

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    assigned_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Results
    success: bool = False
    error_message: Optional[str] = None
    video_directory: Optional[str] = None

    @classmethod
    def create(
        cls,
        job_id: str,
        level_sequence: str,
        map_path: str = "",
        movie_quality: int = 1,
        movie_format: str = "mp4",
        extra_params: Optional[Dict[str, str]] = None,
    ) -> "RenderTask":
        """Create a new task with generated ID"""
        return cls(
            task_id=str(uuid.uuid4()),
            job_id=job_id,
            level_sequence=level_sequence,
            map_path=map_path,
            movie_quality=movie_quality,
            movie_format=movie_format,
            extra_params=extra_params or {},
        )

    def to_lease_dict(self) -> Dict[str, Any]:
        """Convert to dict for lease response (matches UE FOpenCueTaskInfo)"""
        return {
            "task_id": self.task_id,
            "job_id": self.job_id,
            "level_sequence": self.level_sequence,
            "map": self.map_path,
            "movie_quality": self.movie_quality,
            "movie_format": self.movie_format,
            "extra_params": self.extra_params,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Full serialization for API responses"""
        return {
            "task_id": self.task_id,
            "job_id": self.job_id,
            "level_sequence": self.level_sequence,
            "map_path": self.map_path,
            "movie_quality": self.movie_quality,
            "movie_format": self.movie_format,
            "extra_params": self.extra_params,
            "status": self.status.value,
            "assigned_worker_id": self.assigned_worker_id,
            "progress_percent": self.progress_percent,
            "progress_eta_seconds": self.progress_eta_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success": self.success,
            "error_message": self.error_message,
            "video_directory": self.video_directory,
        }


@dataclass
class Worker:
    """
    Represents a UE worker process.

    Tracks the worker's lifecycle and current task assignment.
    """
    worker_id: str
    status: WorkerStatus = WorkerStatus.STARTING

    # Process info
    process_id: Optional[int] = None
    host: str = "localhost"

    # Current task
    current_task_id: Optional[str] = None

    # Heartbeat tracking
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    heartbeat_count: int = 0

    # Lifecycle timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None

    # Stats
    tasks_completed: int = 0
    tasks_failed: int = 0

    @classmethod
    def create(cls, worker_id: Optional[str] = None) -> "Worker":
        """Create a new worker with generated ID"""
        return cls(
            worker_id=worker_id or str(uuid.uuid4()),
        )

    def update_heartbeat(self) -> None:
        """Update heartbeat timestamp"""
        self.last_heartbeat = datetime.utcnow()
        self.heartbeat_count += 1

    def is_alive(self, timeout_seconds: float = 30.0) -> bool:
        """Check if worker is still alive based on heartbeat"""
        if self.status in (WorkerStatus.STOPPING, WorkerStatus.DEAD):
            return False

        elapsed = (datetime.utcnow() - self.last_heartbeat).total_seconds()
        return elapsed < timeout_seconds

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API responses"""
        return {
            "worker_id": self.worker_id,
            "status": self.status.value,
            "process_id": self.process_id,
            "host": self.host,
            "current_task_id": self.current_task_id,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "heartbeat_count": self.heartbeat_count,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
        }


@dataclass
class TaskQueue:
    """
    Simple in-memory task queue with worker assignment.

    For production, this could be backed by Redis or a database.
    """
    _tasks: Dict[str, RenderTask] = field(default_factory=dict)
    _workers: Dict[str, Worker] = field(default_factory=dict)

    def add_task(self, task: RenderTask) -> None:
        """Add a task to the queue"""
        self._tasks[task.task_id] = task

    def get_task(self, task_id: str) -> Optional[RenderTask]:
        """Get task by ID"""
        return self._tasks.get(task_id)

    def get_pending_task(self) -> Optional[RenderTask]:
        """Get the oldest pending task"""
        pending = [
            t for t in self._tasks.values()
            if t.status == TaskStatus.PENDING
        ]
        if not pending:
            return None

        # Sort by created_at, oldest first
        pending.sort(key=lambda t: t.created_at)
        return pending[0]

    def assign_task_to_worker(self, task_id: str, worker_id: str) -> bool:
        """Assign a task to a worker"""
        task = self._tasks.get(task_id)
        worker = self._workers.get(worker_id)

        if not task or not worker:
            return False

        if task.status != TaskStatus.PENDING:
            return False

        task.status = TaskStatus.ASSIGNED
        task.assigned_worker_id = worker_id
        task.assigned_at = datetime.utcnow()

        worker.current_task_id = task_id
        worker.status = WorkerStatus.BUSY

        return True

    def complete_task(
        self,
        task_id: str,
        success: bool,
        video_directory: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """Mark a task as completed"""
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        task.success = success
        task.completed_at = datetime.utcnow()
        task.video_directory = video_directory
        task.error_message = error_message

        # Update worker
        if task.assigned_worker_id:
            worker = self._workers.get(task.assigned_worker_id)
            if worker:
                worker.current_task_id = None
                worker.status = WorkerStatus.IDLE
                if success:
                    worker.tasks_completed += 1
                else:
                    worker.tasks_failed += 1

        return True

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or assigned task"""
        task = self._tasks.get(task_id)
        if not task:
            return False

        if task.status not in (TaskStatus.PENDING, TaskStatus.ASSIGNED):
            return False

        task.status = TaskStatus.CANCELED
        task.completed_at = datetime.utcnow()

        # Free up worker if assigned
        if task.assigned_worker_id:
            worker = self._workers.get(task.assigned_worker_id)
            if worker:
                worker.current_task_id = None
                worker.status = WorkerStatus.IDLE

        return True

    def register_worker(self, worker: Worker) -> None:
        """Register a new worker"""
        self._workers[worker.worker_id] = worker

    def get_worker(self, worker_id: str) -> Optional[Worker]:
        """Get worker by ID"""
        return self._workers.get(worker_id)

    def get_idle_workers(self) -> list[Worker]:
        """Get all idle workers"""
        return [
            w for w in self._workers.values()
            if w.status == WorkerStatus.IDLE
        ]

    def get_all_tasks(self) -> list[RenderTask]:
        """Get all tasks"""
        return list(self._tasks.values())

    def get_all_workers(self) -> list[Worker]:
        """Get all workers"""
        return list(self._workers.values())

    def cleanup_dead_workers(self, timeout_seconds: float = 30.0) -> list[str]:
        """Mark workers with stale heartbeats as dead, return their IDs"""
        dead_ids = []
        for worker in self._workers.values():
            if worker.status not in (WorkerStatus.STOPPING, WorkerStatus.DEAD):
                if not worker.is_alive(timeout_seconds):
                    worker.status = WorkerStatus.DEAD
                    dead_ids.append(worker.worker_id)

                    # Re-queue any assigned task
                    if worker.current_task_id:
                        task = self._tasks.get(worker.current_task_id)
                        if task and task.status == TaskStatus.ASSIGNED:
                            task.status = TaskStatus.PENDING
                            task.assigned_worker_id = None
                            task.assigned_at = None

        return dead_ids
