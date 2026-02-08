#!/usr/bin/env python3
"""
opencue-ue-submit CLI entry point.

Usage:
    python -m ue-submit submit --spec submit_spec.json
    python -m ue-submit test --host cuebot.internal --port 8443
"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
