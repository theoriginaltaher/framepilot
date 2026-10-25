from __future__ import annotations

import argparse
from pathlib import Path
import sys

from framepilot.xmp import parse_sidecar, validate_sidecar


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a FramePilot/Adobe Camera Raw XMP sidecar")
    parser.add_argument("xmp", type=Path)
    args = parser.parse_args()
    result = validate_sidecar(args.xmp)
    if not result.valid:
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Valid Camera Raw XMP")
    print(parse_sidecar(args.xmp).to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

