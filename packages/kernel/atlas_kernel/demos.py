"""Demo projects — real workflows, installed as real records.

A demo is not a screenshot or a scripted tour. Installing one creates genuine
projects, automation rules, approval policies and knowledge-graph nodes
through the same services the application uses, so everything a demo shows can
be opened, edited, re-run and deleted like anything else the user made.

**The honesty rule.** A fresh install has no provider credentials. Steps that
need one are marked :attr:`Step.requires_provider` and the UI says so plainly
rather than showing a button that fails. Every demo has a *runnable spine* --
orchestration, automation, governance, lineage -- that executes for real with
no credentials at all, because that part of Atlas genuinely does not need any.

That distinction is the point. Most of what Atlas does is coordination, and
coordination is fully demonstrable offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Category = Literal["content", "automation", "research", "video", "production"]


@dataclass(frozen=True)
class Step:
    """One step of a demo workflow."""

    name: str
    description: str

    #: True when this step calls a model provider. A fresh install has no
    #: credentials, so these are shown as "needs a provider" rather than
    #: offered as buttons that would fail.
    requires_provider: bool = False

    #: Which Atlas subsystem the step exercises. Shown in the UI so a demo
    #: teaches the architecture rather than only producing output.
    subsystem: str = "runtime"

    @property
    def runs_offline(self) -> bool:
        return not self.requires_provider


@dataclass(frozen=True)
class AutomationSpec:
    """An automation rule a demo installs."""

    name: str
    description: str
    trigger: str
    #: Automation rules never call providers -- they enqueue work through the
    #: scheduler. Every rule a demo installs therefore runs offline.
    schedule: str | None = None


@dataclass(frozen=True)
class GraphSeed:
    """A knowledge-graph node and its relationships."""

    key: str
    label: str
    node_type: str
    connects_to: tuple[str, ...] = ()


@dataclass(frozen=True)
class Demo:
    """A complete, installable demonstration."""

    id: str
    name: str
    tagline: str
    description: str
    category: Category
    #: Emoji shown on the demo card. Kept out of the frontend so the catalogue
    #: is one source of truth.
    icon: str
    #: What this demo teaches about Atlas, in the user's language.
    demonstrates: tuple[str, ...]
    steps: tuple[Step, ...]
    automations: tuple[AutomationSpec, ...] = ()
    graph: tuple[GraphSeed, ...] = ()
    #: An approval policy scope, when the demo shows a governance gate.
    approval_scope: str | None = None
    estimated_minutes: int = 2

    @property
    def offline_steps(self) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.runs_offline)

    @property
    def provider_steps(self) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.requires_provider)

    @property
    def runs_fully_offline(self) -> bool:
        return not self.provider_steps

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tagline": self.tagline,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "demonstrates": list(self.demonstrates),
            "estimated_minutes": self.estimated_minutes,
            "runs_fully_offline": self.runs_fully_offline,
            "step_count": len(self.steps),
            "offline_step_count": len(self.offline_steps),
            "provider_step_count": len(self.provider_steps),
            "automation_count": len(self.automations),
            "has_approval_gate": self.approval_scope is not None,
            "steps": [
                {
                    "name": s.name,
                    "description": s.description,
                    "requires_provider": s.requires_provider,
                    "subsystem": s.subsystem,
                }
                for s in self.steps
            ],
            "automations": [
                {
                    "name": a.name,
                    "description": a.description,
                    "trigger": a.trigger,
                    "schedule": a.schedule,
                }
                for a in self.automations
            ],
        }


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

CONTENT_STUDIO = Demo(
    id="content-studio",
    name="AI Content Studio",
    tagline="One brief becomes a researched article and a week of social posts.",
    description=(
        "A publishing pipeline that starts from a single brief. Atlas researches "
        "the topic, drafts the article, holds it for a human edit, then splits the "
        "approved piece into posts sized for each channel. The editorial gate is a "
        "real approval policy: nothing reaches the repurposing stage until a person "
        "approves it, and the approval is recorded in the audit trail."
    ),
    category="content",
    icon="✍️",
    demonstrates=(
        "Approval gates that pause work before a job is created",
        "Knowledge-graph lineage from brief to every published post",
        "Scheduled automation that opens the week's work for you",
    ),
    steps=(
        Step(
            "Capture the brief",
            "Topic, audience, angle and the three questions the piece must answer.",
            subsystem="projects",
        ),
        Step(
            "Research the topic",
            "Gather sources and pull out claims worth citing.",
            requires_provider=True,
            subsystem="research",
        ),
        Step(
            "Build the outline",
            "Structure the argument before any prose is written.",
            requires_provider=True,
            subsystem="workflow-engine",
        ),
        Step(
            "Draft the article",
            "Write the full piece against the outline.",
            requires_provider=True,
            subsystem="runtime",
        ),
        Step(
            "Editorial review",
            "Work stops here until a human approves. Nothing publishes itself.",
            subsystem="approvals",
        ),
        Step(
            "Repurpose for channels",
            "Split the approved article into posts sized per channel.",
            requires_provider=True,
            subsystem="runtime",
        ),
        Step(
            "Record lineage",
            "Link every post back to the paragraph and source it came from.",
            subsystem="graph",
        ),
    ),
    automations=(
        AutomationSpec(
            "Monday briefing",
            "Opens the week's content run every Monday so the queue is never empty.",
            trigger="schedule",
            schedule="Mondays at 09:00",
        ),
        AutomationSpec(
            "Stale draft reminder",
            "Flags any draft that has waited more than three days for review.",
            trigger="condition",
        ),
    ),
    graph=(
        GraphSeed("brief", "Content brief", "document", ("outline", "research")),
        GraphSeed("research", "Source set", "collection", ("outline",)),
        GraphSeed("outline", "Article outline", "document", ("draft",)),
        GraphSeed("draft", "Article draft", "document", ("posts",)),
        GraphSeed("posts", "Channel posts", "collection", ()),
    ),
    approval_scope="publish",
    estimated_minutes=3,
)


AUTOMATION_STUDIO = Demo(
    id="automation-studio",
    name="Automation Studio",
    tagline="The operations work that should never need a human.",
    description=(
        "Four rules that keep an Atlas installation healthy without anyone watching "
        "it: a nightly backup with an integrity check, automatic filing of anything "
        "new that arrives, escalation when the same job fails twice, and a weekly "
        "digest of what ran and what it cost.\n\n"
        "This demo needs no provider and no credentials. Every rule executes for "
        "real the moment it is installed, because automation in Atlas coordinates "
        "existing subsystems rather than calling models."
    ),
    category="automation",
    icon="⚙️",
    demonstrates=(
        "Triggers, conditions and actions as declarative data, not code",
        "Dry-run: see exactly what a rule would do before enabling it",
        "Automation that enqueues work and never touches a provider directly",
    ),
    steps=(
        Step(
            "Nightly backup",
            "Export at 02:00, verify the checksum, keep the last seven.",
            subsystem="backups",
        ),
        Step(
            "Integrity check",
            "Validate schema and referential integrity after each backup.",
            subsystem="diagnostics",
        ),
        Step(
            "File new assets",
            "Anything that arrives is tagged by type and filed against its project.",
            subsystem="assets",
        ),
        Step(
            "Escalate repeat failures",
            "A second failure of the same job raises it for a human instead of retrying forever.",
            subsystem="approvals",
        ),
        Step(
            "Weekly digest",
            "What ran, what failed, what it cost, and what is still waiting.",
            subsystem="automation",
        ),
    ),
    automations=(
        AutomationSpec(
            "Nightly backup and verify",
            "Exports every night at 02:00 and validates the archive before rotating old ones.",
            trigger="schedule",
            schedule="Daily at 02:00",
        ),
        AutomationSpec(
            "File new assets",
            "Tags and files each new asset the moment it is registered.",
            trigger="event",
        ),
        AutomationSpec(
            "Escalate repeat failures",
            "Raises an approval request when a job fails twice rather than retrying blindly.",
            trigger="condition",
        ),
        AutomationSpec(
            "Weekly operations digest",
            "Summarises runs, failures and queue depth every Friday afternoon.",
            trigger="schedule",
            schedule="Fridays at 17:00",
        ),
    ),
    graph=(
        GraphSeed("schedule", "Scheduled triggers", "trigger", ("backup", "digest")),
        GraphSeed("backup", "Backup archive", "artifact", ("integrity",)),
        GraphSeed("integrity", "Integrity report", "report", ()),
        GraphSeed("digest", "Operations digest", "report", ()),
    ),
    estimated_minutes=2,
)


RESEARCH_ASSISTANT = Demo(
    id="research-assistant",
    name="AI Research Assistant",
    tagline="A question becomes a sourced brief you can defend.",
    description=(
        "Research that keeps its receipts. Atlas breaks a question into "
        "sub-questions, gathers sources, records which source supports which claim, "
        "and flags where two sources disagree instead of quietly picking one.\n\n"
        "The output is a brief where every sentence can be traced back to where it "
        "came from — which is the difference between research you can act on and a "
        "confident paragraph you cannot check."
    ),
    category="research",
    icon="🔍",
    demonstrates=(
        "Claims linked to sources in the knowledge graph",
        "Contradictions surfaced rather than averaged away",
        "A session you can reopen months later and still audit",
    ),
    steps=(
        Step(
            "Frame the question",
            "State what you need to know and what a useful answer would look like.",
            subsystem="research",
        ),
        Step(
            "Decompose",
            "Break the question into sub-questions that can be answered separately.",
            requires_provider=True,
            subsystem="research",
        ),
        Step(
            "Gather sources",
            "Collect candidate sources and record where each one came from.",
            requires_provider=True,
            subsystem="research",
        ),
        Step(
            "Extract claims",
            "Pull out each claim and attach it to the source that made it.",
            requires_provider=True,
            subsystem="graph",
        ),
        Step(
            "Find contradictions",
            "Compare claims and surface the places sources disagree.",
            subsystem="graph",
        ),
        Step(
            "Synthesise",
            "Write the brief, citing the specific source behind each statement.",
            requires_provider=True,
            subsystem="runtime",
        ),
        Step(
            "Preserve the session",
            "Keep questions, sources and reasoning so the work can be audited later.",
            subsystem="research",
        ),
    ),
    automations=(
        AutomationSpec(
            "Watch for new sources",
            "Re-checks open research questions weekly and flags anything new.",
            trigger="schedule",
            schedule="Sundays at 08:00",
        ),
    ),
    graph=(
        GraphSeed("question", "Research question", "question", ("subquestions",)),
        GraphSeed("subquestions", "Sub-questions", "collection", ("sources",)),
        GraphSeed("sources", "Source set", "collection", ("claims",)),
        GraphSeed("claims", "Extracted claims", "collection", ("brief",)),
        GraphSeed("brief", "Research brief", "document", ()),
    ),
    estimated_minutes=3,
)


YOUTUBE_PIPELINE = Demo(
    id="youtube-pipeline",
    name="YouTube Content Pipeline",
    tagline="From an idea in the backlog to a scheduled upload.",
    description=(
        "The full path a video takes: an idea is pulled from the backlog, written "
        "as a script with a hook that earns the first thirty seconds, given three "
        "competing thumbnails, voiced, assembled, and held for approval before "
        "anything is scheduled.\n\n"
        "The approval gate is the part that matters. Publishing is irreversible — "
        "an audience sees it — so Atlas stops and waits for a person, every time, "
        "and records who approved what."
    ),
    category="video",
    icon="🎬",
    demonstrates=(
        "A human gate in front of every irreversible action",
        "Competing variants scored before one is chosen",
        "Scheduling that respects a publishing cadence",
    ),
    steps=(
        Step(
            "Pull from the backlog",
            "Take the next idea, ranked by how well the topic performed before.",
            subsystem="projects",
        ),
        Step(
            "Write the hook",
            "The first thirty seconds, written before anything else.",
            requires_provider=True,
            subsystem="runtime",
        ),
        Step(
            "Write the script",
            "Full script with beats, timings and B-roll notes.",
            requires_provider=True,
            subsystem="runtime",
        ),
        Step(
            "Generate thumbnails",
            "Three competing concepts rather than one guess.",
            requires_provider=True,
            subsystem="cluster",
        ),
        Step(
            "Record the voiceover",
            "Narration from the approved script.",
            requires_provider=True,
            subsystem="runtime",
        ),
        Step(
            "Assemble the cut",
            "Voiceover, B-roll and captions into a single timeline.",
            requires_provider=True,
            subsystem="workflow-engine",
        ),
        Step(
            "Publishing approval",
            "Nothing is scheduled until a person approves the cut and the thumbnail.",
            subsystem="approvals",
        ),
        Step(
            "Schedule the upload",
            "Queue it at the slot that fits the channel's cadence.",
            subsystem="scheduler",
        ),
    ),
    automations=(
        AutomationSpec(
            "Refill the backlog",
            "Keeps at least ten ideas ranked and ready.",
            trigger="condition",
        ),
        AutomationSpec(
            "Publishing cadence guard",
            "Refuses to schedule two uploads within the same 48 hours.",
            trigger="condition",
        ),
    ),
    graph=(
        GraphSeed("idea", "Video idea", "idea", ("script",)),
        GraphSeed("script", "Script", "document", ("voiceover", "thumbnails")),
        GraphSeed("thumbnails", "Thumbnail variants", "collection", ("cut",)),
        GraphSeed("voiceover", "Voiceover", "audio", ("cut",)),
        GraphSeed("cut", "Assembled cut", "video", ("upload",)),
        GraphSeed("upload", "Scheduled upload", "publication", ()),
    ),
    approval_scope="publish",
    estimated_minutes=4,
)


PRODUCTION_PIPELINE = Demo(
    id="production-pipeline",
    name="Image & Video Production Pipeline",
    tagline="A shot list becomes delivered masters, placed across your machines.",
    description=(
        "Production at volume. A brief becomes a shot list, every shot is generated "
        "as a batch, the strongest frames are selected, upscaled and colour-matched, "
        "then packaged for delivery.\n\n"
        "This is the demo that shows the cluster. Atlas decides where each job runs "
        "from what the job needs and what each machine can offer — you never pick a "
        "worker, and work waits for capacity rather than failing when a machine is "
        "busy."
    ),
    category="production",
    icon="🎨",
    demonstrates=(
        "Placement decided by the scheduler, never by the user",
        "Reservations and leases so work is created only when a slot exists",
        "Recovery that requeues work when a machine disappears mid-job",
    ),
    steps=(
        Step(
            "Read the brief",
            "Deliverables, aspect ratios, and the look the client signed off on.",
            subsystem="projects",
        ),
        Step(
            "Build the shot list",
            "Every frame that needs to exist, with its prompt and constraints.",
            requires_provider=True,
            subsystem="workflow-engine",
        ),
        Step(
            "Reserve capacity",
            "Claim worker slots before any job is created, so nothing starts it cannot finish.",
            subsystem="cluster",
        ),
        Step(
            "Generate the batch",
            "Every shot generated in parallel across whatever machines are online.",
            requires_provider=True,
            subsystem="cluster",
        ),
        Step(
            "Select the keepers",
            "Score the variants and keep the frames worth finishing.",
            requires_provider=True,
            subsystem="review",
        ),
        Step(
            "Upscale and colour-match",
            "Bring selected frames to delivery resolution and a consistent grade.",
            requires_provider=True,
            subsystem="runtime",
        ),
        Step(
            "Package for delivery",
            "Named, foldered and checksummed against the brief.",
            subsystem="assets",
        ),
    ),
    automations=(
        AutomationSpec(
            "Requeue orphaned work",
            "If a machine disappears mid-job the work is requeued, never silently lost.",
            trigger="event",
        ),
        AutomationSpec(
            "Delivery checklist",
            "Blocks delivery until every item in the brief has a matching master.",
            trigger="condition",
        ),
    ),
    graph=(
        GraphSeed("brief", "Production brief", "document", ("shotlist",)),
        GraphSeed("shotlist", "Shot list", "collection", ("batch",)),
        GraphSeed("batch", "Generated batch", "collection", ("selects",)),
        GraphSeed("selects", "Selected frames", "collection", ("masters",)),
        GraphSeed("masters", "Delivery masters", "collection", ()),
    ),
    estimated_minutes=4,
)


#: Ordered for the first-run picker. Automation Studio sits second because it is
#: the one that runs completely without credentials, and a new user should be
#: able to see something real happen within a minute of installing.
CATALOGUE: tuple[Demo, ...] = (
    CONTENT_STUDIO,
    AUTOMATION_STUDIO,
    RESEARCH_ASSISTANT,
    YOUTUBE_PIPELINE,
    PRODUCTION_PIPELINE,
)

BY_ID: dict[str, Demo] = {demo.id: demo for demo in CATALOGUE}


def catalogue() -> list[dict[str, Any]]:
    """Every demo, for the picker."""
    return [demo.summary() for demo in CATALOGUE]


def get(demo_id: str) -> Demo | None:
    return BY_ID.get(demo_id)


@dataclass
class InstallResult:
    """What installing a demo actually created."""

    demo_id: str
    project_id: str
    created: bool
    automations: list[str] = field(default_factory=list)
    graph_nodes: list[str] = field(default_factory=list)
    approval_policy: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "demo_id": self.demo_id,
            "project_id": self.project_id,
            "created": self.created,
            "automations": self.automations,
            "graph_nodes": self.graph_nodes,
            "approval_policy": self.approval_policy,
            "notes": self.notes,
        }
