from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Invoke a Zyntry runtime and optionally execute a connected OAuth action."
    )
    parser.add_argument("--base-url", default="https://api.zyntry.space")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--runtime-id")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--provider", help="Connected action provider, for example notion or slack")
    parser.add_argument("--action", help="Provider action name supported by the backend action registry")
    parser.add_argument(
        "--arguments",
        default="{}",
        help='JSON object for the provider action, for example {"channel":"...","text":"..."}',
    )
    parser.add_argument("--confirm", action="store_true", help="Confirm an impactful action")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.getenv("ZYNTRY_API_KEY")
    if not api_key:
        print("Set ZYNTRY_API_KEY in the current shell; the script never prints it.", file=sys.stderr)
        return 2
    try:
        action_arguments = json.loads(args.arguments)
    except json.JSONDecodeError as exc:
        print(f"Invalid --arguments JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(action_arguments, dict):
        print("--arguments must be a JSON object", file=sys.stderr)
        return 2
    if bool(args.provider) != bool(args.action):
        print("Use --provider and --action together", file=sys.stderr)
        return 2

    payload: dict[str, Any] = {
        "project": args.project_id,
        "runtime_id": args.runtime_id,
        "input": args.prompt,
        "goal": "balanced",
    }
    if args.provider and args.action:
        payload["actions"] = [
            {
                "project_id": args.project_id,
                "provider": args.provider,
                "action": args.action,
                "arguments": action_arguments,
                "confirm": args.confirm,
            }
        ]

    request = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/api/v1/invoke/invoke",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print(f"Invocation failed ({exc.code}): {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Invocation failed: {exc.reason}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    pending = [
        item for item in result.get("action_results", []) if item.get("requires_confirmation")
    ]
    if pending:
        print("\nAn action requires confirmation. Review it, then rerun with --confirm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
