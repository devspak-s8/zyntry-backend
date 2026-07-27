from __future__ import annotations

from app.workers.celery_app import celery_app


@celery_app.task(name="app.tasks.workflows.run")
def run_workflow(workflow_id: str) -> None: ...
