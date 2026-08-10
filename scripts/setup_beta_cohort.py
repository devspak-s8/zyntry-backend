from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.admin.feature_registry import BETA_FEATURE_KEYS  # noqa: E402
from app.admin.models import FeatureFlag  # noqa: E402
from app.core.database import async_session_factory  # noqa: E402
from app.core.redis import redis_client  # noqa: E402
from app.emails import send_email  # noqa: E402
from app.models.billing import WalletTransaction  # noqa: E402
from app.models.notifications import Notification  # noqa: E402
from app.models.users import User  # noqa: E402
from app.services.billing import BillingService  # noqa: E402

COHORT_KEY = "founding_beta_2026_08"
INVITATION_MARKER = f"{COHORT_KEY}_invitation_sent"
DEFAULT_CREDIT = Decimal("5.0000")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Allowlist a beta cohort, grant testing credit, and send one invitation"
    )
    parser.add_argument("emails", nargs="+", help="Registered beta tester email addresses")
    parser.add_argument("--credit", type=Decimal, default=DEFAULT_CREDIT)
    parser.add_argument("--access-date", default="today")
    parser.add_argument("--app-url", default="https://zyntry.space")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Required to modify flags, grant credit, and send email",
    )
    return parser.parse_args()


def normalize_emails(emails: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(email.strip().lower() for email in emails))
    invalid = [email for email in normalized if "@" not in email]
    if invalid:
        raise ValueError(f"Invalid email addresses: {', '.join(invalid)}")
    return normalized


async def main() -> int:
    args = parse_args()
    emails = normalize_emails(args.emails)
    if args.credit <= 0:
        print("ERROR: credit must be greater than zero")
        return 2

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(func.lower(User.email).in_(emails)))
        users = list(result.scalars().all())
        users_by_email = {user.email.lower(): user for user in users}
        missing = [email for email in emails if email not in users_by_email]

        print(f"Registered testers: {len(users)}/{len(emails)}")
        for email in emails:
            status = "FOUND" if email in users_by_email else "MISSING"
            print(f"{status}: {email}")

        if missing:
            print("ABORTED: every tester must register before access, credit, or email is applied")
            return 2

        flag_result = await db.execute(
            select(FeatureFlag).where(FeatureFlag.key.in_(BETA_FEATURE_KEYS))
        )
        flags = list(flag_result.scalars().all())
        found_keys = {flag.key for flag in flags}
        missing_flags = sorted(BETA_FEATURE_KEYS - found_keys)
        if missing_flags:
            print(f"ABORTED: missing beta flags: {', '.join(missing_flags)}")
            return 2

        if not args.apply:
            print("DRY RUN: no database changes, wallet credits, or emails were sent")
            print(f"Would allowlist users on {len(flags)} beta flags")
            print(f"Would grant ${args.credit:.2f} once to each registered tester")
            return 0

        targets = {f"email:{email}" for email in emails}
        for flag in flags:
            flag.allowlist = sorted(set(flag.allowlist or []) | targets)
        await db.commit()
        for key in BETA_FEATURE_KEYS:
            await redis_client.delete(f"feature-flag:{key}")
        print(f"ALLOWLISTED: {len(emails)} testers on {len(flags)} beta flags")

        failures = 0
        for email in emails:
            user = users_by_email[email]
            reference_id = f"{COHORT_KEY}_credit_{user.id}"
            transaction_result = await db.execute(
                select(WalletTransaction).where(WalletTransaction.reference_id == reference_id)
            )
            transaction = transaction_result.scalar_one_or_none()
            if transaction is None:
                transaction = await BillingService(db).add_credit(
                    user_id=user.id,
                    amount=args.credit,
                    reason="Zyntry beta testing credit",
                    reference_id=reference_id,
                    metadata={"cohort": COHORT_KEY, "purpose": "beta_testing"},
                )
                print(f"CREDITED: {email}: ${args.credit:.2f}")
            else:
                print(f"CREDIT SKIPPED: {email}: already granted")

            marker_result = await db.execute(
                select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.type == INVITATION_MARKER,
                )
            )
            marker = marker_result.scalar_one_or_none()
            if marker is not None:
                print(f"EMAIL SKIPPED: {email}: already sent")
                continue

            delivery = await send_email(
                "zyntry_beta_invitation",
                email,
                from_name="Zyntry",
                category="beta",
                access_date=args.access_date,
                app_url=args.app_url,
                credit_amount=f"${args.credit:.2f}",
                recipient_name=user.name,
            )
            if not delivery.get("success"):
                failures += 1
                print(f"EMAIL FAILED: {email}: {delivery.get('error', 'unknown error')}")
                continue

            db.add(
                Notification(
                    user_id=user.id,
                    type=INVITATION_MARKER,
                    title="Zyntry beta access",
                    message=f"Beta access enabled with ${args.credit:.2f} testing credit.",
                    data={"cohort": COHORT_KEY, "credit_transaction_id": str(transaction.id)},
                    read=False,
                )
            )
            await db.commit()
            print(f"EMAIL SENT: {email}")

        return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
