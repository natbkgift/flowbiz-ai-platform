from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from platform_app.ops_auth import (
        DEFAULT_BOOTSTRAP_CLIENT_ID,
        DEFAULT_BOOTSTRAP_KEY_ID,
        DEFAULT_BOOTSTRAP_SCOPES,
        seed_or_rotate_bootstrap_admin_key,
    )

    parser = argparse.ArgumentParser(
        description="Create or rotate the platform bootstrap admin key.",
    )
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--key-id", default=DEFAULT_BOOTSTRAP_KEY_ID)
    parser.add_argument("--client-id", default=DEFAULT_BOOTSTRAP_CLIENT_ID)
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        help="Repeat to override the default scopes.",
    )
    parser.add_argument("--reason", default="vps_auth_hardening")
    args = parser.parse_args()

    result = seed_or_rotate_bootstrap_admin_key(
        db_path=args.db_path,
        output_path=args.output_path,
        key_id=args.key_id,
        client_id=args.client_id,
        scopes=tuple(args.scopes) if args.scopes else DEFAULT_BOOTSTRAP_SCOPES,
        reason=args.reason,
    )
    print(
        json.dumps(
            {
                "action": result.action,
                "key_id": result.key_id,
                "client_id": result.client_id,
                "scopes": list(result.scopes),
                "output_path": result.output_path,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
