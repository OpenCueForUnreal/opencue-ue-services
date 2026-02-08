#!/usr/bin/env python3
"""
One-shot OpenCue task runner.

Reads render_plan.json from a Windows local path, resolves task by CUE_IFRAME
(fallback: CUE_FRAME, or --task-index),
launches UnrealEditor-Cmd, and returns UE exit code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import get_config, default_one_shot_work_root

logger = logging.getLogger(__name__)

_RENDER_PROGRESS_RE = re.compile(
    r"\[OpenCueCmdExecutor\]\s*Render progress:\s*([0-9]+(?:\.[0-9]+)?)%",
    re.IGNORECASE,
)
_ENCODING_PROGRESS_RE = re.compile(
    r"\[OpenCueCmdExecutor\]\s*Encoding progress:\s*([0-9]+(?:\.[0-9]+)?)%",
    re.IGNORECASE,
)


def _parse_ue_progress_line(line: str) -> Optional[Tuple[str, float]]:
    render_match = _RENDER_PROGRESS_RE.search(line)
    if render_match:
        return "Rendering", float(render_match.group(1))

    encoding_match = _ENCODING_PROGRESS_RE.search(line)
    if encoding_match:
        return "Encoding", float(encoding_match.group(1))

    return None


class _CueFrameProgressReporter:
    def __init__(self) -> None:
        self._enabled = False
        self._frame = None
        self._job_pb2 = None
        self._last_stage = ""
        self._last_percent = -1.0
        self._last_update_ts = 0.0

        frame_id = os.getenv("CUE_FRAME_ID", "").strip()
        if not frame_id:
            return

        cuebot_hosts = os.getenv("CUEBOT_HOSTS", "").strip()
        if not cuebot_hosts:
            cuebot_host = os.getenv("CUEBOT_HOST", "").strip() or os.getenv("CUEBOT_HOSTNAME", "").strip()
            cuebot_port = os.getenv("CUEBOT_PORT", "").strip() or os.getenv("CUEBOT_GRPC_PORT", "").strip() or "8443"
            if cuebot_host:
                os.environ["CUEBOT_HOSTS"] = f"{cuebot_host}:{cuebot_port}"

        try:
            import opencue
            from opencue_proto import job_pb2

            self._frame = opencue.api.getFrame(frame_id)
            self._job_pb2 = job_pb2
            self._enabled = True
            logger.info("Cue progress sync enabled for frame: %s", frame_id)
        except Exception as exc:
            logger.warning("Cue progress sync disabled (unable to resolve frame): %s", exc)

    def report_from_line(self, line: str) -> None:
        parsed = _parse_ue_progress_line(line)
        if not parsed:
            return
        stage, percent = parsed
        self.report(stage, percent)

    def report(self, stage: str, percent: float) -> None:
        if not self._enabled or self._frame is None or self._job_pb2 is None:
            return

        normalized = max(0.0, min(100.0, float(percent)))
        now = time.monotonic()

        if (
            stage == self._last_stage
            and self._last_percent >= 0.0
            and abs(normalized - self._last_percent) < 0.5
            and (now - self._last_update_ts) < 2.0
        ):
            return

        text = f"{stage} {normalized:.1f}%"
        try:
            self._frame.setFrameStateDisplayOverride(
                self._job_pb2.RUNNING,
                text,
                (80, 170, 255),
            )
            self._last_stage = stage
            self._last_percent = normalized
            self._last_update_ts = now
        except Exception as exc:
            logger.warning("Cue progress sync disabled (update failed): %s", exc)
            self._enabled = False


class _UELogTailer:
    def __init__(self, path: Path, on_line) -> None:
        self._path = path
        self._on_line = on_line
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="ue-log-tailer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        position = 0
        while not self._stop_event.is_set():
            if not self._path.exists():
                time.sleep(0.2)
                continue
            try:
                with self._path.open("r", encoding="utf-8", errors="replace") as stream:
                    stream.seek(position)
                    while not self._stop_event.is_set():
                        line = stream.readline()
                        if line:
                            position = stream.tell()
                            self._on_line(line)
                            continue

                        time.sleep(0.2)
                        try:
                            if self._path.stat().st_size < position:
                                break
                        except OSError:
                            break
            except Exception:
                time.sleep(0.5)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fail(message: str) -> int:
    logger.error(message)
    return 1


def _resolve_plan_path(plan_path: str) -> Path:
    return Path(plan_path)


def _verify_sha256(path: Path, expected: str) -> None:
    if not expected:
        return

    digest = hashlib.sha256(path.read_bytes()).hexdigest().lower()
    if digest != expected.lower():
        raise RuntimeError(f"plan_sha256 mismatch. expected={expected} actual={digest}")


def _task_index(explicit: Optional[int]) -> int:
    if explicit is not None:
        return explicit

    iframe_value = os.getenv("CUE_IFRAME", "").strip()
    if iframe_value:
        try:
            return int(iframe_value)
        except ValueError:
            pass

    value = os.getenv("CUE_FRAME", "").strip()
    if not value:
        raise RuntimeError("CUE_IFRAME/CUE_FRAME is not set. OpenCue must provide task index.")

    if "-" in value:
        prefix = value.split("-", 1)[0].strip()
        if prefix.isdigit():
            return int(prefix)
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid task index env (CUE_IFRAME='{iframe_value}', CUE_FRAME='{value}')."
        ) from exc


def _uproject_hint(plan: Dict[str, Any]) -> str:
    project = plan.get("project") or {}
    hint = project.get("uproject_hint")
    return str(hint or "").strip()


def _resolve_uproject(explicit: str, plan: Dict[str, Any]) -> Tuple[Optional[Path], List[str]]:
    cfg = get_config().worker_pool
    hint = _uproject_hint(plan)
    candidates: List[str] = []

    if explicit:
        candidates.append(explicit)
    env_uproject = os.getenv("UE_UPROJECT", "").strip()
    if env_uproject:
        candidates.append(env_uproject)
    if cfg.uproject:
        candidates.append(cfg.uproject)

    if hint:
        candidates.append(hint)
        project_root = os.getenv("UE_PROJECT_ROOT", "").strip()
        if project_root:
            candidates.append(str(Path(project_root) / hint))

    for c in candidates:
        p = Path(c)
        if p.exists():
            return p, candidates

    return None, candidates


def _cmd_from_root(root_or_cmd: str) -> Optional[Path]:
    if not root_or_cmd:
        return None
    p = Path(root_or_cmd)
    if p.suffix.lower() == ".exe":
        return p
    return p / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"


def _resolve_ue_cmd(explicit_cmd: str, explicit_root: str) -> Tuple[Optional[Path], List[str]]:
    cfg = get_config().worker_pool
    env_cmd = os.getenv("UE_CMD_PATH", "").strip()
    env_root = os.getenv("UE_ROOT", "").strip()

    candidates: List[str] = []
    if explicit_cmd:
        candidates.append(explicit_cmd)
    if env_cmd:
        candidates.append(env_cmd)

    for root_value in (explicit_root, env_root, cfg.ue_root):
        cmd = _cmd_from_root(root_value)
        if cmd is not None:
            candidates.append(str(cmd))

    for c in candidates:
        p = Path(c)
        if p.exists():
            return p, candidates

    return None, candidates


def _headless_enabled() -> bool:
    value = os.getenv("UE_WRAPPER_HEADLESS", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _build_ue_args(plan: Dict[str, Any], task: Dict[str, Any], ue_log_path: Path) -> List[str]:
    render = plan.get("render") or {}
    map_url = str(plan.get("map_asset_path") or "").strip()
    game_mode_class = str(render.get("game_mode_class") or "").strip()
    if map_url and game_mode_class:
        if "?game=" not in map_url.lower():
            if map_url.endswith("?"):
                map_url = f"{map_url}game={game_mode_class}"
            else:
                map_url = f"{map_url}?game={game_mode_class}"

    args: List[str] = [
        map_url,
        f"-AbsLog={ue_log_path}",
        "-forcelogflush",
        "-stdout",
        "-FullStdOutLogOutput",
        "-game",
        f"-MoviePipelineLocalExecutorClass={plan.get('executor_class')}",
        f"-JobId={plan.get('job_id')}",
        f"-LevelSequence={plan.get('level_sequence_asset_path')}",
        f"-MovieQuality={render.get('quality', 1)}",
        f"-MovieFormat={render.get('format', 'mp4')}",
    ]

    if _headless_enabled():
        args += [
            "-RenderOffscreen",
            "-Unattended",
            "-NOSPLASH",
            "-NoLoadingScreen",
            "-notexturestreaming",
        ]
    else:
        logger.info("Headless args disabled by UE_WRAPPER_HEADLESS=%s", os.getenv("UE_WRAPPER_HEADLESS"))

    extensions = task.get("extensions") or {}
    disable_shot_filter = bool(extensions.get("disable_shot_filter", False))
    shot = task.get("shot") or {}
    shot_name = shot.get("name")
    if not disable_shot_filter and shot_name:
        args.append(f"-ShotName={shot_name}")

    frame_range = task.get("frame_range") or {}
    start = frame_range.get("start")
    end = frame_range.get("end")
    if start is not None and end is not None:
        args.append(f"-CustomStartFrame={start}")
        args.append(f"-CustomEndFrame={end}")

    for extra in render.get("additional_ue_args") or []:
        extra_text = str(extra).strip()
        if extra_text:
            args.append(extra_text)

    return args


def _write_runtime_json(
    runtime_path: Path,
    plan: Dict[str, Any],
    task: Dict[str, Any],
    plan_path: Path,
    uproject_path: Path,
    ue_cmd: Path,
    ue_log_path: Path,
    ue_args: List[str],
    start_time: str,
    end_time: str,
    exit_code: int,
) -> None:
    runtime = {
        "job_id": plan.get("job_id"),
        "task_index": task.get("task_index"),
        "shot_name": (task.get("shot") or {}).get("name"),
        "frame_range": task.get("frame_range"),
        "plan_path": str(plan_path),
        "uproject": str(uproject_path),
        "ue_cmd": str(ue_cmd),
        "ue_log_path": str(ue_log_path),
        "ue_args": ue_args,
        "start_time": start_time,
        "end_time": end_time,
        "exit_code": exit_code,
    }
    runtime_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")


def run_one_shot_plan(
    plan_path_arg: str,
    plan_sha256: str,
    work_root: Path,
    uproject_path_arg: str,
    ue_cmd_path_arg: str,
    ue_root_arg: str,
    task_index_arg: Optional[int],
) -> int:
    task_index = _task_index(task_index_arg)
    work_root.mkdir(parents=True, exist_ok=True)

    plan_path = _resolve_plan_path(plan_path_arg)
    if not plan_path.exists():
        return _fail(f"render_plan.json not found at: {plan_path}")

    try:
        _verify_sha256(plan_path, plan_sha256)
    except Exception as exc:
        return _fail(str(exc))

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _fail(f"Failed to parse render_plan.json: {exc}")

    tasks = plan.get("tasks") or []
    task = next((t for t in tasks if int(t.get("task_index", -1)) == task_index), None)
    if task is None:
        return _fail(f"No task found for task_index={task_index}.")

    uproject_path, uproject_candidates = _resolve_uproject(uproject_path_arg, plan)
    if uproject_path is None:
        return _fail(
            "UProject not found. Checked candidates: "
            + ", ".join(uproject_candidates if uproject_candidates else ["<none>"])
        )

    ue_cmd_path, ue_cmd_candidates = _resolve_ue_cmd(ue_cmd_path_arg, ue_root_arg)
    if ue_cmd_path is None:
        return _fail(
            "UnrealEditor-Cmd.exe not found. Checked candidates: "
            + ", ".join(ue_cmd_candidates if ue_cmd_candidates else ["<none>"])
        )

    log_dir = work_root / str(plan.get("job_id", "unknown_job"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"task_{task_index}.log"
    ue_log_path = log_dir / f"task_{task_index}.ue.log"
    runtime_path = log_dir / f"task_{task_index}.runtime.json"

    ue_args = _build_ue_args(plan, task, ue_log_path)
    launch_cmd = [str(ue_cmd_path), str(uproject_path), *ue_args]

    logger.info("UE Cmd: %s", ue_cmd_path)
    logger.info("UE Args: %s", " ".join(ue_args))

    start_time = _now_iso()
    exit_code = 1
    progress_reporter = _CueFrameProgressReporter()
    ue_log_tailer = _UELogTailer(ue_log_path, progress_reporter.report_from_line)

    try:
        ue_log_tailer.start()
        with log_path.open("w", encoding="utf-8", newline="") as log_file:
            process = subprocess.Popen(
                launch_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            assert process.stdout is not None
            for line in process.stdout:
                sys.stdout.write(line)
                log_file.write(line)
                progress_reporter.report_from_line(line)
            exit_code = process.wait()
    except Exception as exc:
        logger.exception("Failed to launch UE command: %s", exc)
        exit_code = 1
    finally:
        ue_log_tailer.stop()

    end_time = _now_iso()

    try:
        _write_runtime_json(
            runtime_path=runtime_path,
            plan=plan,
            task=task,
            plan_path=plan_path,
            uproject_path=uproject_path,
            ue_cmd=ue_cmd_path,
            ue_log_path=ue_log_path,
            ue_args=ue_args,
            start_time=start_time,
            end_time=end_time,
            exit_code=exit_code,
        )
    except Exception:
        logger.exception("Failed to write runtime json: %s", runtime_path)

    logger.info("Exit code: %s", exit_code)
    return exit_code


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one OpenCue render task from a local render_plan.json")
    parser.add_argument("--plan-path", required=True, help="Windows local path to render_plan.json")
    parser.add_argument("--plan-sha256", default="", help="Optional SHA256 checksum for render_plan")
    parser.add_argument("--work-root", default=os.getenv("WORK_ROOT", default_one_shot_work_root()))
    parser.add_argument("--uproject-path", default="", help="Optional explicit .uproject path")
    parser.add_argument("--ue-cmd-path", default="", help="Optional explicit UnrealEditor-Cmd.exe path")
    parser.add_argument("--ue-root", default="", help="Optional UE root or UnrealEditor-Cmd.exe path")
    parser.add_argument(
        "--task-index",
        type=int,
        default=None,
        help="Override task index (defaults to CUE_IFRAME, fallback CUE_FRAME)",
    )
    args = parser.parse_args(argv)

    work_root = Path(args.work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(work_root / "runner.log", encoding="utf-8"),
        ],
        force=True,
    )

    return run_one_shot_plan(
        plan_path_arg=args.plan_path,
        plan_sha256=args.plan_sha256,
        work_root=work_root,
        uproject_path_arg=args.uproject_path,
        ue_cmd_path_arg=args.ue_cmd_path,
        ue_root_arg=args.ue_root,
        task_index_arg=args.task_index,
    )


if __name__ == "__main__":
    raise SystemExit(main())
