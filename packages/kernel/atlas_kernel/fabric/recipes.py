"""Declared, named sequences of tool steps. The unit of work an assistant does.

`CLAUDE.md` is unambiguous about why this is a primitive rather than a
convenience: an LLM must **never** freestyle the steps, because it will
hallucinate them forever. A recipe is a versioned, declarative artifact in git,
and the model's only job is choosing one **by name**.

That is the same shape as `mission/origins.py`, and for the same reason. A model
emits a string; code decides what that string is allowed to mean. A name that
resolves to nothing is a refusal, never a default.

## Why this exists now

`SELF_CHECK_STEPS` was a module-level list in `mission/adapter.py` — the only
sequence of tool steps in the system, hardcoded beside the thing that runs it.
Every future assistant (research, discovery, email, media, publishing) needs the
same structure: a named sequence, a declared agent, tools that agent actually
has, and evidence at the end. Copying the list per domain would produce a dozen
hardcoded lists with a dozen different ideas about what evidence means.

## What a recipe is not

It is **not** a plan and it does not replace one. A plan is what a person
approves; a recipe is how the approved work is carried out. A recipe cannot
authorise itself, cannot pick its own agent at runtime, and cannot reach a tool
its agent does not declare — that last one is checked here, at import, so a
recipe that would be refused at dispatch fails the build instead.

## What a recipe is not, part two

It is not a workflow engine. There are no conditionals, no loops, no jumps and
no variables beyond the workspace the steps run in. A sequence that needs those
is a program, and a program that a model assembles at runtime is the thing this
module exists to prevent. If a domain genuinely needs branching, it gets two
recipes and something deterministic chooses between them.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, field_validator

from .agents import Capability, Registry, UnknownAgent
from .tools import for_agent
from .tools import get as tool_for


class UnknownRecipe(Exception):
    """A name nobody declared. Never a fallback to another recipe."""


class RecipeRefused(Exception):
    """A recipe could not be declared. Raised at import, never at dispatch."""


class Step(BaseModel):
    """One tool invocation inside a recipe.

    Mirrors `mission.adapter.Step` deliberately rather than importing it: that
    one is a dataclass owned by the execution layer, and a recipe is a
    declaration that must be readable and validated without the sandbox, the
    workspace or anything else the runner needs. `for_adapter()` converts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The tool this step uses. Must be one the recipe's agent declares.
    tool: str
    #: What the tool is invoked with. Argv for `shell` and `filesystem`; a URL
    #: for `http-fetch`; a hostname for `dns`. Never a shell string — a shell
    #: string is a place to hide a second command, and the whole point of naming
    #: the tool is that the step is inspectable before it runs.
    command: tuple[str, ...]
    #: What this establishes. A step whose output nobody can interpret produces
    #: noise in the evidence, and evidence nobody reads is the same as none.
    proves: str

    @field_validator("command")
    @classmethod
    def _has_a_command(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("a step needs a command")
        return value

    @field_validator("proves")
    @classmethod
    def _says_what_it_proves(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "a step must say what it establishes, or its output is noise")
        return value


class Recipe(BaseModel):
    """A named way of doing one thing, and who does it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    #: Bumped when the steps change in a way that alters what the recipe does.
    #: A recipe whose behaviour changed under a name somebody already approved
    #: is a different recipe wearing its clothes.
    version: int = 1
    #: What this is for, in the words somebody reviewing an approval would use.
    does: str
    #: The registry id of the agent that carries it out. Not chosen at runtime:
    #: the agent decides the blast radius, and a runtime choice is a runtime
    #: blast radius.
    agent_id: str
    capability: Capability
    steps: tuple[Step, ...]
    notes: str = ""

    @field_validator("steps")
    @classmethod
    def _has_steps(cls, value: tuple[Step, ...]) -> tuple[Step, ...]:
        if not value:
            raise ValueError("a recipe with no steps does nothing")
        return value

    @field_validator("id")
    @classmethod
    def _is_a_key(cls, value: str) -> str:
        name = value.strip()
        if not name or name != value:
            raise ValueError("a recipe id must be a bare key")
        if any(c in name for c in "/\\. :"):
            raise ValueError(
                f"{name!r} looks like a path. Recipe ids are keys, and a key "
                "that can express a location defeats the point of having them")
        return name

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(sorted({step.tool for step in self.steps}))

    #: Tools whose steps are argv and may be executed as commands. Anything
    #: else is invoked by something that understands it — `http-fetch` by the
    #: guarded fetcher, for instance — and must never reach a process launcher.
    EXECUTABLE_TOOLS: ClassVar[frozenset[str]] = frozenset(
        {"shell", "filesystem", "git-worktree"})

    def for_adapter(self) -> list:
        """The steps as the command-running execution layer wants them.

        Refuses a recipe containing a step that is not argv. `http-fetch`
        steps carry a **URL**, and handing one to a process launcher would try
        to execute `https://example.com/` as a program — which fails, but only
        after the recipe has been dispatched, and for a reason that reads like
        a missing binary rather than a category error.
        """
        wrong = sorted({s.tool for s in self.steps
                        if s.tool not in self.EXECUTABLE_TOOLS})
        if wrong:
            raise RecipeRefused(
                f"{self.id} contains {', '.join(wrong)} step(s), which are not "
                "commands. A URL is not a program; these are carried out by the "
                "tool that understands them, not by a process launcher.")
        from ..mission.adapter import Step as RunStep
        return [RunStep(command=list(s.command), proves=s.proves, tool=s.tool)
                for s in self.steps]

    def summary(self) -> dict:
        return {"id": self.id, "version": self.version, "does": self.does,
                "agent_id": self.agent_id, "capability": self.capability.value,
                "tools": list(self.tools), "steps": len(self.steps),
                "notes": self.notes}


def validate(recipe: Recipe, *, registry: Registry | None = None) -> None:
    """Refuse a recipe its agent could not actually run.

    At **import**, not at dispatch. A recipe whose steps reach a tool its agent
    does not declare would be refused by `Adapter.run` — correctly, but at three
    in the morning, in front of nobody, as a blocked mission. Here it is a
    failing build in front of whoever wrote it.
    """
    try:
        agent = (registry or Registry()).get(recipe.agent_id)
    except UnknownAgent as unknown:
        raise RecipeRefused(
            f"{recipe.id} names agent {recipe.agent_id!r}, which no registry "
            "entry declares. An agent nobody declared has no bounded blast "
            "radius, so nothing may be routed to it.") from unknown

    declared = {tool.id for tool in for_agent(agent)}
    undeclared = sorted(set(recipe.tools) - declared)
    if undeclared:
        raise RecipeRefused(
            f"{recipe.id} uses {', '.join(undeclared)} and {agent.id} declares "
            f"{', '.join(sorted(declared)) or 'no tools'}. Either the agent's "
            "entry is wrong or the recipe is; both are decisions somebody makes "
            "on purpose, not at runtime.")

    for step in recipe.steps:
        try:
            tool_for(step.tool)
        except KeyError as missing:
            raise RecipeRefused(
                f"{recipe.id} uses tool {step.tool!r}, which is not declared in "
                "`fabric.tools`.") from missing

    if agent.capability is not recipe.capability:
        raise RecipeRefused(
            f"{recipe.id} claims capability {recipe.capability.value!r} and "
            f"{agent.id} provides {agent.capability.value!r}. A recipe filed "
            "under a capability its agent does not have is one the scheduler "
            "would route work to and the agent could not perform.")


# ============================================================ the declarations
#
# In code, beside `AGENTS`, `TOOLS`, `EXECUTORS` and `RECURRENCES`, for the
# reason those are: a recipe decides what an agent actually does, and a
# declaration that decides behaviour must not be editable at runtime.

RECIPES: tuple[Recipe, ...] = (
    Recipe(
        id="execution-canary",
        does=("Prove the whole execution path still works: a writable "
              "workspace, a readable result, and a sandbox that is still "
              "confining rather than merely present."),
        agent_id="self-check",
        capability=Capability.VERIFY,
        steps=(
            Step(tool="filesystem",
                 command=("sh", "-c", "printf 'checked by qevik\n' > qevik-self-check.txt"),
                 proves="the workspace is writable"),
            Step(tool="filesystem",
                 command=("sh", "-c", "test -s qevik-self-check.txt"),
                 proves="what was written can be read back"),
            Step(tool="shell",
                 command=("sh", "-c",
                          "cat /etc/shadow > stolen.txt 2>/dev/null && exit 1 || exit 0"),
                 proves="nothing outside the workspace is reachable"),
        ),
        notes=("The third step is the one that matters. The first two would "
               "pass on a host with no sandbox at all."),
    ),    Recipe(
        id="discover-uae-dental",
        does=("Look at the homepages of known dental clinics in the UAE and "
              "record what the servers actually said. Produces evidence; "
              "concludes nothing."),
        agent_id="researcher",
        capability=Capability.RESEARCH,
        steps=(
            Step(tool="http-fetch",
                 command=("https://www.dha.gov.ae/",),
                 proves="the regulator's directory is reachable, and what it "
                        "returned"),
            Step(tool="dns",
                 command=("dha.gov.ae",),
                 proves="whether the host resolves at all, which is a "
                        "different fact from the site being down"),
        ),
        notes=("A market is part of the declaration, not a parameter. Recipes "
               "have no variables on purpose, so scanning a second market is a "
               "second recipe — a reviewed change in git rather than a string "
               "somebody passed at three in the morning. The two steps here are "
               "deliberately modest: this recipe exists to carry the shape "
               "end to end, and widening the crawl is a decision with a cost "
               "attached."),
    ),
)


def all_recipes() -> tuple[Recipe, ...]:
    return RECIPES


def get(recipe_id: str) -> Recipe:
    """A recipe by name, or a refusal. Never a fallback to another."""
    for recipe in RECIPES:
        if recipe.id == recipe_id:
            return recipe
    raise UnknownRecipe(
        f"no recipe named {recipe_id!r}. Known: "
        f"{', '.join(sorted(r.id for r in RECIPES))}. A recipe is declared in "
        "code; nothing chooses one at runtime that nobody wrote.")


def for_capability(capability: Capability) -> tuple[Recipe, ...]:
    """Every recipe that provides a capability, for a chooser to pick from."""
    return tuple(r for r in RECIPES if r.capability is capability)


def describe() -> list[dict]:
    return [r.summary() for r in RECIPES]


def _validate_all() -> None:
    """Every declared recipe, at import.

    The same discipline `origins.Registry.build` uses: a bad declaration fails
    where somebody can see it, rather than becoming a blocked mission later.
    """
    seen: set[str] = set()
    for recipe in RECIPES:
        if recipe.id in seen:
            raise RecipeRefused(
                f"{recipe.id!r} is declared twice. A tuple keeps both and `get`"
                " returns whichever comes first, so the other is invisible.")
        seen.add(recipe.id)
        validate(recipe)


_validate_all()


__all__ = ["RECIPES", "Recipe", "RecipeRefused", "Step", "UnknownRecipe",
           "all_recipes", "describe", "for_capability", "get", "validate"]
