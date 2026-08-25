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
"""

from .agents import (
    AGENTS,
    Agent,
    Backend,
    Blast,
    Capability,
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
from .scheduler import (
    Decision,
    Demand,
    Priority,
    Queue,
    decide,
    demands_from,
    plan,
)

__all__ = ["AGENTS", "Agent", "Assessment", "Backend", "Blast", "Capability",
           "Conversation", "Decision", "Demand", "Envelope", "Exchange", "Kind",
           "Limits", "Message", "Placement", "Priority", "Queue", "Refused",
           "Registry", "Scope", "Unmetered", "UnknownAgent", "assess",
           "capable_of", "decide", "demands_from", "describe", "plan",
           "reserve"]
