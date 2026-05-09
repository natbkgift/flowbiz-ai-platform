"""Read-only preflight for platform secret and SQLite file permissions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

from platform_app.file_permissions import scan_platform_file_permissions  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report sensitive platform file permission problems without "
            "printing file contents."
        )
    )
    parser.add_argument("--root", default=".", help="Platform repo/runtime path")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    findings = scan_platform_file_permissions(Path(args.root))
    if args.json:
        print(json.dumps([item.to_dict() for item in findings], indent=2))
    else:
        for item in findings:
            mode = f" mode={item.mode}" if item.mode else ""
            print(f"{item.status.upper()} {item.kind} {item.path}{mode}: {item.message}")

    return 1 if any(item.status == "bad" for item in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
