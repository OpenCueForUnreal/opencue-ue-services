"""
Core submission logic for OpenCue jobs.

Reads submit_spec.json and creates OpenCue jobs via PyOutline.
"""

import os
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


_CMD_EXE_PATTERN = re.compile(r'^(?:"([^"]+)"|(\S+))(.*)$')


def _normalize_layer_command(cmd: str) -> str:
    text = (cmd or "").strip()
    if not text:
        return text

    m = _CMD_EXE_PATTERN.match(text)
    if not m:
        return text

    exe = (m.group(1) or m.group(2) or "").strip()
    rest = m.group(3) or ""
    if not exe:
        return text

    exe_path = Path(exe)
    if not exe_path.is_absolute():
        candidate = (Path.cwd() / exe_path).resolve()
        if candidate.exists():
            return f'"{candidate}"{rest}'

    return text


@dataclass
class SubmitResult:
    """Result of a job submission attempt."""
    ok: bool
    job_id: Optional[str] = None
    opencue_job_ids: List[str] = field(default_factory=list)
    error: Optional[str] = None
    hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = {"ok": self.ok}
        if self.ok:
            if self.job_id:
                d["job_id"] = self.job_id
            if self.opencue_job_ids:
                d["opencue_job_ids"] = self.opencue_job_ids
        else:
            if self.error:
                d["error"] = self.error
            if self.hint:
                d["hint"] = self.hint
        return d


def _validate_spec(spec: Dict[str, Any]) -> Optional[str]:
    """
    Validate submit_spec against required fields.
    Returns error message if invalid, None if valid.
    """
    required_top = ["cuebot", "show", "user", "job", "plan", "opencue"]
    for key in required_top:
        if key not in spec:
            return f"Missing required field: {key}"

    # cuebot
    if "host" not in spec["cuebot"] or "port" not in spec["cuebot"]:
        return "cuebot must have 'host' and 'port'"

    # job
    if "name" not in spec["job"]:
        return "job must have 'name'"

    # plan
    if "plan_uri" not in spec["plan"]:
        return "plan must have 'plan_uri'"

    # opencue
    opencue = spec["opencue"]
    for key in ["layer_name", "task_count", "cmd"]:
        if key not in opencue:
            return f"opencue must have '{key}'"

    if opencue["task_count"] < 1:
        return "task_count must be >= 1"

    return None


