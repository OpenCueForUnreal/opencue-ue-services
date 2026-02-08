"""
OpenCue UE Agent

This package contains the "execution side" components that typically run on
render farm worker machines:

- A persistent UE Worker Pool HTTP service (optional, for persistent mode)
- Per-task entrypoints executed by OpenCue RQD (bridge/runner)

Submitter tooling lives in `src.ue_submit`.
"""

__all__ = [
    "__version__",
]

__version__ = "0.1.0"
