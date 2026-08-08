#!/usr/bin/env python3
"""
Zyntry FastAPI Backend Load-Testing Script
==========================================
Simulates 10,000 concurrent/staggered virtual users exercising the full
auth + CRUD flow across org-scoped endpoints.

Why httpx.AsyncClient instead of Locust
---------------------------------------
Locust excels at distributed, UI-driven load tests with headless browsers,
but this workload needs:
  - precise per-user lifecycle control (register -> login -> CRUD -> logout),
  - deterministic org-assignment across many tenants,
  - mixed regular + superadmin traffic in the single run,
  - fine-grained ramp-up scheduling, and
  - in-process metric aggregation without a master/worker architecture.

httpx + asyncio gives us all of that in a single script with no external
dependencies beyond the project's existing requirements.txt.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

print("[DEBUG] load_test.py module loaded from:", __file__, flush=True)

# ---------------------------------------------------------------------------
# Configuration (env vars with safe staging defaults)
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = os.getenv("ZYTRY_BASE_URL", "api.zyntry.space")
DEFAULT_BATCH_SIZE = int(os.getenv("ZYTRY_LOAD_BATCH_SIZE", "50"))
DEFAULT_RAMP_INTERVAL = float(os.getenv("ZYTRY_LOAD_RAMP_INTERVAL", "2"))
DEFAULT_TOTAL_USERS = int(os.getenv("ZYTRY_LOAD_TOTAL_USERS", "10000"))
DEFAULT_NUM_ORGS = int(os.getenv("ZYTRY_LOAD_NUM_ORGS", "200"))
DEFAULT_MAX_CONCURRENT = int(os.getenv("ZYTRY_LOAD_MAX_CONCURRENT", "10"))
DEFAULT_SUPERADMIN_EMAIL = os.getenv(
    "ZYTRY_LOAD_SUPERADMIN_EMAIL", os.getenv("SUPERADMIN_EMAIL", "")
)
DEFAULT_SUPERADMIN_PASSWORD = os.getenv(
    "ZYTRY_LOAD_SUPERADMIN_PASSWORD", os.getenv("SUPERADMIN_PASSWORD", "")
)


def _normalize_base_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
@dataclass
class RequestRecord:
    endpoint: str
    method: str
    status: int
    latency_ms: float
    ts: float = field(default_factory=time.time)
    error: str | None = None
    response_body: str | None = None
    expected: bool = True


class MetricsCollector:
    def __init__(self) -> None:
        self._records: list[RequestRecord] = []
        self._lock = asyncio.Lock()

    async def add(self, record: RequestRecord) -> None:
        async with self._lock:
            self._records.append(record)

    async def add_error(self, endpoint: str, method: str, error: str) -> None:
        await self.add(
            RequestRecord(
                endpoint=endpoint,
                method=method,
                status=0,
                latency_ms=0.0,
                error=error,
                expected=False,
            )
        )

    def summarize(
        self,
    ) -> tuple[dict[str, dict[str, Any]], list[RequestRecord]]:
        buckets: dict[str, list[float]] = defaultdict(list)
        errors: dict[str, int] = defaultdict(int)
        five_xx: list[RequestRecord] = []

        for r in self._records:
            key = f"{r.method.upper()} {r.endpoint}"
            buckets[key].append(r.latency_ms)
            if not r.expected:
                errors[key] += 1
            if 500 <= r.status < 600:
                five_xx.append(r)

        stats: dict[str, dict[str, Any]] = {}
        for key, latencies in buckets.items():
            s = sorted(latencies)
            n = len(s)
            stats[key] = {
                "count": n,
                "p50_ms": s[int(n * 0.50)] if n else 0.0,
                "p95_ms": s[int(n * 0.95)] if n else 0.0,
                "p99_ms": s[int(n * 0.99)] if n else 0.0,
                "error_count": errors.get(key, 0),
                "error_rate": errors.get(key, 0) / n if n else 0.0,
            }
        return stats, five_xx


metrics = MetricsCollector()

UUID_IN_PATH = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)"
)


def _metric_endpoint(url: str) -> str:
    return UUID_IN_PATH.sub("/{id}", url)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
async def timed_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    label: str = "",
    verbose: bool = False,
    retries: int = 2,
    expected_statuses: set[int] | None = None,
    **kwargs: Any,
) -> httpx.Response | None:
    start = time.perf_counter()
    for attempt in range(retries):
        try:
            resp = await client.request(method, url, **kwargs)
            latency = (time.perf_counter() - start) * 1000.0
            expected = (
                resp.status_code in expected_statuses
                if expected_statuses is not None
                else 200 <= resp.status_code < 400
            )
            body_text: str | None = None
            if 500 <= resp.status_code < 600:
                try:
                    body_text = resp.text[:2000]
                except Exception:
                    body_text = "<unreadable>"
                print(
                    f"    [ERR] {label or method.upper()} {url} -> {resp.status_code} "
                    f"({latency:.1f}ms) body={body_text!r}"
                )
            elif resp.status_code == 429:
                wait = (2**attempt) + 0.1
                print(f"    [RATE] {label or method.upper()} {url} -> 429, backing off {wait:.1f}s")
                await asyncio.sleep(wait)
                continue
            elif not expected:
                try:
                    err_body = resp.text[:500]
                except Exception:
                    err_body = "<unreadable>"
                print(
                    f"    [WARN] {label or method.upper()} {url} -> {resp.status_code} "
                    f"({latency:.1f}ms) body={err_body!r}"
                )
            await metrics.add(
                RequestRecord(
                    endpoint=_metric_endpoint(url),
                    method=method.upper(),
                    status=resp.status_code,
                    latency_ms=latency,
                    response_body=body_text,
                    expected=expected,
                )
            )
            return resp
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000.0
            if attempt < retries - 1:
                wait = (2**attempt) + 0.1
                print(
                    f"    [ERR] {label or method.upper()} {url} -> EXCEPTION "
                    f"({latency:.1f}ms) {exc}, retry {attempt + 1}/{retries}"
                )
                await asyncio.sleep(wait)
                continue
            print(f"    [ERR] {label or method.upper()} {url} -> EXCEPTION ({latency:.1f}ms) {exc}")
            await metrics.add(
                RequestRecord(
                    endpoint=_metric_endpoint(url),
                    method=method.upper(),
                    status=0,
                    latency_ms=latency,
                    error=str(exc),
                    expected=False,
                )
            )
            return None
    return None


# ---------------------------------------------------------------------------
# Virtual User
# ---------------------------------------------------------------------------
class VirtualUser:
    def __init__(
        self,
        uid: int,
        org_id: str,
        email: str,
        password: str,
        base_url: str,
        is_superadmin: bool = False,
        verbose: bool = False,
        verify_ssl: bool = True,
        idempotency_replays: int = 3,
    ) -> None:
        self.uid = uid
        self.org_id = org_id
        self.email = email
        self.password = password
        self._base_url = base_url
        self.is_superadmin = is_superadmin
        self.project_id: str | None = None
        self._verbose = verbose
        self._verify_ssl = verify_ssl
        self._idempotency_replays = idempotency_replays
        self._project_payload: dict[str, Any] | None = None
        self._idempotency_key: str | None = None

    async def run(self) -> None:
        self.project_id = None
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        timeout = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
        async with httpx.AsyncClient(
            base_url=self._base_url,
            limits=limits,
            timeout=timeout,
            follow_redirects=True,
            verify=self._verify_ssl,
        ) as client:
            if self._verbose:
                print(f"    [VERB] u{self.uid} starting flow, email={self.email}", flush=True)
            try:
                await self.register(client)
                await self.login(client)
                await self.get_me(client)
                await self.list_projects(client)
                await self.test_tenant_isolation(client)
                await self.create_project(client)
                await self.replay_idempotent_create(client)
                await self.test_idempotency_payload_mismatch(client)
                await self.test_duplicate_prevention(client)
                await self.get_project(client)
                await self.update_project(client)
                await self.get_user_settings(client)
                await self.update_user_settings(client)
                await self.superadmin_users_check(client)
                await self.delete_project(client)
                await self.verify_project_deleted(client)
                await self.logout(client)
            except Exception as exc:
                print(f"    [FLOW-ERR] User {self.uid} ({self.email}): {type(exc).__name__}: {exc}")
                await metrics.add_error(
                    endpoint="user.flow",
                    method="FLOW",
                    error=f"User {self.uid} flow exception: {exc}",
                )

    async def register(self, client: httpx.AsyncClient) -> None:
        resp = await timed_request(
            client,
            "POST",
            "/api/v1/auth/register",
            label=f"u{self.uid} register",
            verbose=self._verbose,
            json={
                "email": self.email,
                "password": self.password,
                "name": f"LoadTest User {self.uid}",
            },
            expected_statuses={201, 409},
        )
        if resp is None:
            return
        if resp.status_code == 409:
            return

    async def login(self, client: httpx.AsyncClient) -> None:
        resp = await timed_request(
            client,
            "POST",
            "/api/v1/auth/login",
            label=f"u{self.uid} login",
            verbose=self._verbose,
            json={"email": self.email, "password": self.password},
        )
        if resp is None:
            return
        if resp.status_code == 200:
            self.project_id = None

    async def get_me(self, client: httpx.AsyncClient) -> None:
        await timed_request(
            client, "GET", "/api/v1/auth/me", label=f"u{self.uid} me", verbose=self._verbose
        )

    async def list_projects(self, client: httpx.AsyncClient) -> None:
        await timed_request(
            client,
            "GET",
            "/api/v1/projects",
            label=f"u{self.uid} list_projects",
            verbose=self._verbose,
        )

    async def test_tenant_isolation(self, client: httpx.AsyncClient) -> None:
        unique = uuid.uuid4().hex
        await timed_request(
            client,
            "POST",
            "/api/v1/projects",
            label=f"u{self.uid} cross_org_create",
            json={
                "name": f"Forbidden Project {unique}",
                "slug": f"forbidden-{unique}",
                "organization_id": self.org_id,
                "settings": {},
            },
            expected_statuses={403},
        )
        await timed_request(
            client,
            "GET",
            f"/api/v1/projects/{uuid.uuid4()}",
            label=f"u{self.uid} inaccessible_project",
            expected_statuses={404},
        )

    async def create_project(self, client: httpx.AsyncClient) -> None:
        unique = uuid.uuid4().hex
        slug = f"loadtest-{self.uid}-{unique}"
        name = f"LoadTest Project {self.uid} {unique}"
        self._project_payload = {
            "name": name,
            "slug": slug,
            "description": f"Load test project for user {self.uid}",
            "organization_id": None,
            "settings": {},
        }
        self._idempotency_key = f"loadtest-project-{self.uid}-{unique}"
        resp = await timed_request(
            client,
            "POST",
            "/api/v1/projects",
            label=f"u{self.uid} create_project",
            verbose=self._verbose,
            json=self._project_payload,
            headers={"Idempotency-Key": self._idempotency_key},
        )
        if resp and resp.status_code in (200, 201):
            try:
                data = resp.json()
                self.project_id = data.get("id")
                if self._verbose:
                    print(f"    [VERB] u{self.uid} create_project -> project_id={self.project_id}")
            except Exception as exc:
                if self._verbose:
                    print(f"    [VERB] u{self.uid} create_project -> json parse error: {exc}")
        elif resp and resp.status_code == 409:
            resp2 = await timed_request(
                client,
                "GET",
                "/api/v1/projects",
                label=f"u{self.uid} list_projects_fallback",
                verbose=self._verbose,
            )
            if resp2 and resp2.status_code == 200:
                try:
                    data = resp2.json()
                    if isinstance(data, list) and data:
                        self.project_id = data[0].get("id")
                        if self._verbose:
                            print(
                                f"    [VERB] u{self.uid} create_project 409 -> "
                                f"fallback project_id={self.project_id}"
                            )
                except Exception:
                    pass

    async def replay_idempotent_create(self, client: httpx.AsyncClient) -> None:
        if not self.project_id or not self._project_payload or not self._idempotency_key:
            return

        async def replay(index: int) -> httpx.Response | None:
            return await timed_request(
                client,
                "POST",
                "/api/v1/projects",
                label=f"u{self.uid} idempotency_replay_{index}",
                json=self._project_payload,
                headers={"Idempotency-Key": self._idempotency_key},
                expected_statuses={201},
            )

        responses = await asyncio.gather(*(replay(i) for i in range(self._idempotency_replays)))
        for response in responses:
            if response is not None and response.status_code == 201:
                replay_id = response.json().get("id")
                if replay_id != self.project_id:
                    await metrics.add_error(
                        "idempotency.project_id_mismatch",
                        "ASSERT",
                        f"expected {self.project_id}, got {replay_id}",
                    )

    async def test_idempotency_payload_mismatch(self, client: httpx.AsyncClient) -> None:
        if not self._project_payload or not self._idempotency_key:
            return
        changed = dict(self._project_payload)
        changed["description"] = "different payload using the same idempotency key"
        await timed_request(
            client,
            "POST",
            "/api/v1/projects",
            label=f"u{self.uid} idempotency_mismatch",
            json=changed,
            headers={"Idempotency-Key": self._idempotency_key},
            expected_statuses={409},
        )

    async def test_duplicate_prevention(self, client: httpx.AsyncClient) -> None:
        if not self._project_payload:
            return
        await timed_request(
            client,
            "POST",
            "/api/v1/projects",
            label=f"u{self.uid} duplicate_project",
            json=self._project_payload,
            expected_statuses={409},
        )

    async def get_project(self, client: httpx.AsyncClient) -> None:
        if not self.project_id:
            return
        await timed_request(
            client,
            "GET",
            f"/api/v1/projects/{self.project_id}",
            label=f"u{self.uid} get_project",
            verbose=self._verbose,
        )

    async def update_project(self, client: httpx.AsyncClient) -> None:
        if not self.project_id:
            return
        await timed_request(
            client,
            "PATCH",
            f"/api/v1/projects/{self.project_id}",
            label=f"u{self.uid} update_project",
            verbose=self._verbose,
            json={
                "name": f"Updated LoadTest Project {self.uid}",
                "slug": f"updated-loadtest-{self.uid}-{int(time.time())}",
                "description": f"Updated load test project for user {self.uid}",
                "settings": {},
            },
        )

    async def get_user_settings(self, client: httpx.AsyncClient) -> None:
        await timed_request(
            client,
            "GET",
            "/api/v1/users/me/settings",
            label=f"u{self.uid} settings",
            verbose=self._verbose,
        )

    async def update_user_settings(self, client: httpx.AsyncClient) -> None:
        await timed_request(
            client,
            "PATCH",
            "/api/v1/users/me/settings",
            label=f"u{self.uid} update_settings",
            verbose=self._verbose,
            json={"load_test_user_id": self.uid, "updated_at": time.time()},
        )

    async def superadmin_users_check(self, client: httpx.AsyncClient) -> None:
        expected_statuses = {200} if self.is_superadmin else {403}
        resp = await timed_request(
            client,
            "GET",
            "/api/v1/users",
            label=f"u{self.uid} superadmin_check",
            verbose=self._verbose,
            expected_statuses=expected_statuses,
        )
        if resp is None:
            return
        if self.is_superadmin:
            if resp.status_code != 200:
                await metrics.add(
                    RequestRecord(
                        endpoint="/api/v1/users (superadmin check)",
                        method="GET",
                        status=resp.status_code,
                        latency_ms=0.0,
                        expected=False,
                        error=(
                            f"Superadmin account expected 200 on GET /users, got {resp.status_code}"
                        ),
                    )
                )
        else:
            if resp.status_code != 403:
                await metrics.add(
                    RequestRecord(
                        endpoint="/api/v1/users (superadmin check)",
                        method="GET",
                        status=resp.status_code,
                        latency_ms=0.0,
                        expected=False,
                        error=(
                            f"Non-superadmin account expected 403 on GET /users, "
                            f"got {resp.status_code} — possible org-isolation / "
                            f"permission leak under concurrency"
                        ),
                    )
                )

    async def delete_project(self, client: httpx.AsyncClient) -> None:
        if not self.project_id:
            return
        await timed_request(
            client,
            "DELETE",
            f"/api/v1/projects/{self.project_id}",
            label=f"u{self.uid} delete_project",
            expected_statuses={204},
        )

    async def verify_project_deleted(self, client: httpx.AsyncClient) -> None:
        if not self.project_id:
            return
        await timed_request(
            client,
            "GET",
            f"/api/v1/projects/{self.project_id}",
            label=f"u{self.uid} verify_project_deleted",
            expected_statuses={404},
        )

    async def logout(self, client: httpx.AsyncClient) -> None:
        await timed_request(
            client,
            "POST",
            "/api/v1/auth/logout",
            label=f"u{self.uid} logout",
            verbose=self._verbose,
        )


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------
async def run_batch(
    users: list[VirtualUser],
    base_url: str,
    max_concurrent: int,
    batch_idx: int = 0,
    total_batches: int = 0,
) -> None:
    semaphore = asyncio.Semaphore(max_concurrent)
    completed = 0
    total = len(users)
    last_print = time.perf_counter()
    batch_start = last_print
    batch_started_at = time.time()

    async def run_one(user: VirtualUser) -> None:
        nonlocal completed, last_print
        async with semaphore:
            try:
                await user.run()
            except Exception as exc:
                print(f"    [RUN-ERR] User {user.uid}: {type(exc).__name__}: {exc}", flush=True)
                await metrics.add_error(
                    endpoint="user.flow",
                    method="FLOW",
                    error=f"User {user.uid} flow exception: {exc}",
                )
        completed += 1
        now = time.perf_counter()
        if completed == 1 or completed == total or now - last_print >= 2.0:
            elapsed = now - batch_start
            rate = completed / elapsed if elapsed > 0 else 0.0
            print(
                f"  [{time.strftime('%H:%M:%S')}] "
                f"Batch {batch_idx}/{total_batches} progress: "
                f"{completed}/{total} users ({rate:.1f} users/s)",
                flush=True,
            )
            last_print = now

    tasks = [run_one(u) for u in users]
    await asyncio.gather(*tasks, return_exceptions=True)

    batch_elapsed = time.perf_counter() - batch_start
    _, batch_five_xx = metrics.summarize()
    batch_five_xx = [r for r in batch_five_xx if r.ts >= batch_started_at]
    print(
        f"  [{time.strftime('%H:%M:%S')}] Batch {batch_idx}/{total_batches} done "
        f"in {batch_elapsed:.1f}s — {completed} users"
    )
    if batch_five_xx:
        print(f"    WARN: {len(batch_five_xx)} 5xx responses in this batch")
        for r in batch_five_xx[:5]:
            body = (r.response_body or "").replace("\n", " ")[:200]
            print(f"      {r.method} {r.endpoint} -> {r.status} body={body!r}")


# ---------------------------------------------------------------------------
# Stats printer
# ---------------------------------------------------------------------------
def print_summary(
    stats: dict[str, dict[str, Any]],
    five_xx: list[RequestRecord],
    total_duration: float,
) -> None:
    total_requests = sum(s["count"] for s in stats.values())
    total_errors = sum(s["error_count"] for s in stats.values())

    print("\n" + "=" * 90)
    print(
        f"LOAD TEST COMPLETE  |  Duration: {total_duration:.1f}s  |  "
        f"Total requests: {total_requests}  |  Errors: {total_errors}"
    )
    print("=" * 90)

    print("\nREQUEST LATENCY PERCENTILES & ERROR RATES")
    print("-" * 90)
    for endpoint, s in sorted(stats.items()):
        print(
            f"  {endpoint:62s}  "
            f"n={s['count']:6d}  "
            f"p50={s['p50_ms']:8.1f}ms  "
            f"p95={s['p95_ms']:8.1f}ms  "
            f"p99={s['p99_ms']:8.1f}ms  "
            f"err={s['error_rate']:5.1%}"
        )

    if five_xx:
        print("\n" + "=" * 90)
        print(f"5XX RESPONSES ({len(five_xx)} total) — response bodies below")
        print("=" * 90)
        for r in five_xx[:50]:
            body_preview = (r.response_body or "").replace("\n", " ")[:400]
            print(f"  {r.method} {r.endpoint}  -> {r.status}  body={body_preview!r}")
        if len(five_xx) > 50:
            print(f"  ... and {len(five_xx) - 50} more")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Zyntry FastAPI backend load test (10k users, org-scoped)"
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Backend base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Users per ramp batch (default: %(default)s)",
    )
    parser.add_argument(
        "--ramp-interval",
        type=float,
        default=DEFAULT_RAMP_INTERVAL,
        help="Seconds to wait between batches (default: %(default)s)",
    )
    parser.add_argument(
        "--total-users",
        type=int,
        default=DEFAULT_TOTAL_USERS,
        help="Total virtual users to simulate (default: %(default)s)",
    )
    parser.add_argument(
        "--num-orgs",
        type=int,
        default=DEFAULT_NUM_ORGS,
        help="Approximate number of orgs to distribute users across (default: %(default)s). "
        "Note: the public register endpoint creates one org per user, so actual "
        "org count will equal total-users unless an org-assignment API exists.",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=DEFAULT_MAX_CONCURRENT,
        help="Max concurrent HTTP connections (default: %(default)s)",
    )
    parser.add_argument(
        "--superadmin-email",
        default=DEFAULT_SUPERADMIN_EMAIL,
        help="Pre-existing superadmin account email (optional)",
    )
    parser.add_argument(
        "--superadmin-password",
        default=DEFAULT_SUPERADMIN_PASSWORD,
        help="Pre-existing superadmin account password (optional)",
    )
    parser.add_argument(
        "--verbose-first",
        type=int,
        default=5,
        help="Log full request/response details for the first N users (default: 5)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Disable SSL verification (use only for local/staging with self-signed certs)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a single-user smoke test with verbose logging and exit",
    )
    parser.add_argument(
        "--stress",
        action="store_true",
        help="Stress profile: 5,000 users, batches of 500, concurrency 250",
    )
    parser.add_argument(
        "--spike",
        action="store_true",
        help="Spike profile: 2,000 users launched in one batch at concurrency 500",
    )
    parser.add_argument(
        "--idempotency-replays",
        type=int,
        default=3,
        help="Concurrent retries per project using the same Idempotency-Key (default: 3)",
    )
    args = parser.parse_args()

    base_url = _normalize_base_url(args.base_url.rstrip("/"))
    total_users = max(1, args.total_users)
    batch_size = min(args.batch_size, total_users)
    ramp_interval = max(0.0, args.ramp_interval)
    num_orgs = min(args.num_orgs, total_users)
    max_concurrent = max(1, args.max_concurrent)
    superadmin_email = args.superadmin_email.strip()
    superadmin_password = args.superadmin_password
    verbose_first = max(0, args.verbose_first)
    verify_ssl = not args.no_verify
    idempotency_replays = max(1, args.idempotency_replays)

    if sum((args.smoke, args.stress, args.spike)) > 1:
        parser.error("Choose only one of --smoke, --stress, or --spike")
    if args.smoke:
        total_users = 1
        batch_size = 1
        max_concurrent = 1
        verbose_first = 1
        print("[*] Smoke test mode: 1 user, verbose, max_concurrent=1")
    elif args.stress:
        total_users = 5000
        batch_size = 500
        max_concurrent = 250
        ramp_interval = 1.0
        print("[*] Stress mode: 5,000 users, batches=500, max_concurrent=250")
    elif args.spike:
        total_users = 2000
        batch_size = 2000
        max_concurrent = 500
        ramp_interval = 0.0
        print("[*] Spike mode: 2,000 users, one batch, max_concurrent=500")

    health_url = base_url + "/health"
    print(f"[*] Pre-flight health check: {health_url}")
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=verify_ssl) as hc:
            health_resp = await hc.get(health_url)
            print(f"    -> {health_resp.status_code} {health_resp.text[:200]}")
    except Exception as exc:
        print(f"    -> HEALTH CHECK FAILED: {exc}")
        print(
            "    If this is a staging server with a self-signed certificate, "
            "re-run with --no-verify"
        )
        return

    # Generate org pool
    org_ids = [str(uuid.uuid4()) for _ in range(num_orgs)]

    # Build user list
    users: list[VirtualUser] = []
    superadmin_count = 0

    for i in range(total_users):
        org_id = org_ids[i % num_orgs]
        is_superadmin = False

        if superadmin_email and superadmin_count < 5:
            email = superadmin_email
            password = superadmin_password
            is_superadmin = True
            superadmin_count += 1
        else:
            email = f"loadtest-user-{i}-{uuid.uuid4().hex[:8]}@example.com"
            password = "LoadTestPass123!"

        users.append(
            VirtualUser(
                uid=i,
                org_id=org_id,
                email=email,
                password=password,
                base_url=base_url,
                is_superadmin=is_superadmin,
                verbose=(i < verbose_first),
                verify_ssl=verify_ssl,
                idempotency_replays=idempotency_replays,
            )
        )

    if superadmin_count == 0 and not superadmin_email:
        print(
            "[WARN] No --superadmin-email provided; positive superadmin access "
            "will be skipped, but regular-user denial is still tested."
        )

    print(f"Zyntry Load Test — {total_users} users, {num_orgs} orgs")
    print(f"  Batch size   : {batch_size}")
    print(f"  Ramp interval: {ramp_interval}s")
    print(f"  Max concurrent: {max_concurrent}")
    print(f"  Base URL     : {base_url}")
    print(f"  Superadmin accounts: {superadmin_count}")
    print(f"  Idempotency replays/user: {idempotency_replays}")
    print(
        "\nNOTE: Email verification is skipped because the verify-email endpoint "
        "requires a token delivered out-of-band via email."
    )
    print(
        "NOTE: The public register endpoint auto-creates one org per user, so "
        "actual org count equals total-users.\n"
    )

    start_time = time.time()
    total_batches = (total_users + batch_size - 1) // batch_size

    for batch_idx, batch_start in enumerate(range(0, total_users, batch_size), start=1):
        batch = users[batch_start : batch_start + batch_size]
        print(
            f"[{time.strftime('%H:%M:%S')}] Batch {batch_idx}/{total_batches} — {len(batch)} users"
        )
        await run_batch(batch, base_url, max_concurrent, batch_idx, total_batches)
        next_batch = batch_start + batch_size
        if next_batch < total_users:
            await asyncio.sleep(ramp_interval)

    elapsed = time.time() - start_time
    stats, five_xx = metrics.summarize()
    print_summary(stats, five_xx, elapsed)


if __name__ == "__main__":
    asyncio.run(async_main())
