#!/usr/bin/env python3
"""
UE Render Task Script - Bridge between OpenCue RQD and the local Worker Pool.

This script is executed by RQD (OpenCue Render Queue Daemon) to submit
a render task to the local UE Worker Pool and wait for completion.

Usage:
    # Preferred (agent CLI):
    python -m src.ue_agent run-task --job-id <job_id> --level-sequence <path> [options]

    # Or run the module directly:
    python -m src.ue_agent.run_task --job-id <job_id> --level-sequence <path> [options]

The script:
1. Submits the task to the Worker Pool via POST /tasks
2. Polls for task completion via GET /tasks/{id}
3. Exits with appropriate exit code (0=success, 1=failure)
"""
import argparse
import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests

from .config import default_worker_pool_log_root

logger = logging.getLogger(__name__)


class WorkerPoolClient:
    """HTTP client for the Worker Pool service"""

    def __init__(self, base_url: str = "http://127.0.0.1:9100/"):
        self.base_url = base_url.rstrip("/")

    def create_task(
        self,
        job_id: str,
        level_sequence: str,
        map_path: str = "",
        movie_quality: int = 1,
        movie_format: str = "mp4",
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """Create a new render task, returns task_id"""
        url = f"{self.base_url}/tasks"
        payload = {
            "job_id": job_id,
            "level_sequence": level_sequence,
            "map_path": map_path,
            "movie_quality": movie_quality,
            "movie_format": movie_format,
            "extra_params": extra_params or {},
        }

        response = requests.post(url, json=payload)
        response.raise_for_status()

        data = response.json()
        return data["task_id"]

    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Get task status and details"""
        url = f"{self.base_url}/tasks/{task_id}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task"""
        url = f"{self.base_url}/tasks/{task_id}/cancel"
        response = requests.post(url)
        return response.status_code == 200

    def get_status(self) -> Dict[str, Any]:
        """Get worker pool status"""
        url = f"{self.base_url}/status"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()


def wait_for_task_completion(
    client: WorkerPoolClient,
    task_id: str,
    poll_interval: float = 5.0,
    timeout: float = 3600.0,
) -> Dict[str, Any]:
    """
    Poll for task completion.

    Args:
        client: WorkerPoolClient instance
        task_id: Task ID to monitor
        poll_interval: Seconds between polls
        timeout: Maximum time to wait

    Returns:
        Final task status dict

    Raises:
        TimeoutError: If task doesn't complete within timeout
    """
    start_time = time.time()
    last_progress = -1.0

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")

        try:
            task = client.get_task(task_id)
        except requests.RequestException as e:
            logger.warning(f"Failed to get task status: {e}")
            time.sleep(poll_interval)
            continue

        status = task.get("status", "unknown")
        progress = task.get("progress_percent", 0.0)
        eta = task.get("progress_eta_seconds", -1)

        # Log progress updates
        if progress != last_progress:
            if progress <= 1.0:
                phase = "rendering"
                pct = progress * 100
            else:
                phase = "encoding"
                pct = (progress - 1.0) * 100

            eta_str = f"ETA: {eta}s" if eta >= 0 else ""
            logger.info(f"Task {task_id}: {status} - {phase} {pct:.1f}% {eta_str}")
            last_progress = progress

        # Check terminal states
        if status == "completed":
            logger.info(f"Task {task_id} completed successfully")
            return task

        if status == "failed":
            error_msg = task.get("error_message", "Unknown error")
            logger.error(f"Task {task_id} failed: {error_msg}")
            return task

        if status == "canceled":
            logger.warning(f"Task {task_id} was canceled")
            return task

        time.sleep(poll_interval)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Submit UE render task to Worker Pool"
    )
    parser.add_argument(
        "--job-id",
        required=True,
        help="Job ID for tracking"
    )
    parser.add_argument(
        "--level-sequence",
        required=True,
        help="Level sequence asset path (e.g., /Game/Seqs/Seq1.Seq1)"
    )
    parser.add_argument(
        "--map-path",
        default="",
        help="Map asset path (optional)"
    )
    parser.add_argument(
        "--movie-quality",
        type=int,
        default=1,
        choices=[0, 1, 2, 3],
        help="Movie quality (0=LOW, 1=MEDIUM, 2=HIGH, 3=EPIC)"
    )
    parser.add_argument(
        "--movie-format",
        default="mp4",
        choices=["mp4", "mov"],
        help="Output format"
    )
    parser.add_argument(
        "--worker-pool-url",
        default="http://127.0.0.1:9100/",
        help="Worker Pool service URL"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        help="Maximum wait time in seconds"
    )
    parser.add_argument(
        "--extra-params",
        type=str,
        default="{}",
        help="Extra parameters as JSON string"
    )

    args = parser.parse_args(argv)

    log_root = Path(default_worker_pool_log_root())
    log_root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_root / "run_task.log", encoding="utf-8"),
        ],
        force=True,
    )

    # Parse extra params
    try:
        extra_params = json.loads(args.extra_params)
    except json.JSONDecodeError:
        logger.warning(f"Invalid extra_params JSON: {args.extra_params}")
        extra_params = {}

    client = WorkerPoolClient(args.worker_pool_url)

    # Check pool status
    try:
        status = client.get_status()
        logger.info(f"Worker Pool Status: {status}")
    except requests.RequestException as e:
        logger.error(f"Cannot connect to Worker Pool at {args.worker_pool_url}: {e}")
        return 1

    # Create task
    logger.info(f"Creating task for job {args.job_id}...")
    try:
        task_id = client.create_task(
            job_id=args.job_id,
            level_sequence=args.level_sequence,
            map_path=args.map_path,
            movie_quality=args.movie_quality,
            movie_format=args.movie_format,
            extra_params=extra_params,
        )
        logger.info(f"Task created: {task_id}")
    except requests.RequestException as e:
        logger.error(f"Failed to create task: {e}")
        return 1

    # Wait for completion
    try:
        result = wait_for_task_completion(
            client,
            task_id,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
        )

        if result.get("status") == "completed" and result.get("success"):
            logger.info(f"Render complete! Output: {result.get('video_directory')}")
            return 0
        else:
            error_msg = result.get("error_message", "Task did not complete successfully")
            logger.error(f"Render failed: {error_msg}")
            return 1

    except TimeoutError as e:
        logger.error(str(e))
        # Try to cancel the task
        client.cancel_task(task_id)
        return 1

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        client.cancel_task(task_id)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
