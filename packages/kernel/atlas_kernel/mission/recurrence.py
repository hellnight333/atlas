"""Work that repeats, expressed as missions rather than as a timer.

## Why this exists, concretely

On 2026-08-26 the database backup on `qevik-core-01` was found to have failed
every night since 2026-08-18. Eight days, no verified backup, and **no signal
anywhere** — not in the console, not on the phone, not in any report. The unit
ran as `User=qevik` and the script tried to read a root-owned `0600` env file,
so it exited 1 into the journal and nothing else happened. Somebody would have
discovered it when they needed to restore.

That is not a bug in a backup script. It is what happens to any scheduled work
that lives outside the mission system: a systemd timer has no budget, no policy,
no evidence, no report, and no way to appear on a screen a person actually
looks at. The three things Qevik already does well — decide deterministically
whether work may run, prove what it did, and show a person the result — all stop
at the edge of the mission fabric.

So recurring work becomes missions. Everything downstream is then unchanged:
the scheduler orders it, the atomic claim guards it, the worker proves it, the
report survives, and a failure shows up in exactly the place a failure of any
other mission shows up.

## What this module is not

It is **not a scheduler** and it is **not an orchestrator**. It creates missions
and stops. It never claims, never dispatches, never runs an agent, and never
decides whether work may proceed — `mission.policy` decides that, on the same
call every other mission goes through. There is one queue and one worker path,
and this adds neither.

## Three rules that are easy to get wrong

**Only the latest occurrence fires.** A daily job whose host was down for eight
days produces *one* mission, not eight. Eight market scans in a row cost eight
times as much to tell you what one current scan tells you, and eight backups of
the same database is not eight times the safety. Work where every occurrence
genuinely matters — billing periods, statements — is not a recurrence and must
not be modelled as one.

**An occurrence fires once.** The key is derived from the recurrence and the
occurrence instant, so it is the same string in every process that computes it.
Two guards stand behind it, deliberately different in kind: the caller holds the
occurrence key through the existing `Claims` (the same `FOR UPDATE SKIP LOCKED`
primitive missions use — no second claim system), and this module independently
refuses an occurrence a mission already carries. A lock can be reclaimed after a
crash; the mission is a fact.

**A slow occurrence does not stack.** If yesterday's mission is still running,
today's does not start. Overlap is how a job that usually takes ten minutes and
occasionally takes thirty hours quietly becomes four copies competing over the
same files.

## Unattended is a property of the work, not of the hour

`policy.decide` is asked the same question here as anywhere, with one difference:
a recurrence states whether its work changes Qevik's own source. Nothing that
does may run unattended, whatever the hour — self-modification stays gated on a
person, and a schedule is not a person. A recurrence that says otherwise about
work that does modify Qevik would be lying to policy, which is why the set of
recurrences lives in code (`RECURRENCES`) beside `AGENTS` and `EXECUTORS`, and
not in a table somebody can edit at runtime.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from ..opportunity.tenancy import TenantId
from . import origins, service
from .models import TERMINAL, Mission, MissionStatus, Plan, PlanStep

#: The shortest period a recurrence may declare. A recurrence is a way to put
#: work in a queue; one that fires every few seconds is a queue flood with a
#: calendar attached. Five minutes is far below any real cadence and still far
#: above the range where a mistake becomes an incident.
MINIMUM_PERIOD = timedelta(minutes=5)


class Hold(StrEnum):
    """Why an occurrence did not fire. Every one of these is a normal outcome.

    Named rather than boolean because "nothing fired" has several very different
    meanings, and a log that cannot distinguish "not due yet" from "yesterday's
    run never finished" is one nobody can act on.
    """

    #: Switched off. Still declared, still visible.
    DISABLED = "disabled"
    #: `at` is before the recurrence's first occurrence.
    NOT_STARTED = "not-started"
    #: Due, and a mission for this exact occurrence already exists.
    ALREADY_CREATED = "already-created"
    #: An earlier occurrence is still running. Deliberately not an error.
    PREVIOUS_UNFINISHED = "previous-unfinished"


class Recurrence(BaseModel):
    """Work that should happen repeatedly, and the plan it happens by.

    The plan is **declared here**, not produced by a model when the occurrence
    comes due. A recurring job whose steps are invented afresh each night is a
    different job each night, and there is no useful sense in which a person
    approved it once.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    tenant_id: str
    title: str
    #: Fixed, reviewed, and the same on every occurrence.
    plan: Plan
    #: Who carries it out. Must exist in the agent registry — `policy` treats an
    #: unknown agent as having an unbounded blast radius, which is correct here
    #: too: unattended work by something nobody declared is the worst case.
    agent_id: str
    #: The gap between occurrences.
    every: timedelta
    #: The first occurrence. Every later one is `anchor + n * every`, so the
    #: series is a pure function of two values and never drifts by accumulating
    #: "now + every" rounding.
    anchor: datetime
    description: str = ""
    enabled: bool = True
    #: Which repository this works on, **by name**. Not a boolean about whether
    #: it changes Qevik: a boolean is a claim that can disagree with what the
    #: worker actually hands the mission, and the first version of this file had
    #: exactly that gap. The name resolves through the origin registry, and the
    #: kind — and therefore whether a person is asked — comes from the resolved
    #: origin rather than from anything declared here.
    origin_name: str = origins.DEFAULT_NAME
    requested_by: str = "recurrence"
    notes: str = ""

    @field_validator("every")
    @classmethod
    def _sane_period(cls, value: timedelta) -> timedelta:
        if value < MINIMUM_PERIOD:
            raise ValueError(
                f"a recurrence may not fire more often than every "
                f"{MINIMUM_PERIOD}; {value} would flood the queue")
        return value

    @field_validator("anchor")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("the anchor needs a timezone; a naive moment means "
                             "a different thing on every host")
        return value

    @field_validator("id", "tenant_id", "title", "agent_id")
    @classmethod
    def _present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a recurrence needs an id, tenant, title and agent")
        return value.strip()


