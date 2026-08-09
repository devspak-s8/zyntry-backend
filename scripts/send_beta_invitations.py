from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.emails import send_email  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send the Zyntry founding-beta announcement")
    parser.add_argument("emails", nargs="+", help="Recipients; each receives a separate email")
    parser.add_argument("--access-date", required=True, help="Human-readable follow-up date")
    parser.add_argument("--app-url", default="https://zyntry.space", help="CTA destination")
    parser.add_argument("--send", action="store_true", help="Required to perform external delivery")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    recipients = list(dict.fromkeys(email.strip().lower() for email in args.emails))
    if not args.send:
        print("DRY RUN: no emails sent. Add --send to deliver.")
        for email in recipients:
            print(f"WOULD SEND: {email}")
        return 0

    failures = 0
    for email in recipients:
        result = await send_email(
            "zyntry_beta_invitation",
            email,
            from_name="Zyntry",
            category="beta",
            access_date=args.access_date,
            app_url=args.app_url,
        )
        if result.get("success"):
            print(f"SENT: {email}")
        else:
            failures += 1
            print(f"FAILED: {email}: {result.get('error', 'unknown error')}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
