# OpenCue for Unreal - UE Worker Pool System
"""
This package provides a persistent UE Worker Pool that integrates with OpenCue
for distributed rendering of Unreal Engine Movie Render Queue jobs.

Architecture:
- UE Worker Pool maintains persistent UE Editor processes
- Workers poll for tasks via HTTP lease mechanism
- RQD executes ue_render_task.py which communicates with Worker Pool
- Progress is reported back to the central MRQ server
"""

__version__ = "0.1.0"
