# opencue-ue-services

Python services for OpenCue + Unreal Engine Movie Render Queue integration.

## Features

- **OpenCue Launcher** - Unified launcher for Cuebot, RQD, and Worker Pool
- **UE Worker Pool** - HTTP service managing persistent UE worker processes
- **One-shot Rendering** - Command-line mode for single render job (UE exits after completion)
- **Job Submission** - Submit render jobs to OpenCue via pycue/pyoutline

## Requirements

- Python 3.10+
- Conda (recommended)
- OpenCue (Cuebot + RQD)
- Unreal Engine 5.4+

## Setup

### 1. Create Conda Environment

```bash
conda create -n opencue_ue python=3.10
conda activate opencue_ue
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your paths and settings
```

## Run

### Worker Pool Service

Starts the HTTP service and spawns UE worker processes:

```bash
python -m src.ue_worker_service --host 127.0.0.1 --port 9100
```

### Worker Pool Service (No UE Spawn)

Starts the HTTP service only, without spawning UE workers (for debugging):

```bash
MIN_WORKERS=0 python -m src.ue_worker_service --host 127.0.0.1 --port 9100
```

## VSCode Debug

Open this folder in VSCode and use the debug configurations in `.vscode/launch.json`:

- **Worker Pool Service** - Full service with UE workers
- **Worker Pool Service (No UE Spawn)** - HTTP service only

## Related Repositories

- [OpenCueForUnreal_Plugin](https://github.com/OpenCueForUnreal/OpenCueForUnreal_Plugin) - UE5 Plugin
- [OpenCueForMRQ_Demo](https://github.com/OpenCueForUnreal/OpenCueForMRQ_Demo) - Demo Project
