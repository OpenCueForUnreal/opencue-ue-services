# opencue-ue-submit

CLI tool to submit UE render jobs to OpenCue.

## Usage

```bash
# From opencue-ue-services directory:

# Submit a job
python -m src.ue_submit submit --spec path/to/submit_spec.json

# Test Cuebot connection
python -m src.ue_submit test --host cuebot.internal --port 8443

# Or use the batch script (exe-first wrapper):
opencue-ue-submit.bat submit --spec path/to/submit_spec.json

# Or call packaged exe directly:
dist/opencue-ue-submitter.exe submit --spec path/to/submit_spec.json
```

## Input: submit_spec.json

See `contracts/submit_spec.schema.json` for the full schema.

Example:
```json
{
  "cuebot": { "host": "cuebot.internal", "port": 8443 },
  "show": "UE_RENDER",
  "user": "alice",
  "job": {
    "name": "UE5_MainSeq_Render",
    "priority": 100
  },
  "plan": {
    "plan_uri": "\\\\fileserver\\plans\\job-id.json"
  },
  "opencue": {
    "layer_name": "render",
    "task_count": 3,
    "cmd": "opencue-ue-agent.bat run-one-shot-plan --plan-path D:\\RenderPlans\\job-id.json"
  }
}
```

## Output

Last line of stdout is always JSON:

**Success:**
```json
{"ok":true,"job_id":"2f5f3f7e-...","opencue_job_ids":["00000001-..."]}
```

**Failure:**
```json
{"ok":false,"error":"...","hint":"..."}
```

## How It Works

1. Reads `submit_spec.json`
2. Creates an OpenCue job with 1 layer
3. Layer has `task_count` tasks (frame range: `0` to `task_count-1`)
4. Each task runs `cmd` with `CUE_IFRAME` (and `CUE_FRAME`) env vars
5. RQD on worker nodes executes the command (`opencue.cmd`)

## Task Index Convention

- `CUE_IFRAME` is the integer task index (0, 1, 2, ..., N-1)
- `CUE_FRAME` may be a frame label like `0000-render`, depending on wrapper mode
- The worker entry command uses this to select the correct task from `render_plan.json`

## Worker Execution Entry

Current V1 execution entry is:

`opencue-ue-agent.bat run-one-shot-plan --plan-path <windows_plan_path>`

Notes:
- V1 intentionally does **not** implement asset sync or artifact publishing.
- `run-one-shot-plan` reads `render_plan.json` and picks the task by `CUE_IFRAME` (fallback: `CUE_FRAME`).
