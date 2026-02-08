# opencue-ue-services

Windows runtime and tooling for integrating OpenCue with Unreal Engine MRQ.

This repository provides two product-facing executables:
- `opencue-ue-submitter` for job submission
- `opencue-ue-agent` for task execution

It also includes convenience launch scripts for local OpenCue core services
(`cuebot`, `rqd`, `cuegui`) and developer packaging tools.

## Components and Responsibilities

| Component | Type | Responsibility | Entry |
| --- | --- | --- | --- |
| `run_cuebot.bat` | launcher script | start Cuebot (Java) with DB and port args | developer / local ops |
| `run_rqd.bat` | launcher script | activate conda env and start `rqd.exe` | developer / worker host |
| `run_cuegui.bat` | launcher script | activate conda env and start `cuegui.exe` | developer / TD |
| `opencue-ue-submit.bat` | wrapper | run `opencue-ue-submitter.exe` first, fallback to Python | UE plugin or CLI user |
| `opencue-ue-agent.bat` | wrapper | run `opencue-ue-agent.exe` first, fallback to Python | OpenCue task command |
| `src/ue_submit` | Python module | parse `submit_spec.json`, submit OpenCue job via outline/opencue | submitter executable |
| `src/ue_agent` | Python module | execute OpenCue task in one-shot mode or persistent pool mode | agent executable |
| `build_exes.ps1` / `build_exes.bat` | build tooling | package `opencue-ue-submitter.exe` and `opencue-ue-agent.exe` | developer / release |

## Local Startup

Assumptions:
- UE plugin installed
- this repository on disk
- OpenCue DB initialized (schema + seed data already applied)

### 1. Prepare Python/Conda Environment

```powershell
conda create -n opencue_ue python=3.10 -y
conda activate opencue_ue
pip install -r requirements.txt
```

### 2. Start OpenCue Core Services

Open separate terminals from `opencue-ue-services`:

```bat
run_cuebot.bat
run_rqd.bat
run_cuegui.bat
```

Notes:
- Cuebot gRPC is `8443`.
- `run_cuebot.bat` defaults HTTP to `18080`.
- `run_rqd.bat` prepends repo root to `PATH`, so RQD can resolve `opencue-ue-agent.bat`.

### 3. Verify Submitter Connectivity

```powershell
.\opencue-ue-submit.bat test --host localhost --port 8443
```

Expected output should contain `"ok": true`.

### 4. Submit from UE Plugin

In UE plugin submit settings, point submit command to:
- `opencue-ue-submitter.exe` (preferred), or
- `opencue-ue-submit.bat` (wrapper fallback path)

The plugin will generate two files under `Saved/`:
- `Saved/OpenCueSubmitSpecs/<job_id>_submit_spec.json`
- `Saved/OpenCueRenderPlans/<job_id>.json`

The submitter consumes `--spec` (submit spec), then OpenCue workers consume
the render plan referenced by `plan.plan_uri`.

## One-shot Execution Flow (Current Default)

1. UE plugin writes `submit_spec.json` and `render_plan.json`.
2. UE calls `opencue-ue-submitter` with `submit --spec ...`.
3. Submitter creates OpenCue job/layer and sets layer command.
4. RQD executes layer command:
   `opencue-ue-agent.bat run-one-shot-plan --plan-path <render_plan_path>`
5. Agent resolves task index from `CUE_IFRAME` (fallback `CUE_FRAME`).
6. Agent launches `UnrealEditor-Cmd.exe` for that task and exits with UE code.
7. OpenCue frame status updates from process exit code and task logs.

Key command used by the layer:

```bat
opencue-ue-agent.bat run-one-shot-plan --plan-path D:\path\to\render_plan.json
```

## Persistent Worker Pool Mode (TODO)

This mode keeps UE worker processes alive and dispatches tasks over HTTP.

Start service:

```powershell
python -m src.ue_agent service --host 0.0.0.0 --port 9100
```

Task bridge command (for layer command if you switch modes):

```powershell
python -m src.ue_agent run-task --job-id <job_id> --level-sequence <asset_path>
```

## CLI Reference

### Submitter

```powershell
opencue-ue-submit.bat submit --spec D:\path\to\submit_spec.json
opencue-ue-submit.bat test --host localhost --port 8443
```

### Agent

```powershell
opencue-ue-agent.bat run-one-shot-plan --plan-path D:\path\to\render_plan.json
opencue-ue-agent.bat service --host 0.0.0.0 --port 9100
opencue-ue-agent.bat run-task --job-id <job_id> --level-sequence /Game/Seqs/Seq0.Seq0
```

## Logs and Runtime Data

Default runtime roots (can be overridden by env vars):
- one-shot logs: `logs/one_shot/`
- persistent pool logs: `logs/worker_pool/`
- worker pool data: `data/worker_pool/`
- pid files from core launchers: `pids/`

Useful files:
- `logs/cuebot.log`
- `logs/rqd.log`
- `logs/rqd_console.log`
- `logs/one_shot/<job_id>/task_<index>.log`
- `logs/one_shot/<job_id>/task_<index>.ue.log`
- `logs/one_shot/<job_id>/task_<index>.runtime.json`

## Build Windows Exes

```powershell
.\build_exes.ps1 -Clean -InstallBuildDeps
```

or:

```bat
build_exes.bat -Clean -InstallBuildDeps
```

Outputs:
- `dist/opencue-ue-agent.exe`
- `dist/opencue-ue-submitter.exe`

Wrapper lookup order (`opencue-ue-agent.bat` / `opencue-ue-submit.bat`):
1. exe next to bat
2. exe in `dist/`
3. fallback to `python -m src.ue_agent` or `python -m src.ue_submit`

## Smoke Test Checklist

1. `.\opencue-ue-submit.bat --help`
2. `.\opencue-ue-agent.bat --help`
3. `.\opencue-ue-submit.bat test --host localhost --port 8443`
4. submit one job from UE
5. verify task starts in CueGUI and logs appear in `logs/one_shot/<job_id>/`

## Safe Cleanup (Regeneratable Files)

You can safely remove these local runtime/build artifacts:
- `build/`
- `logs/`
- `pids/`
- `src/**/__pycache__/`
- `.env` (if you want to recreate from `.env.example`)

Do not delete unless you intend to reconfigure:
- `Downloads/cuebot-1.13.8-all.jar`
- `Downloads/schema-1.13.8.sql`
- `Downloads/seed_data-1.13.8.sql`

## Related Repositories

- `OpenCueForUnreal_Plugin` (UE plugin)
- `OpenCueForMRQ_Demo` (demo project)
