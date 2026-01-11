"""
UE Worker Pool HTTP Service

FastAPI-based HTTP service providing the following APIs:
- POST /workers/{id}/ready     - Worker signals ready to accept tasks (STARTING -> IDLE)
- GET  /workers/{id}/lease     - Worker polls for task assignment
- POST /workers/{id}/heartbeat - Worker sends heartbeat
- POST /workers/{id}/done      - Worker reports task completion
- POST /tasks                  - Create a new render task
- GET  /tasks/{id}             - Get task status
- POST /tasks/{id}/cancel      - Cancel a task
- GET  /status                 - Pool status summary

Worker Lifecycle:
1. Python spawns UE process with worker_id -> status = STARTING
2. UE initializes and sends POST /workers/{id}/ready -> status = IDLE
3. UE polls GET /workers/{id}/lease to receive tasks -> status = BUSY when assigned
4. UE sends POST /workers/{id}/heartbeat periodically
5. UE sends POST /workers/{id}/done when task completes -> status = IDLE
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from .config import get_config
from .models import RenderTask, TaskStatus
from .ue_worker_pool import UEWorkerPool

logger = logging.getLogger(__name__)

# Global pool instance
_pool: Optional[UEWorkerPool] = None


def get_pool() -> UEWorkerPool:
    """Get the global worker pool instance"""
    global _pool
    if _pool is None:
        raise RuntimeError("Worker pool not initialized")
    return _pool


# Pydantic models for API
class CreateTaskRequest(BaseModel):
    """Request body for creating a new task"""
    job_id: str
    level_sequence: str
    map_path: str = ""
    movie_quality: int = 1
    movie_format: str = "mp4"
    extra_params: Optional[Dict[str, str]] = None


class HeartbeatRequest(BaseModel):
    """Request body for worker heartbeat"""
    status: Optional[str] = None
    task_id: Optional[str] = None


class TaskDoneRequest(BaseModel):
    """Request body for task completion"""
    task_id: str
    success: bool
    video_directory: Optional[str] = None
    error_message: Optional[str] = None


class TaskResponse(BaseModel):
    """Response for task info"""
    task_id: str
    job_id: str
    level_sequence: str
    map_path: str
    movie_quality: int
    movie_format: str
    status: str
    progress_percent: float
    progress_eta_seconds: int
    assigned_worker_id: Optional[str]
    success: bool
    error_message: Optional[str]
    video_directory: Optional[str]


class StatusResponse(BaseModel):
    """Response for pool status"""
    workers: Dict[str, int]
    tasks: Dict[str, int]


# Lifespan handler for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown"""
    global _pool

    config = get_config()
    _pool = UEWorkerPool(config.worker_pool)

    logger.info("Starting UE Worker Pool Service...")
    await _pool.start()

    yield

    logger.info("Shutting down UE Worker Pool Service...")
    await _pool.shutdown()


# Create FastAPI app
app = FastAPI(
    title="UE Worker Pool Service",
    description="HTTP API for managing UE render workers",
    version="0.1.0",
    lifespan=lifespan,
)


# ============== Worker APIs ==============

@app.get("/workers/{worker_id}/lease")
async def lease_task(worker_id: str):
    """
    Worker polls for a task lease.

    Returns:
        200 with task info if a task is available
        204 No Content if no tasks available
    """
    pool = get_pool()
    task = pool.try_lease_task(worker_id)

    if task is None:
        return Response(status_code=204)

    return task.to_lease_dict()


@app.post("/workers/{worker_id}/heartbeat")
async def worker_heartbeat(worker_id: str, request: HeartbeatRequest):
    """
    Worker sends heartbeat.

    Updates the worker's last-seen timestamp and optionally status.
    """
    pool = get_pool()

    if not pool.update_worker_heartbeat(worker_id, request.status):
        raise HTTPException(status_code=404, detail="Worker not found")

    return {"status": "ok"}


@app.post("/workers/{worker_id}/ready")
async def worker_ready(worker_id: str):
    """
    Worker signals it's ready to accept tasks.

    Called by UE after OpenCueWorkerSubsystem finishes initialization.
    Transitions the worker from STARTING to IDLE status.
    """
    pool = get_pool()

    if not pool.mark_worker_ready(worker_id):
        raise HTTPException(status_code=400, detail="Cannot mark worker as ready")

    return {"status": "ok"}


@app.post("/workers/{worker_id}/done")
async def task_done(worker_id: str, request: TaskDoneRequest):
    """
    Worker reports task completion.

    Marks the task as completed or failed and frees the worker.
    """
    pool = get_pool()

    success = pool.complete_task(
        worker_id=worker_id,
        task_id=request.task_id,
        success=request.success,
        video_directory=request.video_directory,
        error_message=request.error_message,
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to complete task")

    return {"status": "ok"}


# ============== Task APIs ==============

@app.post("/tasks", status_code=201)
async def create_task(request: CreateTaskRequest):
    """
    Create a new render task.

    The task is added to the queue and will be assigned to
    the next available worker.
    """
    pool = get_pool()

    task = RenderTask.create(
        job_id=request.job_id,
        level_sequence=request.level_sequence,
        map_path=request.map_path,
        movie_quality=request.movie_quality,
        movie_format=request.movie_format,
        extra_params=request.extra_params,
    )

    pool.add_task(task)

    return {"task_id": task.task_id, "status": task.status.value}


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get task status and details."""
    pool = get_pool()
    task = pool.get_task(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return task.to_dict()


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a pending or assigned task."""
    pool = get_pool()

    if not pool.cancel_task(task_id):
        raise HTTPException(status_code=400, detail="Cannot cancel task")

    return {"status": "canceled"}


@app.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    limit: int = 100,
):
    """List all tasks, optionally filtered by status."""
    pool = get_pool()
    tasks = pool.task_queue.get_all_tasks()

    if status:
        try:
            filter_status = TaskStatus(status)
            tasks = [t for t in tasks if t.status == filter_status]
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    # Sort by created_at descending
    tasks.sort(key=lambda t: t.created_at, reverse=True)

    return [t.to_dict() for t in tasks[:limit]]


# ============== Admin APIs ==============

@app.get("/status")
async def get_status():
    """Get pool status summary."""
    pool = get_pool()
    return pool.get_status()


@app.get("/workers")
async def list_workers():
    """List all workers."""
    pool = get_pool()
    workers = pool.task_queue.get_all_workers()
    return [w.to_dict() for w in workers]


@app.post("/workers/scale")
async def scale_workers(target: int):
    """Scale worker pool to target count."""
    pool = get_pool()
    await pool.scale_workers(target)
    return pool.get_status()


@app.delete("/workers/{worker_id}")
async def kill_worker(worker_id: str, graceful: bool = True):
    """Kill a specific worker."""
    pool = get_pool()

    if not await pool.kill_worker(worker_id, graceful):
        raise HTTPException(status_code=404, detail="Worker not found or already dead")

    return {"status": "ok"}


# ============== Health Check ==============

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# ============== Entry point for standalone run ==============

def run_service(host: str = "0.0.0.0", port: int = 9100):
    """Run the service with uvicorn"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UE Worker Pool Service")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9100, help="Port to bind to")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    run_service(args.host, args.port)
