#!/usr/bin/env python3
"""
CLI interface for opencue-ue-submit.

Commands:
    submit  - Submit a job to OpenCue using submit_spec.json
    test    - Test connection to Cuebot
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .submitter import submit_job, test_connection, SubmitResult


def cmd_submit(args) -> int:
    """Handle 'submit' command."""
    spec_path = Path(args.spec)

    if not spec_path.exists():
        result = SubmitResult(
            ok=False,
            error=f"Spec file not found: {spec_path}",
            hint="Ensure the submit_spec.json file exists at the specified path."
        )
        print(json.dumps(result.to_dict()))
        return 1

    try:
        with open(spec_path, "r", encoding="utf-8") as f:
            spec = json.load(f)
    except json.JSONDecodeError as e:
        result = SubmitResult(
            ok=False,
            error=f"Invalid JSON in spec file: {e}",
            hint="Check the submit_spec.json for syntax errors."
        )
        print(json.dumps(result.to_dict()))
        return 1

    result = submit_job(spec)

    # Always output JSON as the last line (contract requirement)
    print(json.dumps(result.to_dict()))

    return 0 if result.ok else 1


def cmd_test(args) -> int:
    """Handle 'test' command."""
    result = test_connection(args.host, args.port)

    print(json.dumps(result.to_dict()))

    return 0 if result.ok else 1


def main(argv: Optional[list] = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="opencue-ue-submit",
        description="Submit UE render jobs to OpenCue"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # submit command
    submit_parser = subparsers.add_parser(
        "submit",
        help="Submit a job using submit_spec.json"
    )
    submit_parser.add_argument(
        "--spec",
        type=str,
        required=True,
        help="Path to submit_spec.json"
    )
    submit_parser.set_defaults(func=cmd_submit)

    # test command
    test_parser = subparsers.add_parser(
        "test",
        help="Test connection to Cuebot"
    )
    test_parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Cuebot host (default: localhost)"
    )
    test_parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help="Cuebot port (default: 8443)"
    )
    test_parser.set_defaults(func=cmd_test)

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
