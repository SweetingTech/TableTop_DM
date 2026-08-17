#!/usr/bin/env python3
"""Wait for and validate the HTTP readiness contract."""

from __future__ import annotations

import argparse
import json
import sys

from manage import wait_ready


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/readyz")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    try:
        payload = wait_ready(args.url, args.timeout)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
