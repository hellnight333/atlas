"""What an agent may reach, and how much damage it can do with it.

`Agent.tools` was a tuple of free-form strings. Nothing checked that a named
tool existed, nothing said what it could do, and nothing connected it to the
isolation the agent would run under. That is the shape of drift this project has
been bitten by before: two lists kept in step by hand until the day they are not.

So a tool is a record, agents reference it by id, and a test fails the build on
a dangling name.

## Blast radius belongs to the tool, not to the agent

An agent's declared `blast` must be **at least** the worst its tools can do.
`at least` rather than `equal to`, so an agent may be more cautious than its
tools — a merchandiser that only ever drafts is welcome to say IRREVERSIBLE —
but it can never understate them.

Writing the tools down this way found two real errors in the registry, both
recorded in `TOOLS` below:

**`shell` meant two different things.** `cli-implementer` ran a shell in a
sandboxed worktree and called it reversible; `administrator` ran a shell on a
live host and called it irreversible. Both were right about their own case and
the *tool* was the same string. A shell whose writes `git checkout` undoes and a
shell on a production machine are different tools, so they are now `shell` and
`host-shell`.

**`browser` understated itself.** The browser agent declared REVERSIBLE while a
browser that can navigate can also submit a form, buy something, or send a
message. Nothing about "browse" is reversible once a button is clicked.

## The network flag is not documentation

`Tool.network` feeds `sandbox.Isolation(network=…)`. An agent whose tools are
all local runs with the network unshared, and that is enforced by the kernel
rather than by an instruction in a prompt.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .agents import Agent, Blast

#: Worst-first, so "at least as bad as" is a comparison rather than a table.
SEVERITY: dict[Blast, int] = {Blast.REVERSIBLE: 0, Blast.COSTLY: 1,
                              Blast.IRREVERSIBLE: 2}


class UnknownTool(KeyError):
    """An agent named a tool nobody wrote.

    An agent that can reach a tool nobody wrote down is an agent whose blast
    radius is unknown — which is the one thing the approval boundaries cannot
    work around.
    """


class Tool(BaseModel):
    """One thing an agent can reach, and what it costs to be wrong with it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    #: What it does, in the words a person reviewing an approval would use.
    does: str
    #: The worst it can do. See the module note: this belongs to the tool.
    blast: Blast = Blast.REVERSIBLE
    #: Whether the process needs to reach the network to use it. Feeds
    #: `sandbox.Isolation`, so it is enforced rather than described.
    network: bool = False
    #: Credential ids, as the Credential Centre names them.
    credentials: tuple[str, ...] = ()
    #: True when a sandbox genuinely reduces the damage. A shell writing to a
    #: worktree is contained; an email leaving the machine is not, and calling
    #: it contained because the process was in a namespace would be the most
    #: dangerous kind of wrong.
    contained_by_sandbox: bool = False
    notes: str = ""

    def summary(self) -> dict:
        return {"id": self.id, "does": self.does, "blast": self.blast.value,
                "network": self.network, "credentials": list(self.credentials),
                "contained_by_sandbox": self.contained_by_sandbox,
                "notes": self.notes}


