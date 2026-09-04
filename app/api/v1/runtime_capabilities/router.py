from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_runtime_access
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.capabilities import (
    CrossSourceJoinRequest,
    CrossSourceJoinResponse,
    EvaluationRunRequest,
    EvaluationRunResponse,
    EvaluationCase,
    EvaluationSuiteRead,
    EvaluationSuiteUpdate,
    RuntimeAccessPolicy,
    RuntimeAccessPolicyUpdate,
    RuntimeBudgetPolicy,
    RuntimeBudgetPolicyUpdate,
    RuntimeCapabilitiesRead,
)
from app.services.runtime_capabilities import (
    authorize_runtime_request,
    evaluate_case,
    join_source_records,
    normalize_access_policy,
    normalize_budget_policy,
    resolve_role,
)
from app.services.ocr import ocr_available
from app.services.runtime_security import normalize_runtime_security_policy, redact_pii

router = APIRouter(prefix="/runtimes", tags=["runtime capabilities"])


async def _load(runtime_id: str, user: User, db: AsyncSession):
    try:
        rid = uuid.UUID(runtime_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid runtime id") from exc
    return await require_runtime_access(rid, user, db)


def _config(runtime) -> dict:
    return dict(runtime.config or {}) if isinstance(runtime.config, dict) else {}


@router.get("/{runtime_id}/capabilities", response_model=RuntimeCapabilitiesRead)
async def get_runtime_capabilities(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeCapabilitiesRead:
    runtime = await _load(runtime_id, current_user, db)
    config = _config(runtime)
    return RuntimeCapabilitiesRead(
        runtime_id=runtime.id,
        access_control=RuntimeAccessPolicy(**normalize_access_policy(config.get("access_control"))),
        budgets=RuntimeBudgetPolicy(**normalize_budget_policy(config.get("budgets"))),
        feature_flags={
            "cross_source_joins": True,
            "approval_inbox": True,
            "scheduled_workflows": True,
            "webhook_triggers": True,
            "evaluation_suites": True,
            "ocr_extraction": ocr_available(),
            "streaming_progress": True,
            "custom_openapi_tools": True,
        },
    )


@router.get("/{runtime_id}/access-policy", response_model=RuntimeAccessPolicy)
async def get_access_policy(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeAccessPolicy:
    runtime = await _load(runtime_id, current_user, db)
    return RuntimeAccessPolicy(**normalize_access_policy(_config(runtime).get("access_control")))


@router.put("/{runtime_id}/access-policy", response_model=RuntimeAccessPolicy)
async def update_access_policy(
    runtime_id: str,
    body: RuntimeAccessPolicyUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeAccessPolicy:
    runtime = await _load(runtime_id, current_user, db)
    if not current_user.is_superuser and runtime.user_id != current_user.id:
        role = resolve_role(current_user)
        if role not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Only runtime owners or administrators can update access policy")
    config = _config(runtime)
    policy = normalize_access_policy(body.model_dump())
    config["access_control"] = policy
    await UnitOfWork(db).runtimes.update(runtime, config=config)
    await db.commit()
    return RuntimeAccessPolicy(**policy)


@router.get("/{runtime_id}/budget", response_model=RuntimeBudgetPolicy)
async def get_runtime_budget(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeBudgetPolicy:
    runtime = await _load(runtime_id, current_user, db)
    return RuntimeBudgetPolicy(**normalize_budget_policy(_config(runtime).get("budgets")))


@router.put("/{runtime_id}/budget", response_model=RuntimeBudgetPolicy)
async def update_runtime_budget(
    runtime_id: str,
    body: RuntimeBudgetPolicyUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> RuntimeBudgetPolicy:
    runtime = await _load(runtime_id, current_user, db)
    if not current_user.is_superuser and runtime.user_id != current_user.id and resolve_role(current_user) not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only runtime owners or administrators can update budgets")
    config = _config(runtime)
    budget = normalize_budget_policy(body.model_dump())
    config["budgets"] = budget
    await UnitOfWork(db).runtimes.update(runtime, config=config)
    await db.commit()
    return RuntimeBudgetPolicy(**budget)


@router.post("/{runtime_id}/sources/join", response_model=CrossSourceJoinResponse)
async def join_runtime_sources(
    runtime_id: str,
    body: CrossSourceJoinRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> CrossSourceJoinResponse:
    runtime = await _load(runtime_id, current_user, db)
    try:
        authorize_runtime_request(runtime, current_user, sources=[item.source for item in body.sources])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    joined = join_source_records(body)
    if normalize_runtime_security_policy(runtime.security_policies).get("pii_redaction"):
        joined = redact_pii(joined)
    return CrossSourceJoinResponse(**joined)


@router.get("/{runtime_id}/evaluations", response_model=EvaluationSuiteRead)
async def get_evaluation_suite(
    runtime_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> EvaluationSuiteRead:
    runtime = await _load(runtime_id, current_user, db)
    suite = _config(runtime).get("evaluation_suite") or {}
    return EvaluationSuiteRead(
        runtime_id=runtime.id,
        version=int(suite.get("version") or 1),
        cases=suite.get("cases") or [],
        updated_at=suite.get("updated_at"),
    )


@router.put("/{runtime_id}/evaluations", response_model=EvaluationSuiteRead)
async def update_evaluation_suite(
    runtime_id: str,
    body: EvaluationSuiteUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> EvaluationSuiteRead:
    runtime = await _load(runtime_id, current_user, db)
    if not current_user.is_superuser and runtime.user_id != current_user.id and resolve_role(current_user) not in {"owner", "admin", "developer"}:
        raise HTTPException(status_code=403, detail="This role cannot edit evaluation suites")
    config = _config(runtime)
    previous = config.get("evaluation_suite") or {}
    cases = []
    for case in body.cases:
        data = case.model_dump()
        data["id"] = data.get("id") or uuid.uuid4().hex
        cases.append(data)
    suite = {
        "version": int(previous.get("version") or 0) + 1,
        "cases": cases,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    config["evaluation_suite"] = suite
    await UnitOfWork(db).runtimes.update(runtime, config=config)
    await db.commit()
    return EvaluationSuiteRead(runtime_id=runtime.id, **suite)


@router.post("/{runtime_id}/evaluations/run", response_model=EvaluationRunResponse)
async def run_evaluation_suite(
    runtime_id: str,
    body: EvaluationRunRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> EvaluationRunResponse:
    runtime = await _load(runtime_id, current_user, db)
    suite = _config(runtime).get("evaluation_suite") or {}
    cases = suite.get("cases") or []
    normalized_cases = []
    for raw_case in cases:
        try:
            normalized_cases.append(raw_case if isinstance(raw_case, EvaluationCase) else EvaluationCase.model_validate(raw_case))
        except Exception:
            continue
    results = [evaluate_case(case, body.responses.get(case.id or case.name)) for case in normalized_cases]
    passed = sum(1 for item in results if item.passed)
    score = sum(item.score for item in results) / len(results) if results else 0.0
    return EvaluationRunResponse(
        runtime_id=runtime.id,
        version=int(suite.get("version") or 1),
        total=len(results),
        passed=passed,
        score=round(score, 4),
        results=results,
    )
