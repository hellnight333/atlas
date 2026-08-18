"""The endpoints the control UI runs on.

Everything an operator does from a browser goes through here: submit an
objective, watch it run, read what it decided and why, approve what it may not
do alone.

Two properties this layer must preserve, because they are the ones easiest to
lose when a UI is added.

**Objectives run as durable jobs.** Submitting one starts a detached job and
returns immediately. The browser tab is a viewer, never the thing keeping work
alive — closing it, losing the network or restarting the API must not stop a
deployment halfway.

**Scopes are checked per route, and approval is separate from scope.** Holding
PUBLISH means a publish may be proposed; it still queues for a human. A scope is
a standing grant, an approval is a decision about one specific thing, and
collapsing the two is how an autonomous system ends up publishing on its own
authority.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import Scope, User, requires
from ..jobs import JobRunner, collect

#: Where an objective's work happens. The runner script is deployed alongside
#: the kernel rather than generated per request: a control plane that writes and
#: executes fresh scripts on demand is a shell by another name.
OBJECTIVE_RUNNER = Path("/opt/qevik/run_objective.py")
WORKING_DIR = Path("/opt/qevik/atlas")


class ObjectiveRequest(BaseModel):
    """A natural-language instruction. Qevik decides the steps."""

    objective: str = Field(min_length=8, max_length=4000)
    #: Publishing anywhere the public can reach requires this, and it is
    #: recorded against the requesting user rather than inferred.
    authorise_publish: bool = False
    slug: str = ""


class ObjectiveAccepted(BaseModel):
    job_id: str
    objective: str
    submitted_by: str
    publish_authorised: bool


def build_router(runner: JobRunner | None = None) -> APIRouter:
    runner = runner or JobRunner()
    router = APIRouter(prefix="/control", tags=["control"])

    # -- submitting work --------------------------------------------------

    @router.post("/objectives", response_model=ObjectiveAccepted)
    def submit(
        body: ObjectiveRequest, user: User = Depends(requires(Scope.EXECUTE))
    ) -> ObjectiveAccepted:
        """Start an objective. Returns as soon as it is running, not when done."""
        if body.authorise_publish:
            # Asking to publish requires the scope, checked here rather than
            # when the plan reaches its deploy step — refusing early is cheaper
            # than refusing after a site has been built.
            try:
                user.require(Scope.PUBLISH)
            except Exception as error:  # noqa: BLE001 - re-raised as HTTP
                raise HTTPException(status_code=403, detail=str(error)) from error

        if not OBJECTIVE_RUNNER.is_file():
            raise HTTPException(
                status_code=503,
                detail=f"objective runner missing at {OBJECTIVE_RUNNER}; deploy it first",
            )

        argv = [
            str(WORKING_DIR / ".venv/bin/python"),
            str(OBJECTIVE_RUNNER),
            body.objective,
            body.slug or "",
            "publish" if body.authorise_publish else "no-publish",
        ]
        record = runner.start(
            argv,
            kind="objective",
            cwd=str(WORKING_DIR),
            note=f"{user.username}: {body.objective[:120]}",
        )
        return ObjectiveAccepted(
            job_id=record.id,
            objective=body.objective,
            submitted_by=user.username,
            publish_authorised=body.authorise_publish,
        )

    # -- watching it ------------------------------------------------------

    @router.get("/jobs", dependencies=[Depends(requires(Scope.READ))])
    def jobs(limit: int = 30) -> list[dict]:
        return [
            {
                **record.model_dump(mode="json"),
                "phase": _phase(runner, record),
                "duration_seconds": record.duration_seconds,
            }
            for record in runner.list(limit=limit)
        ]

    @router.get("/jobs/{job_id}", dependencies=[Depends(requires(Scope.READ))])
    def job(job_id: str) -> dict:
        record = _get(runner, job_id)
        artifacts = runner.artifacts(job_id)
        return {
            **record.model_dump(mode="json"),
            "phase": _phase(runner, record),
            "duration_seconds": record.duration_seconds,
            "command": record.command,
            "artifacts": [{"name": Path(p).name, "path": p, "bytes": _size(p)} for p in artifacts],
            # The three files a run writes about itself, parsed so the UI does
            # not have to know their names.
            **_run_documents(artifacts),
        }

    @router.get("/jobs/{job_id}/logs", dependencies=[Depends(requires(Scope.READ))])
    def logs(job_id: str, stream: str = "stdout", tail: int = 200) -> dict:
        _get(runner, job_id)
        return {
            "stream": stream,
            "text": runner.output(job_id, stream=stream, tail=max(1, min(tail, 2000))),
        }

    @router.post("/jobs/{job_id}/stop")
    def stop(job_id: str, user: User = Depends(requires(Scope.DESTRUCTIVE))) -> dict:
        """Stopping a running job can leave a half-finished deployment, which is
        why it needs the destructive scope rather than merely execute."""
        return _get(runner, job_id, then=lambda: runner.stop(job_id)).model_dump(mode="json")

    # -- the system -------------------------------------------------------

    @router.get("/health", dependencies=[Depends(requires(Scope.READ))])
    def health() -> dict:
        report = collect(runner)
        return {**report.model_dump(mode="json"), "healthy": report.healthy}

    @router.get("/capabilities", dependencies=[Depends(requires(Scope.READ))])
    def capabilities() -> dict:
        """What Qevik can actually do, and what is blocked on what.

        Reported from the running system rather than from a document, because a
        document is a claim and this is an observation.
        """
        from ..actions import default_action_runner
        from ..actions.planning import default_planner

        planner = default_planner()
        return {
            "actions": default_action_runner().registered(),
            "planner": {
                "model_available": planner.available,
                "preferred_model": planner.preferred,
                "fallback": "deterministic",
            },
        }

    return router


def _get(runner: JobRunner, job_id: str, then=None):
    from ..jobs import JobError

    try:
        return then() if then else runner.get(job_id)
    except JobError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _size(path: str) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def _run_documents(artifacts: list[str]) -> dict:
    """Parse the plan, provenance and outcome a run leaves behind.

    Missing files are normal — a job that failed during planning has no
    provenance — so absence is reported as null rather than as an error.
    """
    found: dict[str, object] = {"plan": None, "provenance": None, "outcome": None}
    for path in artifacts:
        name = Path(path).stem
        if name in found:
            try:
                found[name] = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                found[name] = None
    return found


def _phase(runner: JobRunner, record) -> str:
    """A coarse phase for the dashboard, read from the job's own output.

    Derived from what the run has printed rather than tracked in a separate
    state machine: a second source of truth about progress is a second thing
    that can be wrong, and this one cannot drift because it *is* the output.
    """
    from ..jobs import JobState

    if record.state is JobState.LOST:
        return "lost"
    if record.state is JobState.FAILED:
        return "failed"
    if record.state is JobState.SUCCEEDED:
        return "completed"

    try:
        tail = runner.output(record.id, tail=60)
    except Exception:  # noqa: BLE001 - a phase is never worth an error
        return "running"
    for marker, phase in (
        ("browser.operate", "verifying"),
        ("site.deploy", "deploying"),
        ("[attempt 2]", "repairing"),
        ("code.execute", "testing"),
        ("code.write", "generating"),
        ("code.generate", "generating"),
        ("web.search", "researching"),
        ("PLAN", "planning"),
    ):
        if marker in tail:
            return phase
    return "queued"


def install(app, runner: JobRunner | None = None) -> None:
    app.include_router(build_router(runner))