class Firing(BaseModel):
    """What `assess` decided, and why, in terms a log can print."""

    model_config = ConfigDict(frozen=True)

    recurrence_id: str
    #: The occurrence instant that should fire, when one should.
    occurrence: datetime | None = None
    #: The deterministic key for that occurrence.
    key: str = ""
    hold: Hold | None = None
    detail: str = ""

    @property
    def fires(self) -> bool:
        return self.occurrence is not None

    def summary(self) -> dict:
        return {"recurrence_id": self.recurrence_id,
                "occurrence": self.occurrence.isoformat() if self.occurrence else None,
                "key": self.key, "fires": self.fires,
                "hold": self.hold.value if self.hold else None,
                "detail": self.detail}


#: Statuses after which the next occurrence may fire. Derived from the canonical
#: `TERMINAL` rather than written out again — the first draft of this line spelled
#: the set by hand and immediately disagreed with it, which is how two lists that
#: must match stop matching.
#:
#: BLOCKED is added, and it is the interesting one. A blocked mission is not
#: terminal: somebody can resolve the blocker and it continues. But the overlap
#: guard exists to stop two *live* runs competing, and a blocked mission holds no
#: worker and touches nothing. Treating it as live would mean one blocked run
#: stops the recurrence for good — a schedule that dies in silence, which is the
#: precise failure this module was written after. Better one visible blocked
#: mission per occurrence, each a fact about that day, than a series that
#: quietly ends.
_SETTLED = frozenset(s.value for s in (*TERMINAL, MissionStatus.BLOCKED))


def key_for(recurrence_id: str, occurrence: datetime) -> str:
    """The identity of one occurrence. The same string in every process.

    Computed from the two values that define the occurrence and nothing else —
    no clock, no counter, no random part. That is what lets two workers reach
    the same conclusion about whether tonight's run already exists.
    """
    stamp = occurrence.astimezone(UTC).replace(microsecond=0)
    return f"{recurrence_id}@{stamp.isoformat().replace('+00:00', 'Z')}"


def latest_due(recurrence: Recurrence, *, at: datetime) -> datetime | None:
    """The most recent occurrence at or before `at`, or None before the anchor.

    Deliberately singular. See the module note: a missed week produces one
    mission, not a week of them.
    """
    if at < recurrence.anchor:
        return None
    elapsed = at - recurrence.anchor
    periods = elapsed // recurrence.every
    return recurrence.anchor + periods * recurrence.every


def next_after(recurrence: Recurrence, *, at: datetime) -> datetime:
    """When this fires next. For a status screen, so "why is nothing happening"
    has an answer that is a time rather than a shrug."""
    if at < recurrence.anchor:
        return recurrence.anchor
    current = latest_due(recurrence, at=at)
    assert current is not None                     # at >= anchor, so it exists
    return current + recurrence.every


