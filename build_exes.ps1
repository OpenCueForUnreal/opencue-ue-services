param(
    [string]$PythonExe = "",
    [switch]$InstallBuildDeps,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

function Resolve-PythonExe {
    param([string]$Explicit)

    $candidates = @()
    if ($Explicit) {
        $candidates += $Explicit
    }
    if ($env:CONDA_PREFIX) {
        $candidates += (Join-Path $env:CONDA_PREFIX "python.exe")
    }
    $candidates += (Join-Path $ProjectRoot ".venv\Scripts\python.exe")
    if ($env:USERPROFILE) {
        $candidates += (Join-Path $env:USERPROFILE "miniconda3\envs\opencue_ue\python.exe")
    }
    $candidates += "python"

    foreach ($candidate in $candidates) {
        try {
            if ($candidate -eq "python" -or (Test-Path $candidate)) {
                $resolved = & $candidate -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $resolved) {
                    return $candidate
                }
            }
        } catch {
            continue
        }
    }

    throw "No usable Python executable found."
}

function Ensure-PyInstaller {
    param([string]$Py)

    $checkCmd = "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
    & $Py -c $checkCmd *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    if (-not $InstallBuildDeps) {
        throw "PyInstaller is missing. Re-run with -InstallBuildDeps or install manually: $Py -m pip install pyinstaller"
    }

    Write-Host "[build_exes] Installing PyInstaller..."
    & $Py -m pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install PyInstaller."
    }
}

function Configure-BuildPathForPython {
    param([string]$Py)

    $pyFull = (& $Py -c "import sys, pathlib; print(pathlib.Path(sys.executable).resolve())").Trim()
    if (-not $pyFull) {
        return
    }

    $pyDir = Split-Path -Parent $pyFull
    $prefix = $pyDir
    $dllDirs = @(
        $prefix,
        (Join-Path $prefix "DLLs"),
        (Join-Path $prefix "Library\bin"),
        (Join-Path $prefix "Scripts")
    ) | Where-Object { Test-Path $_ }

    if ($dllDirs.Count -gt 0) {
        $prepend = ($dllDirs -join ";")
        $env:PATH = "$prepend;$env:PATH"
        Write-Host "[build_exes] Added DLL lookup dirs:" 
        foreach ($d in $dllDirs) {
            Write-Host "  $d"
        }
    }
}

function Invoke-PyInstallerBuild {
    param(
        [string]$Py,
        [string]$ExeName,
        [string]$EntryPath,
        [string[]]$ExtraArgs
    )

    $workPath = Join-Path $BuildRoot ("work-" + $ExeName)
    $args = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", $ExeName,
        "--distpath", $DistDir,
        "--workpath", $workPath,
        "--specpath", $SpecDir,
        "--paths", $ProjectRoot
    ) + $ExtraArgs + @($EntryPath)

    Write-Host "[build_exes] Building $ExeName ..."
    & $Py @args
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed for $ExeName."
    }
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".")).Path
$DistDir = Join-Path $ProjectRoot "dist"
$BuildRoot = Join-Path $ProjectRoot "build\pyinstaller"
$SpecDir = Join-Path $BuildRoot "spec"
$AgentEntry = Join-Path $ProjectRoot "tools\entrypoints\opencue_ue_agent_entry.py"
$SubmitterEntry = Join-Path $ProjectRoot "tools\entrypoints\opencue_ue_submitter_entry.py"

if (-not (Test-Path $AgentEntry)) {
    throw "Missing entrypoint: $AgentEntry"
}
if (-not (Test-Path $SubmitterEntry)) {
    throw "Missing entrypoint: $SubmitterEntry"
}

if ($Clean) {
    Write-Host "[build_exes] Cleaning previous artifacts ..."
    if (Test-Path $BuildRoot) {
        Remove-Item -Recurse -Force $BuildRoot
    }
    if (Test-Path (Join-Path $DistDir "opencue-ue-agent.exe")) {
        Remove-Item -Force (Join-Path $DistDir "opencue-ue-agent.exe")
    }
    if (Test-Path (Join-Path $DistDir "opencue-ue-submitter.exe")) {
        Remove-Item -Force (Join-Path $DistDir "opencue-ue-submitter.exe")
    }
}

New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
New-Item -ItemType Directory -Force -Path $SpecDir | Out-Null

$Py = Resolve-PythonExe -Explicit $PythonExe
Write-Host "[build_exes] Using Python: $Py"
& $Py -V

Ensure-PyInstaller -Py $Py
Configure-BuildPathForPython -Py $Py

Invoke-PyInstallerBuild -Py $Py -ExeName "opencue-ue-agent" -EntryPath $AgentEntry -ExtraArgs @(
    "--hidden-import", "src.ue_agent.cli",
    "--hidden-import", "src.ue_agent.service",
    "--hidden-import", "src.ue_agent.run_task",
    "--hidden-import", "src.ue_agent.run_one_shot_plan",
    "--collect-data", "opencue"
)

Invoke-PyInstallerBuild -Py $Py -ExeName "opencue-ue-submitter" -EntryPath $SubmitterEntry -ExtraArgs @(
    "--hidden-import", "src.ue_submit.cli",
    "--hidden-import", "src.ue_submit.submitter",
    "--collect-data", "opencue",
    "--collect-data", "outline",
    "--collect-submodules", "outline",
    "--collect-submodules", "opencue",
    "--collect-submodules", "opencue_proto",
    "--collect-submodules", "grpc"
)

$AgentExe = Join-Path $DistDir "opencue-ue-agent.exe"
$SubmitterExe = Join-Path $DistDir "opencue-ue-submitter.exe"

if (-not (Test-Path $AgentExe)) {
    throw "Missing output: $AgentExe"
}
if (-not (Test-Path $SubmitterExe)) {
    throw "Missing output: $SubmitterExe"
}

Write-Host ""
Write-Host "[build_exes] Done."
Write-Host "  $AgentExe"
Write-Host "  $SubmitterExe"
