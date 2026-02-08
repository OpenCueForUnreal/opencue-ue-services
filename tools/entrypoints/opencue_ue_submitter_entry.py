#!/usr/bin/env python3
"""PyInstaller entrypoint for opencue-ue-submitter."""

from src.ue_submit.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
