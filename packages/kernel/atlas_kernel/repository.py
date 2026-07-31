from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from .db import SessionLocal, init_db
from .models import Job, JobStatus, Run, Step, StepStatus


class AtlasRepository:
    def __init__(self) -> None:
        init_db()

    def create_run(self, run: Run) -> Run:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_runs (id, title, description, studio, status, created_at)
                VALUES (:id, :title, :description, :studio, :status, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": run.id,
                    "title": run.title,
                    "description": run.description,
                    "studio": run.studio,
                    "status": run.status.value,
                    "created_at": run.created_at,
                },
            )
            session.commit()
        return run

    def create_step(self, step: Step) -> Step:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_steps (id, run_id, action, status, payload, depends_on, created_at)
                VALUES (:id, :run_id, :action, :status, :payload, :depends_on, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": step.id,
                    "run_id": step.run_id,
                    "action": step.action,
                    "status": step.status.value,
                    "payload": json.dumps(step.payload),
                    "depends_on": json.dumps(step.depends_on),
                    "created_at": step.created_at,
                },
            )
            session.commit()
        return step

    def create_job(self, job: Job) -> Job:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_jobs (id, run_id, action, payload, status, attempts, priority, capability_req, provider_name, output, created_at)
                VALUES (:id, :run_id, :action, :payload, :status, :attempts, :priority, :capability_req, :provider_name, :output, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": job.id,
                    "run_id": job.run_id,
                    "action": job.action,
                    "payload": json.dumps(job.payload),
                    "status": job.status.value,
                    "attempts": job.attempts,
                    "priority": job.priority,
                    "capability_req": json.dumps(job.capability_req),
                    "provider_name": job.provider_name,
                    "output": json.dumps(job.output),
                    "created_at": job.created_at,
                },
            )
            session.commit()
        return job

    def list_runs(self) -> list[Run]:
        with SessionLocal() as session:
            rows = session.execute(text("SELECT id, title, description, studio, status, created_at FROM atlas_runs ORDER BY created_at DESC")).fetchall()
        return [Run(id=row[0], title=row[1], description=row[2], studio=row[3], status=JobStatus(row[4]), created_at=row[5]) for row in rows]

    def get_run(self, run_id: str) -> Run | None:
        with SessionLocal() as session:
            row = session.execute(text("SELECT id, title, description, studio, status, created_at FROM atlas_runs WHERE id = :run_id"), {"run_id": run_id}).fetchone()
        if row is None:
            return None
        return Run(id=row[0], title=row[1], description=row[2], studio=row[3], status=JobStatus(row[4]), created_at=row[5])

    def list_jobs(self) -> list[Job]:
        with SessionLocal() as session:
            rows = session.execute(text("SELECT id, run_id, action, payload, status, attempts, priority, capability_req, provider_name, output, created_at FROM atlas_jobs ORDER BY created_at DESC")).fetchall()
        return [Job(
            id=row[0],
            run_id=row[1],
            action=row[2],
            payload=row[3] if isinstance(row[3], dict) else json.loads(row[3]) if row[3] else {},
            status=JobStatus(row[4]),
            attempts=row[5],
            priority=row[6],
            capability_req=row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {},
            provider_name=row[8],
            output=row[9] if isinstance(row[9], dict) else json.loads(row[9]) if row[9] else {},
            created_at=row[10],
        ) for row in rows]

    def list_jobs_by_run(self, run_id: str) -> list[Job]:
        with SessionLocal() as session:
            rows = session.execute(text("SELECT id, run_id, action, payload, status, attempts, priority, capability_req, provider_name, output, created_at FROM atlas_jobs WHERE run_id = :run_id ORDER BY created_at DESC"), {"run_id": run_id}).fetchall()
        return [Job(
            id=row[0],
            run_id=row[1],
            action=row[2],
            payload=row[3] if isinstance(row[3], dict) else json.loads(row[3]) if row[3] else {},
            status=JobStatus(row[4]),
            attempts=row[5],
            priority=row[6],
            capability_req=row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {},
            provider_name=row[8],
            output=row[9] if isinstance(row[9], dict) else json.loads(row[9]) if row[9] else {},
            created_at=row[10],
        ) for row in rows]

    def update_job_status(self, job_id: str, status: JobStatus, provider_name: str | None = None, output: dict[str, Any] | None = None) -> None:
        with SessionLocal() as session:
            query = "UPDATE atlas_jobs SET status = :status"
            params = {"status": status.value, "job_id": job_id}
            if provider_name is not None:
                query += ", provider_name = :provider_name"
                params["provider_name"] = provider_name
            if output is not None:
                query += ", output = :output"
                params["output"] = json.dumps(output)
            query += " WHERE id = :job_id"
            session.execute(text(query), params)
            session.commit()

    def update_run_status(self, run_id: str, status: JobStatus) -> None:
        with SessionLocal() as session:
            session.execute(text("UPDATE atlas_runs SET status = :status WHERE id = :run_id"), {"status": status.value, "run_id": run_id})
            session.commit()
