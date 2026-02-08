#!/usr/bin/env python3
"""PyInstaller entrypoint for opencue-ue-agent."""

from src.ue_agent.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
