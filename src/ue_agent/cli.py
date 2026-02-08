#!/usr/bin/env python3
"""
CLI for the OpenCue UE Agent.

This is designed to be a stable entrypoint that can be packaged as an exe
later (eg. `opencue-ue-agent.exe`), while still being runnable in dev via:

  python -m src.ue_agent <command> [args...]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List, Optional


def _cmd_service(args: argparse.Namespace) -> int:
    from .config import get_config
    from .service import run_service

    log_root = Path(get_config().worker_pool.log_root)
    log_root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_root / "service.log", encoding="utf-8"),
        ],
        force=True,
    )

    run_service(host=args.host, port=args.port)
    return 0


def _cmd_run_task(args: argparse.Namespace) -> int:
    from .run_task import main as run_task_main

    argv: List[str] = []
    argv += ["--job-id", args.job_id]
    argv += ["--level-sequence", args.level_sequence]
    if args.map_path:
        argv += ["--map-path", args.map_path]
    argv += ["--movie-quality", str(args.movie_quality)]
    argv += ["--movie-format", args.movie_format]
    argv += ["--worker-pool-url", args.worker_pool_url]
    argv += ["--poll-interval", str(args.poll_interval)]
    argv += ["--timeout", str(args.timeout)]
    argv += ["--extra-params", args.extra_params]

    return run_task_main(argv)


def _cmd_run_one_shot_plan(args: argparse.Namespace) -> int:
    from .run_one_shot_plan import main as run_one_shot_plan_main

    argv: List[str] = []
    argv += ["--plan-path", args.plan_path]
    if args.plan_sha256:
        argv += ["--plan-sha256", args.plan_sha256]
    if args.work_root:
        argv += ["--work-root", args.work_root]
    if args.uproject_path:
        argv += ["--uproject-path", args.uproject_path]
    if args.ue_cmd_path:
        argv += ["--ue-cmd-path", args.ue_cmd_path]
    if args.ue_root:
        argv += ["--ue-root", args.ue_root]
    if args.task_index is not None:
        argv += ["--task-index", str(args.task_index)]

    return run_one_shot_plan_main(argv)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opencue-ue-agent",
        description="Execution-side tools for OpenCue + Unreal Engine integration",
    )

    subparsers = parser.add_subparsers(dest="command")

    service_parser = subparsers.add_parser("service", help="Run the UE worker pool service (persistent mode)")
    service_parser.add_argument("--host", default="0.0.0.0")
    service_parser.add_argument("--port", type=int, default=9100)
    service_parser.set_defaults(func=_cmd_service)

    run_task_parser = subparsers.add_parser("run-task", help="Submit a task to the local worker pool and wait (RQD entrypoint)")
    run_task_parser.add_argument("--job-id", required=True)
    run_task_parser.add_argument("--level-sequence", required=True)
    run_task_parser.add_argument("--map-path", default="")
    run_task_parser.add_argument("--movie-quality", type=int, default=1, choices=[0, 1, 2, 3])
    run_task_parser.add_argument("--movie-format", default="mp4", choices=["mp4", "mov"])
    run_task_parser.add_argument("--worker-pool-url", default="http://127.0.0.1:9100/")
    run_task_parser.add_argument("--poll-interval", type=float, default=5.0)
    run_task_parser.add_argument("--timeout", type=float, default=3600.0)
    run_task_parser.add_argument("--extra-params", type=str, default="{}")
    run_task_parser.set_defaults(func=_cmd_run_task)

    run_one_shot_plan_parser = subparsers.add_parser(
        "run-one-shot-plan",
        help="Run one plan task in one-shot mode (RQD entrypoint)",
    )
    run_one_shot_plan_parser.add_argument("--plan-path", required=True)
    run_one_shot_plan_parser.add_argument("--plan-sha256", default="")
    run_one_shot_plan_parser.add_argument("--work-root", default="")
    run_one_shot_plan_parser.add_argument("--uproject-path", default="")
    run_one_shot_plan_parser.add_argument("--ue-cmd-path", default="")
    run_one_shot_plan_parser.add_argument("--ue-root", default="")
    run_one_shot_plan_parser.add_argument("--task-index", type=int, default=None)
    run_one_shot_plan_parser.set_defaults(func=_cmd_run_one_shot_plan)

    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
