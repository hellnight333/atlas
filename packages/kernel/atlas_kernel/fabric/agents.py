"""What an agent is, before any of them run.

The temptation with a fabric is to make an agent an object with methods that
does things. That is how you get three hundred processes and a swarm. Here an
agent is a **record**: an identity, a capability, a backend that could serve it,
the tools it may reach, and the approval its blast radius demands.

Nothing in this module executes, dispatches, or decides. It answers one question
— *which agents could be asked to do this* — and a test asserts it cannot do
more than that.

## Blast radius decides approval, not the other way round

The field that matters most is `blast`. An agent that reads a web page and an
agent that sends an email are the same shape and completely different risks, and
the difference is not how clever the model is — it is whether the effect can be
undone.

    REVERSIBLE     a branch, a draft, a fetch          execution approval
    COSTLY         spends money, produces nothing bad   budget
    IRREVERSIBLE   an email, a post, an order, a       artefact approval over
                   deletion                             the exact payload

`IRREVERSIBLE` requires approval of the payload rather than of the capability.
Not "may the CRM agent send email" — *may this message go to this person.* That
is the boundary `publication` already enforces for artefacts, generalised.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..credentials.models import Role


class UnknownAgent(Exception):
    """No agent by that id, or none capable of that work."""


class Capability(StrEnum):
    """What an agent can be asked to do.

    Deliberately about *work*, not about tools. "Research a business" is a
    capability; "call the Brave API" is a tool the capability might use. Naming
    capabilities after tools is how a registry becomes a list of integrations
    that nobody can route work through.
    """

    PLAN = "plan"
    IMPLEMENT = "implement"
    REVIEW = "review"
    RESEARCH = "research"
    SUMMARISE = "summarise"
    ANALYSE = "analyse"
    WRITE = "write"
    TRANSLATE_CHECK = "translate_check"
    # Everything below is designed and has no backend yet. Recorded so the gap
    # is visible in the registry rather than being an absence nobody can see.
    BROWSE = "browse"
    ADMINISTER = "administer"
    CORRESPOND = "correspond"
    MERCHANDISE = "merchandise"
    PUBLISH_SOCIAL = "publish_social"
    GENERATE_IMAGE = "generate_image"
    GENERATE_VIDEO = "generate_video"


class Backend(StrEnum):
    """How an agent actually runs.

    Two shapes, and conflating them is how a registry rots: an API model returns
    text, a CLI agent has its own tool loop and writes files. The second is a
    sandboxing question rather than a provider question.
    """

    API_MODEL = "api_model"
    CLI_AGENT = "cli_agent"
    #: Deterministic code. Most of Qevik's existing capabilities are this, and
    #: recording them here keeps one registry rather than "agents" beside
    #: "executors" with no relationship.
    EXECUTOR = "executor"


class Placement(StrEnum):
    """Where the work has to happen. A requirement, never a preference."""

    EITHER = "either"
    #: Needs a filesystem, a GPU, or a CLI logged in as the operator.
    LOCAL = "local"
    #: Must survive the operator's machine sleeping.
    CLOUD = "cloud"


class Blast(StrEnum):
    """How far a mistake reaches. This decides which approval applies."""

    REVERSIBLE = "reversible"
    COSTLY = "costly"
    IRREVERSIBLE = "irreversible"


#: Which approval a blast radius demands. A table rather than a conditional, so
#: adding a radius without deciding its approval is a failure rather than a
#: default.
APPROVAL_FOR: dict[Blast, str] = {
    Blast.REVERSIBLE: "execution",
    Blast.COSTLY: "budget",
    Blast.IRREVERSIBLE: "artefact",
}


class Agent(BaseModel):
    """One agent, as a record. Nothing here runs."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    capability: Capability
    backend: Backend
    #: Which model role this maps onto, for API and CLI backends. `None` for an
    #: executor, which is deterministic code and chooses no model.
    role: Role | None = None
    #: The offer this agent fulfils, for executor-backed agents. Keeps the
    #: fabric and `EXECUTORS` describing one thing rather than two.
    offer_id: str = ""
    blast: Blast = Blast.REVERSIBLE
    placement: Placement = Placement.EITHER
    #: Tools it may reach. Named, not inferred: an agent that can reach a tool
    #: nobody wrote down is an agent whose blast radius is unknown.
    tools: tuple[str, ...] = ()
    #: Credentials required before it can run at all. The same ids the
    #: Credential Centre uses, so "what does this key unlock" is answerable.
    credentials: tuple[str, ...] = ()
    #: False while the backend is designed and unbuilt. An agent that cannot run
    #: is listed rather than absent, because an absence is invisible.
    ready: bool = True
    why_not_ready: str = ""
    notes: str = ""

    @property
    def approval(self) -> str:
        return APPROVAL_FOR[self.blast]

    @property
    def needs_sandbox(self) -> bool:
        """A CLI agent writes files. That is a container, not a permission."""
        return self.backend is Backend.CLI_AGENT

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name,
                "capability": self.capability.value,
                "backend": self.backend.value,
                "role": self.role.value if self.role else "",
                "offer_id": self.offer_id, "blast": self.blast.value,
                "approval": self.approval, "placement": self.placement.value,
                "tools": list(self.tools), "credentials": list(self.credentials),
                "ready": self.ready, "why_not_ready": self.why_not_ready,
                "needs_sandbox": self.needs_sandbox, "notes": self.notes}


