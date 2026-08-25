"""The agent fabric: many agents, few processes, no authority.

An agent here is a **declarative record**, not a running thing. Three hundred
records cost nothing while idle; three hundred processes are impossible. A
process is instantiated when the scheduler dispatches work to a capability and
released afterwards.

Three rules make a fabric rather than a swarm, and each is enforced rather than
documented:

**Agents cannot recruit agents.** Only the scheduler dispatches. An agent able to
spawn agents is an unbounded resource commitment made by a language model.

**Capability is not authority.** An agent record says what an agent *can be
asked to do*. Whether it may is decided by policy — `EXECUTORS`,
`REQUIRES_CUSTOMER_INPUT`, the approval boundaries, `owns()` — none of which
lives here.

**One registry.** `ModelRegistry` remains the only answer to "what can run";
this maps capabilities onto it. A second registry is how an invocation gets
recorded against a model that never saw the request.

The package, in the order it was built:

    agents      who could be asked, and what stands in their way
    tools       what they may reach, and what it costs to be wrong with it
    scheduler   what runs next, and why everything else does not
    protocol    how they ask each other, and why it cannot run away
    budgets     what any of it may spend, at four scopes
    sandbox     where a coding agent is allowed to exist

Each answers one question and refuses the others. The scheduler does not decide
*whether*; the protocol does not execute; the registry decides nothing about
permission; the sandbox never pretends to contain what it cannot.
"""

from .agents import (
    AGENTS,
    Agent,
    Backend,
    Blast,
    Capability,
    Need,
    Placement,
    Registry,
    UnknownAgent,
    capable_of,
    describe,
)
from .budgets import (
    Assessment,
    Envelope,
    Scope,
    Unmetered,
    assess,
    reserve,
)
from .protocol import (
    Conversation,
    Exchange,
    Kind,
    Limits,
    Message,
    Refused,
)
from .sandbox import (
    Bubblewrap,
    Confinement,
    Isolation,
    NoSandbox,
    NotIsolated,
    Outcome,
)
from .scheduler import (
    Decision,
    Demand,
    Priority,
    Queue,
    decide,
    demands_from,
    plan,
)
from .tools import (
    TOOLS,
    Tool,
    UnknownTool,
    for_agent,
    needs_network,
)

__all__ = ["AGENTS", "Agent", "Assessment", "Backend", "Blast", "Bubblewrap",
           "Capability", "Confinement", "Conversation", "Decision", "Demand",
           "Envelope", "Exchange", "Isolation", "Kind", "Limits", "Message",
           "NoSandbox", "NotIsolated", "Need", "Outcome", "Placement",
           "Priority", "Queue", "Refused", "Registry", "Scope", "Unmetered",
           "TOOLS", "Tool", "UnknownAgent", "UnknownTool", "assess",
           "capable_of", "decide", "demands_from",
           "describe", "for_agent", "needs_network", "plan", "reserve"]