def assess(recurrence: Recurrence, *, at: datetime,
           missions: list[dict]) -> Firing:
    """Whether this recurrence should create a mission now.

    `missions` are folded mission summaries for the tenant — the same read model
    every other surface uses. No separate record of "when did this last run" is
    kept, because a second record is a second thing that can be wrong, and the
    missions already say precisely what was created and how it ended.
    """
    if not recurrence.enabled:
        return Firing(recurrence_id=recurrence.id, hold=Hold.DISABLED,
                      detail="this recurrence is switched off")

    occurrence = latest_due(recurrence, at=at)
    if occurrence is None:
        return Firing(recurrence_id=recurrence.id, hold=Hold.NOT_STARTED,
                      detail=f"the first occurrence is "
                             f"{recurrence.anchor.isoformat(timespec='minutes')}")

    key = key_for(recurrence.id, occurrence)
    mine = [m for m in missions
            if (m.get("occurrence") or "").startswith(f"{recurrence.id}@")]

    if any(m.get("occurrence") == key for m in mine):
        return Firing(recurrence_id=recurrence.id, hold=Hold.ALREADY_CREATED,
                      key=key, detail=f"{key} already has a mission")

    unfinished = [m for m in mine
                  if m.get("status") not in _SETTLED]
    if unfinished:
        held = unfinished[0]
        return Firing(
            recurrence_id=recurrence.id, hold=Hold.PREVIOUS_UNFINISHED, key=key,
            detail=(f"{held.get('occurrence')} is still "
                    f"{held.get('status')}; a slow run must not stack"))

    return Firing(recurrence_id=recurrence.id, occurrence=occurrence, key=key,
                  detail=f"due at {occurrence.isoformat(timespec='minutes')}")



def enqueue(recurrence: Recurrence, firing: Firing, *,
            tenant: TenantId | None, origin: origins.Origin
            ) -> tuple[Mission, tuple[object, ...]]:
    """Create the mission for a firing, through the ordinary mission path.

    Returns the mission and the events to persist. Three calls, all existing:
    `service.create`, a transition to PLANNING, then `service.attach_plan` —
    which runs `policy.decide` and routes the mission to QUEUED or
    AWAITING_APPROVAL exactly as it would for work a person typed in. A
    recurrence cannot reach the queue by any route a person's request could not.

    `origin` is **resolved by the caller** and passed in, rather than looked up
    from the name here. The caller is the worker, which owns the registry, and
    resolving there means a recurrence naming an origin nobody registered fails
    when the mission would be created rather than after it exists — and that
    whether a person is asked comes from the origin the worker will actually
    use, not from a field the declaration could have set to anything.
    """
    if not firing.fires:
        raise ValueError(f"{recurrence.id} is not firing: {firing.detail}")
    if origin.name != recurrence.origin_name:
        raise ValueError(
            f"{recurrence.id} declares origin {recurrence.origin_name!r} but was "
            f"given {origin.name!r}. Creating the mission anyway would record "
            "one repository and use another.")

    mission, created = service.create(
        tenant=tenant, title=recurrence.title,
        description=recurrence.description, requested_by=recurrence.requested_by,
        occurrence=firing.key, origin_name=origin.name)
    # DRAFT -> PLANNING -> (QUEUED | AWAITING_APPROVAL). The middle step is not
    # ceremony: `ALLOWED` refuses `draft -> queued` outright, which is the state
    # machine correctly rejecting a mission that reached a queue without ever
    # having been planned. A recurrence takes the same three steps a person's
    # request takes, in the same order, through the same functions.
    mission, planning = service.transition(
        mission, MissionStatus.PLANNING, tenant=tenant,
        actor=recurrence.requested_by,
        note=f"recurring: {firing.key}")
    mission, planned = service.attach_plan(
        mission, recurrence.plan, tenant=tenant, actor=recurrence.requested_by,
        agent_id=recurrence.agent_id,
        modifies_qevik_itself=origin.modifies_qevik_itself)
    return mission, (created, planning, planned)


# ============================================ the declared recurrences
#
# In code, beside `AGENTS` and `EXECUTORS`, for the reason given in the module
# note: which origin a recurrence names decides whether a person is asked, and a
# decision policy relies on must not be editable at runtime. Adding one is a
# change to Qevik's own source — which is itself a mission a person approves.

#: The production tenant. Named here because a recurrence is deployment
#: configuration expressed in code; `declared(tenant)` filters on it, so a
#: deployment with a different tenant simply gets none of these.
QEVIK_TENANT = "tenant-qevik"

#: Runs every night. Cheap, writes only under `reports/`, and works in an
#: **empty** origin — no source repository, so nothing is at risk and no person
#: is asked. That combination is the only one that reaches a queue unattended,
#: and it is the whole reason the origin registry had to come first.
_CANARY_PLAN = Plan(
    goal="prove the whole execution path still works, unattended",
    why=("A path that is only exercised when somebody asks for something is a "
         "path that breaks quietly. The backup on this host failed every night "
         "from 2026-08-18 to 2026-08-26 — eight days — and nothing reported it, "
         "because it ran as a systemd timer rather than as a mission. This is "
         "the same work done the other way round: if the scheduler, the claim, "
         "the workspace, the sandbox, the agent, the evidence or the report "
         "stops working, a failed mission appears on the phone the next "
         "morning instead of being discovered during a restore."),
    steps=(
        PlanStep(order=1, title="write into the workspace",
                 why="proves the workspace exists and is writable",
                 files=("reports/canary.md",)),
        PlanStep(order=2, title="read it back",
                 why="proves what was written survives the step boundary"),
        PlanStep(order=3, title="confirm nothing outside the workspace is reachable",
                 why="proves the sandbox is still confining, not merely present"),
    ),
    test_plan="each step reports pass or fail, and the evidence is in the report",
    security_impact=("None. Empty origin, no network, no credentials, and every "
                     "effect is inside a discardable repository."),
    rollback="nothing to roll back; the mission writes nowhere that persists",
    estimated_cost=0.0,
    cost_status="REPORTED",
    approval_required=False,
)