#: The agents Qevik has, and the ones it has designed and cannot yet run.
#:
#: Everything with `ready=True` is backed by something that exists today —
#: mostly `EXECUTORS`, which is the point: the fabric describes what is already
#: there before it describes anything new. The unready records exist so the gap
#: between "designed" and "runnable" is visible in the same list rather than
#: being an absence.
AGENTS: tuple[Agent, ...] = (
    # -- the mission trio, backed by ModelRegistry --------------------------
    Agent(id="planner", name="Planner", capability=Capability.PLAN,
          backend=Backend.API_MODEL, role=Role.PLANNING,
          credentials=("qwen", "anthropic", "openai"),
          notes="Proposes. Authorises nothing — policy sits above it."),
    Agent(id="implementer", name="Implementer", capability=Capability.IMPLEMENT,
          backend=Backend.API_MODEL, role=Role.IMPLEMENTATION,
          tools=("git-worktree",), credentials=("qwen", "anthropic", "openai"),
          notes="Writes in an isolated worktree. Never on a protected branch."),
    Agent(id="reviewer", name="Reviewer", capability=Capability.REVIEW,
          backend=Backend.API_MODEL, role=Role.REVIEW,
          credentials=("qwen", "anthropic", "openai"),
          notes="Independent of the implementer where the registry allows."),
    Agent(id="summariser", name="Summariser", capability=Capability.SUMMARISE,
          backend=Backend.API_MODEL, role=Role.SUMMARISATION,
          credentials=("qwen", "anthropic", "openai")),

    # -- deterministic capabilities that already ship ----------------------
    Agent(id="website-builder", name="Website builder",
          capability=Capability.IMPLEMENT, backend=Backend.EXECUTOR,
          offer_id="offer-website", tools=("website-generator",),
          notes="Evidence in, multi-page bundle out. Invents nothing."),
    Agent(id="portfolio-builder", name="Portfolio builder",
          capability=Capability.IMPLEMENT, backend=Backend.EXECUTOR,
          offer_id="offer-portfolio-system", tools=("website-generator",)),
    Agent(id="editorial-builder", name="Editorial builder",
          capability=Capability.WRITE, backend=Backend.EXECUTOR,
          offer_id="offer-editorial", tools=("website-generator",)),
    Agent(id="arabic-builder", name="Arabic experience",
          capability=Capability.TRANSLATE_CHECK, backend=Backend.EXECUTOR,
          offer_id="offer-arabic-experience", tools=("website-generator",),
          notes="Checks supplied Arabic. Never translates — a machine "
                "translation is a claim about the business in a language the "
                "approver usually cannot read."),
    Agent(id="enquiry-builder", name="Enquiry builder",
          capability=Capability.IMPLEMENT, backend=Backend.EXECUTOR,
          offer_id="offer-enquiry-builder", tools=("website-generator",)),
    Agent(id="imagery-planner", name="Imagery planner",
          capability=Capability.ANALYSE, backend=Backend.EXECUTOR,
          offer_id="offer-imagery", tools=("website-generator",),
          notes="Plans imagery. Documentary slots take only supplied "
                "photographs."),
    Agent(id="researcher", name="Researcher", capability=Capability.RESEARCH,
          backend=Backend.EXECUTOR, tools=("http-fetch", "dns"),
          notes="Crawls with the SSRF guard: every resolved address, every "
                "redirect hop."),

    # -- designed, not yet runnable ----------------------------------------
    Agent(id="cli-implementer", name="CLI coding agent",
          capability=Capability.IMPLEMENT, backend=Backend.CLI_AGENT,
          role=Role.IMPLEMENTATION, placement=Placement.LOCAL,
          tools=("shell", "filesystem", "git-worktree"),
          credentials=("anthropic",), ready=False,
          why_not_ready="A CLI agent writes files with its own tool loop. "
                        "Qevik's isolation is a process and a worktree, which "
                        "is right for an API agent and insufficient for this. "
                        "PENDING_INFRASTRUCTURE: a container boundary.",
          notes="Its permission prompts must become HumanActions, never "
                "auto-answered."),
    Agent(id="browser", name="Browser agent", capability=Capability.BROWSE,
          backend=Backend.CLI_AGENT, placement=Placement.CLOUD,
          tools=("browser",), ready=False,
          why_not_ready="PENDING_INFRASTRUCTURE: a browser worker."),
    Agent(id="correspondent", name="Correspondent",
          capability=Capability.CORRESPOND, backend=Backend.EXECUTOR,
          blast=Blast.IRREVERSIBLE, tools=("smtp",), credentials=("smtp",),
          ready=False,
          why_not_ready="PENDING_CREDENTIAL: SMTP. An email cannot be unsent, "
                        "so it needs artefact approval over the exact message.",
          notes="Prepares drafts. Sending is a separate, approved act."),
    Agent(id="merchandiser", name="Marketplace agent",
          capability=Capability.MERCHANDISE, backend=Backend.EXECUTOR,
          blast=Blast.IRREVERSIBLE, tools=("amazon", "noon"),
          credentials=("amazon", "noon"), ready=False,
          why_not_ready="PENDING_CREDENTIAL. A marketplace token creates "
                        "orders."),
    Agent(id="social", name="Social agent", capability=Capability.PUBLISH_SOCIAL,
          backend=Backend.EXECUTOR, blast=Blast.IRREVERSIBLE,
          tools=("youtube", "instagram"), credentials=("youtube", "instagram"),
          ready=False,
          why_not_ready="PENDING_CREDENTIAL. A post cannot be recalled."),
    Agent(id="image-maker", name="Image generator",
          capability=Capability.GENERATE_IMAGE, backend=Backend.API_MODEL,
          role=Role.IMAGE, blast=Blast.COSTLY, tools=("media-provider",),
          ready=False,
          why_not_ready="PENDING_CREDENTIAL: a generation provider."),
    Agent(id="administrator", name="Server administrator",
          capability=Capability.ADMINISTER, backend=Backend.CLI_AGENT,
          blast=Blast.IRREVERSIBLE, placement=Placement.CLOUD,
          tools=("shell",), ready=False,
          why_not_ready="PENDING_INFRASTRUCTURE: a sandbox, and a per-action "
                        "approval policy. A shell on a host is not reversible.",
          notes="The highest blast radius in the fabric."),
)


