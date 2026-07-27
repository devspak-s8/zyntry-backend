from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflows import Workflow, WorkflowExecution


class WorkflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, limit: int = 50, offset: int = 0) -> list[Workflow]:
        result = await self.session.execute(
            select(Workflow).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def list_active(self) -> list[Workflow]:
        result = await self.session.execute(
            select(Workflow).where(Workflow.status != "archived")
        )
        return list(result.scalars().all())

    async def get_by_project(self, project_id: uuid.UUID) -> list[Workflow]:
        result = await self.session.execute(
            select(Workflow).where(Workflow.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get(self, workflow_id: uuid.UUID) -> Workflow | None:
        result = await self.session.execute(
            select(Workflow).where(Workflow.id == workflow_id)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs: Any) -> Workflow:
        workflow = Workflow(**kwargs)
        self.session.add(workflow)
        await self.session.flush()
        return workflow

    async def update(self, workflow: Workflow, **kwargs: Any) -> Workflow:
        for key, value in kwargs.items():
            if hasattr(workflow, key):
                setattr(workflow, key, value)
        await self.session.flush()
        return workflow

    async def delete(self, workflow: Workflow) -> None:
        await self.session.delete(workflow)


class WorkflowExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_workflow(self, workflow_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[WorkflowExecution]:
        result = await self.session.execute(
            select(WorkflowExecution)
            .where(WorkflowExecution.workflow_id == workflow_id)
            .order_by(WorkflowExecution.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def create(self, **kwargs: Any) -> WorkflowExecution:
        execution = WorkflowExecution(**kwargs)
        self.session.add(execution)
        await self.session.flush()
        return execution

    async def update(self, execution: WorkflowExecution, **kwargs: Any) -> WorkflowExecution:
        for key, value in kwargs.items():
            if hasattr(execution, key):
                setattr(execution, key, value)
        await self.session.flush()
        return execution