TOOLS: tuple[Tool, ...] = (
    # -- local, and undone by version control ------------------------------
    Tool(id="git-worktree", does="Read and write files in an isolated checkout",
         contained_by_sandbox=True,
         notes="Reversible because the checkout is discardable, not because "
               "writing files is harmless."),
    Tool(id="filesystem", does="Read and write files in the workspace",
         contained_by_sandbox=True),
    Tool(id="shell", does="Run commands inside the sandboxed workspace",
         contained_by_sandbox=True,
         notes="Split from `host-shell`. The same word covered a shell whose "
               "writes `git checkout` undoes and a shell on a live machine; "
               "one string cannot carry both blast radii."),
    Tool(id="website-generator",
         does="Turn evidence into a website bundle, on disk",
         contained_by_sandbox=True,
         notes="Produces a bundle. Publishing it is a separate, approved act "
               "with its own artefact approval over the published bytes."),

    # -- reads the world ---------------------------------------------------
    Tool(id="http-fetch", does="Fetch a page", network=True,
         notes="Behind the SSRF guard: every resolved address, every redirect "
               "hop."),
    Tool(id="dns", does="Resolve a name", network=True),

    # -- costs money -------------------------------------------------------
    Tool(id="media-provider", does="Generate an image or a video",
         blast=Blast.COSTLY, network=True,
         notes="Costly rather than irreversible: a wasted generation is money, "
               "not a public act. Publishing the result is."),

    # -- leaves the machine, and cannot be recalled -------------------------
    Tool(id="smtp", does="Send an email", blast=Blast.IRREVERSIBLE,
         network=True, credentials=("smtp",),
         notes="An email cannot be unsent. A sandbox does not contain this: "
               "the effect is already elsewhere."),
    Tool(id="amazon", does="Create or change an Amazon listing",
         blast=Blast.IRREVERSIBLE, network=True, credentials=("amazon",)),
    Tool(id="noon", does="Create or change a noon listing",
         blast=Blast.IRREVERSIBLE, network=True, credentials=("noon",)),
    Tool(id="youtube", does="Publish to YouTube", blast=Blast.IRREVERSIBLE,
         network=True, credentials=("youtube",),
         notes="A post cannot be recalled once anybody has seen it."),
    Tool(id="instagram", does="Publish to Instagram", blast=Blast.IRREVERSIBLE,
         network=True, credentials=("instagram",)),
    Tool(id="browser", does="Drive a real browser", blast=Blast.IRREVERSIBLE,
         network=True,
         notes="Corrected. A browser that can navigate can also submit a form, "
               "buy something or send a message — nothing about 'browse' is "
               "reversible once a button is clicked."),
    Tool(id="host-shell", does="Run commands on a live machine",
         blast=Blast.IRREVERSIBLE, network=True,
         notes="The highest blast radius in the fabric. A sandbox contains the "
               "process; it does not make what the process did to the host "
               "reversible."),
)

BY_ID: dict[str, Tool] = {tool.id: tool for tool in TOOLS}


def get(tool_id: str) -> Tool:
    try:
        return BY_ID[tool_id]
    except KeyError:
        raise UnknownTool(
            f"no tool {tool_id!r}. An agent that can reach a tool nobody wrote "
            "down is an agent whose blast radius is unknown.") from None


def for_agent(agent: Agent) -> tuple[Tool, ...]:
    """Every tool this agent may reach. Raises on a name nobody wrote."""
    return tuple(get(name) for name in agent.tools)


def worst(tools: tuple[Tool, ...]) -> Blast:
    """The worst any of them can do. Reversible when there are none."""
    return max((t.blast for t in tools), key=lambda b: SEVERITY[b],
               default=Blast.REVERSIBLE)


def understates(agent: Agent) -> bool:
    """Whether an agent's declared blast is milder than its tools allow.

    A test fails the build on this. An agent that says REVERSIBLE while holding
    a tool that sends email would be routed to execution approval instead of
    artefact approval — the wrong boundary, chosen by a typo.
    """
    return SEVERITY[agent.blast] < SEVERITY[worst(for_agent(agent))]


def needs_network(agent: Agent) -> bool:
    """Whether any of its tools has to reach the network.

    Feeds `sandbox.Isolation(network=…)`, so an agent whose work is entirely
    local runs with the network unshared — enforced by the kernel rather than
    requested in a prompt.
    """
    return any(tool.network for tool in for_agent(agent))


def unmet(agent: Agent) -> tuple[str, ...]:
    """Credentials the agent's tools need that the agent does not declare.

    The two lists are kept honest against each other rather than by hand. An
    agent holding a tool whose key it never lists is an agent that fails at the
    provider, after the customer was told the work was happening.
    """
    needed = {c for tool in for_agent(agent) for c in tool.credentials}
    return tuple(sorted(needed - set(agent.credentials)))


def describe() -> dict:
    """The tool table, for a report or a review."""
    return {
        "tools": [t.summary() for t in TOOLS],
        "irreversible": [t.id for t in TOOLS if t.blast is Blast.IRREVERSIBLE],
        "note": ("Blast radius belongs to the tool. An agent may be more "
                 "cautious than its tools and never less — a test fails the "
                 "build on an agent that understates them."),
    }