class Registry(BaseModel):
    """The agents this deployment has. Reads only.

    A class rather than module functions so a deployment can hold a different
    set — a tenant with no marketplace agents, a developer machine with only the
    executor-backed ones — without any of them being global state.
    """

    model_config = ConfigDict(frozen=True)

    agents: tuple[Agent, ...] = Field(default=AGENTS)

    def get(self, agent_id: str) -> Agent:
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        raise UnknownAgent(f"no agent {agent_id!r}")

    def capable_of(self, capability: Capability, *, ready_only: bool = True
                   ) -> tuple[Agent, ...]:
        """Which agents could be asked to do this.

        `ready_only` defaults to True: dispatching to an agent whose backend
        does not exist produces a failure at execution, after a customer has
        been told the work would happen.
        """
        return tuple(a for a in self.agents
                     if a.capability is capability and (a.ready or not ready_only))

    def needing(self, credential: str) -> tuple[Agent, ...]:
        """Which agents a credential unlocks.

        The answer to "what does this key buy me", which is the same question as
        "what breaks without it" — and the Credential Centre should be able to
        say both.
        """
        return tuple(a for a in self.agents if credential in a.credentials)

    def summary(self) -> dict:
        ready = [a for a in self.agents if a.ready]
        return {
            "agents": [a.summary() for a in self.agents],
            "counts": {
                "total": len(self.agents),
                "ready": len(ready),
                "blocked": len(self.agents) - len(ready),
                "irreversible": sum(1 for a in self.agents
                                    if a.blast is Blast.IRREVERSIBLE),
                "needing_sandbox": sum(1 for a in self.agents if a.needs_sandbox),
            },
            "capabilities": sorted({a.capability.value for a in ready}),
            "note": ("An agent record is not a running process. Processes are "
                     "instantiated on demand by the scheduler; nothing here "
                     "dispatches, and no agent may recruit another."),
        }


def capable_of(capability: Capability, *, ready_only: bool = True
               ) -> tuple[Agent, ...]:
    """Convenience over the default registry."""
    return Registry().capable_of(capability, ready_only=ready_only)


def describe(agent_id: str) -> dict:
    return Registry().get(agent_id).summary()