def submit_job(spec: Dict[str, Any]) -> SubmitResult:
    """
    Submit a job to OpenCue based on submit_spec.

    Args:
        spec: Parsed submit_spec.json content

    Returns:
        SubmitResult with success/failure info
    """
    # Validate spec
    validation_error = _validate_spec(spec)
    if validation_error:
        return SubmitResult(
            ok=False,
            error=validation_error,
            hint="Check submit_spec.json against the schema."
        )

    # Set environment for OpenCue connection
    cuebot = spec["cuebot"]
    cuebot_host = cuebot["host"]
    cuebot_port = cuebot.get("port", 8443)
    cuebot_hostport = f"{cuebot_host}:{cuebot_port}"
    os.environ["CUEBOT_HOSTS"] = cuebot_hostport
    # Note: pycue uses CUEBOT_HOSTS env var

    try:
        # Import OpenCue libraries (deferred to allow graceful error handling)
        from outline import Outline
        from outline.cuerun import OutlineLauncher
        from outline.modules.shell import Shell
    except ImportError as e:
        return SubmitResult(
            ok=False,
            error=f"Failed to import OpenCue libraries: {e}",
            hint="Install dependencies: pip install -r opencue-ue-services/requirements.txt (ensure 'packaging' is installed too).",
        )

    try:
        # Extract spec fields
        show = spec["show"]
        if isinstance(show, str):
            show = show.strip().lower()
        user = spec["user"]
        job_name = spec["job"]["name"]
        job_comment = spec["job"].get("comment", "")
        job_priority = spec["job"].get("priority", 100)

        layer_name = spec["opencue"]["layer_name"]
        task_count = spec["opencue"]["task_count"]
        cmd = spec["opencue"]["cmd"]
        if isinstance(cmd, str):
            cmd = _normalize_layer_command(cmd)
        # outline serialize_simple joins command tokens; keep Windows command
        # as a single token to avoid per-character splitting.
        cmd_for_layer = [cmd] if isinstance(cmd, str) else cmd

        # Create Outline job
        # Frame range: "0-{task_count-1}" means task_count tasks (0, 1, 2, ..., task_count-1)
        # CUE_FRAME will be set to each value (0, 1, 2, ...) by RQD
        ol = Outline(job_name, show=show, user=user)

        if job_comment and hasattr(ol, "set_comment"):
            ol.set_comment(job_comment)
        if job_priority is not None and hasattr(ol, "set_priority"):
            ol.set_priority(job_priority)

        # Create Shell layer with the wrapper command
        # The command is called for each frame (task) with CUE_FRAME env var set
        render_layer = Shell(layer_name, command=cmd_for_layer)

        # Set frame range: 0 to task_count-1
        # This creates task_count tasks numbered 0, 1, 2, ..., task_count-1
        frame_range = f"0-{task_count - 1}"
        render_layer.set_frame_range(frame_range)
        render_layer.set_chunk_size(1)

        # Set resource requirements from services if provided
        services = spec["opencue"].get("services", {})
        if "cores" in services:
            try:
                render_layer.set_cores(int(services["cores"]))
            except Exception:
                render_layer.set_arg("cores", services["cores"])
        if "memory_gb" in services:
            # Memory is in KB for OpenCue
            try:
                memory_kb = int(services["memory_gb"] * 1024 * 1024)
            except Exception:
                memory_kb = services["memory_gb"]
            try:
                render_layer.set_memory(memory_kb)
            except Exception:
                render_layer.set_arg("memory", str(memory_kb))
        if "tags" in services:
            render_layer.set_arg("tags", services["tags"])

        # Add layer to outline
        ol.add_layer(render_layer)

        # Submit the job to OpenCue
        launcher = OutlineLauncher(ol)
        if job_priority is not None:
            try:
                launcher.set_flag("priority", int(job_priority))
            except Exception:
                pass
        # Windows execution should run layer command directly.
        # pycuerun wrapper scripts are not executable under cmd on Windows.
        jobs = launcher.launch(use_pycuerun=False)

        # Extract job IDs
        opencue_job_ids = []
        for job in jobs:
            try:
                # OpenCue job objects have id() or data.id
                if hasattr(job, 'id') and callable(job.id):
                    opencue_job_ids.append(job.id())
                elif hasattr(job, 'data') and hasattr(job.data, 'id'):
                    opencue_job_ids.append(job.data.id)
                else:
                    opencue_job_ids.append(str(job))
            except Exception:
                opencue_job_ids.append(str(job))

        # Get job_id from plan if available
        job_id = None
        plan_uri = spec["plan"].get("plan_uri", "")
        potential_id = None
        if plan_uri:
            parsed = urlparse(plan_uri)
            if parsed.scheme in ("http", "https", "file"):
                potential_id = Path(parsed.path).name
            else:
                potential_id = Path(plan_uri).name

        if potential_id:
            potential_id = potential_id.replace(".json", "")
            if len(potential_id) == 36 and "-" in potential_id:  # UUID format
                job_id = potential_id

        return SubmitResult(
            ok=True,
            job_id=job_id,
            opencue_job_ids=opencue_job_ids
        )

    except Exception as e:
        logger.exception("Failed to submit job to OpenCue")
        return SubmitResult(
            ok=False,
            error=str(e),
            hint="Check Cuebot connectivity and OpenCue configuration."
        )


def test_connection(host: str, port: int) -> SubmitResult:
    """
    Test connection to Cuebot.

    Args:
        host: Cuebot hostname
        port: Cuebot port

    Returns:
        SubmitResult indicating success/failure
    """
    hostport = f"{host}:{port}"
    os.environ["CUEBOT_HOSTS"] = hostport

    try:
        import opencue
    except ImportError as e:
        return SubmitResult(
            ok=False,
            error=f"Failed to import opencue: {e}",
            hint="Install opencue: pip install opencue"
        )

    try:
        # Try to get shows - this will fail if Cuebot is unreachable
        shows = opencue.api.getShows()
        show_names = [s.name() for s in shows]

        return SubmitResult(
            ok=True,
            job_id=None,
            opencue_job_ids=[],
            # Abuse hint field to show available shows
            hint=f"Connected. Available shows: {show_names}"
        )

    except Exception as e:
        return SubmitResult(
            ok=False,
            error=f"Failed to connect to Cuebot at {host}:{port}: {e}",
            hint="Verify Cuebot host/port and network connectivity."
        )