#: Discovery's plan. Writes nothing outside `reports/`, works in an **empty**
#: origin — it has no source repository, because what it changes is the business
#: memory in Postgres, not a checkout — and therefore reaches the queue with
#: nobody asked.
#:
#: What it may *do* with what it finds is a separate question with a separate
#: answer: every outward action a signal suggests carries `needs_approval`, and
#: `policy.decide` is what actually gates it. Discovery running unattended and
#: contacting nobody unattended are both true at once, and they have to be.
_DISCOVERY_PLAN = Plan(
    goal="Look at a market and record what was actually there",
    why=("A market that was scanned once and written down is a market nobody "
         "has looked at since. Businesses appear, sites change, and the value "
         "of the memory is that it is current — but only a scheduled scan keeps "
         "it that way, and a scan somebody has to remember to run is one that "
         "stops being run."),
    steps=(
        PlanStep(order=1, title="fetch what the recipe names",
                 why="through the guarded fetcher: budget, robots, and every "
                     "resolved address on every redirect hop",
                 files=("reports/discovery.md",)),
        PlanStep(order=2, title="resolve each sighting against memory",
                 why="strong keys only, so the same clinic from two sources is "
                     "one company"),
        PlanStep(order=3, title="classify and record",
                 why="new to Qevik is a fact about Qevik; only the source can "
                     "make it a fact about the world"),
    ),
    test_plan="the pass reports what it saw, what was new, and to whom",
    security_impact=("Outbound HTTP to public addresses only, refused on every "
                     "private one. No credentials. Contacts nobody."),
    rollback="the sightings are additive; nothing is overwritten",
    estimated_cost=0.0,
    cost_status="REPORTED",
    approval_required=False,
)

RECURRENCES: tuple[Recurrence, ...] = (
    Recurrence(
        id="rec-daily-business-discovery",
        tenant_id=QEVIK_TENANT,
        title="Daily business discovery",
        description=("Scans a declared market and records what was there, so "
                     "the business memory is current rather than a snapshot of "
                     "whenever somebody last ran a script."),
        plan=_DISCOVERY_PLAN,
        agent_id="researcher",
        origin_name=origins.EMPTY_NAME,
        every=timedelta(days=1),
        # 04:15 UTC — inside the night window, clear of the 02:30 canary and the
        # 03:30 backup, so the three do not contend.
        anchor=datetime(2026, 8, 27, 4, 15, tzinfo=UTC),
        requested_by="recurrence",
        notes=("Runs unattended because its origin is EMPTY and it contacts "
               "nobody. Anything it suggests doing about what it finds is "
               "gated by policy like any other outward act."),
    ),
    Recurrence(
        id="rec-execution-canary",
        tenant_id=QEVIK_TENANT,
        title="Nightly execution-path canary",
        description=("Runs the self-check agent end to end so a broken "
                     "execution path is discovered by a failed mission rather "
                     "than by needing one."),
        plan=_CANARY_PLAN,
        agent_id="self-check",
        origin_name=origins.EMPTY_NAME,
        every=timedelta(days=1),
        # 02:30 UTC — inside the scheduler's night window (01:00–06:00) and
        # clear of the 03:30 backup, so the two do not contend for the disk.
        anchor=datetime(2026, 8, 27, 2, 30, tzinfo=UTC),
        requested_by="recurrence",
        notes=("The first unattended recurrence. Reaches the queue with nobody "
               "asked only because its origin is EMPTY; the same plan against "
               "the 'qevik' origin would wait for a person."),
    ),
)


def declared(tenant: TenantId | None = None) -> tuple[Recurrence, ...]:
    """The recurrences for a tenant, or all of them."""
    if tenant is None:
        return RECURRENCES
    return tuple(r for r in RECURRENCES if r.tenant_id == str(tenant))


def describe(at: datetime | None = None) -> list[dict]:
    """Every declared recurrence and when it next fires. For a status screen."""
    moment = at or datetime.now(UTC)
    return [{"id": r.id, "title": r.title, "tenant_id": r.tenant_id,
             "agent_id": r.agent_id, "enabled": r.enabled,
             "every_seconds": r.every.total_seconds(),
             "origin_name": r.origin_name,
             "next_at": next_after(r, at=moment).isoformat(),
             "notes": r.notes}
            for r in RECURRENCES]
