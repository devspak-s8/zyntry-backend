"""Read-only cross-tenant isolation checks for an authorized staging deployment.

The script intentionally requires explicit staging URL, session cookies, and
resource IDs. It never creates, mutates, or deletes data. A tenant may read its
own project/runtime, while the other tenant must receive a not-found or
forbidden response for those same identifiers.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin


@dataclass(frozen=True)
class Tenant:
    name: str
    session: str
    project_id: str
    runtime_id: str


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _get(base_url: str, path: str, session: str) -> tuple[int, dict | None]:
    request = urllib.request.Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        headers={"Cookie": f"zyntra_session={session}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else None
            except json.JSONDecodeError:
                payload = None
            return response.status, payload
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _assert_status(label: str, status: int, expected: set[int]) -> None:
    if status not in expected:
        raise AssertionError(f"{label}: expected {sorted(expected)}, got {status}")
    print(f"PASS {label}: HTTP {status}")


def main() -> int:
    base_url = _required("STAGING_BASE_URL")
    if not base_url.startswith("https://") or "staging" not in base_url.lower():
        raise RuntimeError("STAGING_BASE_URL must be an HTTPS staging endpoint")

    tenants = [
        Tenant(
            "tenant-a",
            _required("STAGING_TENANT_A_SESSION"),
            _required("STAGING_TENANT_A_PROJECT_ID"),
            _required("STAGING_TENANT_A_RUNTIME_ID"),
        ),
        Tenant(
            "tenant-b",
            _required("STAGING_TENANT_B_SESSION"),
            _required("STAGING_TENANT_B_PROJECT_ID"),
            _required("STAGING_TENANT_B_RUNTIME_ID"),
        ),
    ]

    for owner in tenants:
        project_path = f"/api/v1/projects/{owner.project_id}"
        runtime_path = f"/api/v1/runtimes/{owner.runtime_id}"
        _assert_status(
            f"{owner.name} reads its project",
            _get(base_url, project_path, owner.session)[0],
            {200},
        )
        _assert_status(
            f"{owner.name} reads its runtime",
            _get(base_url, runtime_path, owner.session)[0],
            {200},
        )

        other = tenants[1] if owner is tenants[0] else tenants[0]
        _assert_status(
            f"{other.name} cannot read {owner.name} project",
            _get(base_url, project_path, other.session)[0],
            {403, 404},
        )
        _assert_status(
            f"{other.name} cannot read {owner.name} runtime",
            _get(base_url, runtime_path, other.session)[0],
            {403, 404},
        )

    print("Two-tenant staging isolation checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
