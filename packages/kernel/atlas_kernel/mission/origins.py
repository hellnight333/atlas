"""Which repository a mission is allowed to touch, decided before it runs.

## The hole this closes

The scratch clone stopped a mission writing into the production checkout, but
*which* repository a mission worked on was still a **worker flag**:
`--repository /opt/qevik/atlas`, one value for the whole process. So every
mission on that worker was a Qevik mission, the CUSTOMER case could not be
exercised at all, and one worker could not serve both self-improvement and
unattended work.

Moving the choice onto the mission raises the obvious danger: if a mission can
name a repository, and a model can write the mission, then a model can name a
repository. That is a path traversal with extra steps.

## So a mission names a *key*, never a path

    mission.origin_name = "acme-web"        <- a key. Meaningless on its own.
    registry.resolve("acme-web")            <- code decides what that is, if anything

The registry is the only thing that turns a name into a location, and it is
built at start-up from code plus deployment configuration. A planner emitting
`"../../etc"`, `"/opt/qevik/atlas"` or `"qevik "` gets `UnknownOrigin` and the
mission is blocked. There is no path in the mission at all, so there is nothing
to traverse and no fallback to guess at.

**A name that is not registered is never a fallback to the default.** Falling
back would make a typo silently run against whatever the worker's default
happened to be — and the default is Qevik.

## Three kinds, and the one that must not be confusable

    EMPTY      no source at all. Nothing at risk, so it may run unattended.
    CUSTOMER   somebody else's repository. Normal execution path.
    QEVIK      Qevik's own source. Self-modification: policy + human approval.

The registration check that matters: a CUSTOMER entry whose path resolves to
Qevik's own repository is **refused at start-up**. Without it, "register the
customer `totally-not-qevik` pointing at /opt/qevik/atlas" is a way to launder
self-modification through the customer path — approval bypassed, by
configuration, silently.

`classify()` answers what a path really is by comparing it against the
repository this code was imported from. Derived from `__file__`, so there is no
setting that makes Qevik's repository look like somebody else's.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from .scratch import Origin as Kind
from .scratch import classify

#: The name a mission gets when it does not ask for one. Deliberately the most
#: restricted kind rather than the most convenient: an undeclared mission is one
#: nobody thought about, and the safe direction for those is "needs a person".
DEFAULT_NAME = "qevik"

#: The name for work with no source repository.
EMPTY_NAME = "none"


class UnknownOrigin(Exception):
    """A mission named an origin the registry does not have."""


class OriginRefused(Exception):
    """An origin could not be registered. Raised at start-up, never at dispatch."""


class Origin(BaseModel):
    """One allowed starting point, and what kind of thing it is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: Kind
    #: Absolute, resolved, and empty only for EMPTY.
    path: str = ""
    notes: str = ""

    @field_validator("name")
    @classmethod
    def _usable(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("an origin needs a name")
        if name != value:
            raise ValueError(f"{value!r} has surrounding whitespace; a name that "
                             "resolves only after trimming is two names")
        if any(c in name for c in "/\\.:"):
            raise ValueError(
                f"{name!r} looks like a path. Origin names are keys, and a key "
                "that can express a location defeats the point of having them")
        return name

    @property
    def modifies_qevik_itself(self) -> bool:
        """What `policy.decide` is asked. A clone of Qevik is still Qevik."""
        return self.kind is Kind.QEVIK

    @property
    def may_run_unattended(self) -> bool:
        """Whether work here can reach a queue with nobody asked.

        Only EMPTY. CUSTOMER is not self-modification, but it is still somebody's
        repository, and `policy.decide` applies its own rules to it — this
        property is about the *origin*, not about the plan.
        """
        return self.kind is Kind.EMPTY

    def location(self) -> Path | None:
        return Path(self.path) if self.path else None

    def summary(self) -> dict:
        """Everything, including the path. For logs and the worker."""
        return {"name": self.name, "kind": self.kind.value, "path": self.path,
                "modifies_qevik_itself": self.modifies_qevik_itself,
                "may_run_unattended": self.may_run_unattended,
                "notes": self.notes}

    def public(self) -> dict:
        """What a browser may see. **No path.**

        A filesystem location is not something an operator picks from or needs
        to read, and putting it in an HTTP response makes it something an
        attacker can read too — a free map of the deployment from any session
        that reaches the console. The name is the whole interface; the path is
        an implementation detail of the worker that resolves it.
        """
        return {"name": self.name, "kind": self.kind.value,
                "modifies_qevik_itself": self.modifies_qevik_itself,
                "may_run_unattended": self.may_run_unattended,
                "notes": self.notes}


def builtin() -> tuple[Origin, ...]:
    """The two origins every deployment has, derived rather than configured."""
    mine = None
    from .scratch import running_from
    found = running_from()
    if found is not None:
        mine = str(found.resolve())
    entries = [Origin(name=EMPTY_NAME, kind=Kind.EMPTY,
                      notes="no source repository; nothing at risk")]
    if mine:
        entries.append(Origin(name=DEFAULT_NAME, kind=Kind.QEVIK, path=mine,
                              notes="Qevik's own source; self-modification"))
    return tuple(entries)


class Registry(BaseModel):
    """Every origin a mission may name. Built once, at start-up."""

    model_config = ConfigDict(frozen=True)

    origins: tuple[Origin, ...]

    @classmethod
    def build(cls, customers: dict[str, str] | None = None) -> Registry:
        """Built-ins plus deployment-configured customer repositories.

        Every refusal below happens **here**, at start-up, rather than when a
        mission is dispatched. A worker configured with a bad origin should fail
        to start, loudly, in front of whoever configured it — not succeed and
        then block one mission at three in the morning.
        """
        entries = list(builtin())
        names = {o.name for o in entries}

        for name, raw in (customers or {}).items():
            if name in names:
                raise OriginRefused(
                    f"{name!r} is already an origin. Two entries with one name "
                    "means whichever the loop reached last silently wins")
            path = Path(raw).expanduser().resolve()
            if not (path / ".git").exists():
                raise OriginRefused(f"{path} is not a git repository")

            # The check the whole file exists for.
            if classify(path) is Kind.QEVIK:
                raise OriginRefused(
                    f"{name!r} points at Qevik's own repository ({path}). "
                    "Registering it as a customer origin would route "
                    "self-modification through the customer path, where policy "
                    "does not ask for approval. Use the built-in "
                    f"{DEFAULT_NAME!r} origin.")

            entry = Origin(name=name, kind=Kind.CUSTOMER, path=str(path),
                           notes="deployment-configured customer repository")
            entries.append(entry)
            names.add(name)
        return cls(origins=tuple(entries))

    def resolve(self, name: str) -> Origin:
        """A name into an origin, or a refusal. Never a fallback.

        `""` means the mission did not ask, and takes `DEFAULT_NAME` — which is
        Qevik, and therefore needs a person. A *wrong* name is an error, because
        silently treating a typo as "the default" would run unrelated work
        against Qevik's own source.
        """
        wanted = (name or DEFAULT_NAME).strip()
        for origin in self.origins:
            if origin.name == wanted:
                return origin
        raise UnknownOrigin(
            f"no origin named {wanted!r}. Known: "
            f"{', '.join(sorted(o.name for o in self.origins))}. An origin is "
            "declared in configuration, never chosen by whatever produced the "
            "mission.")

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(o.name for o in self.origins))

    def describe(self) -> list[dict]:
        """Everything, paths included. Not for a browser — see `public()`."""
        return [o.summary() for o in self.origins]

    def public(self) -> list[dict]:
        """The list a console may render. Qevik first, then empty, then
        customers alphabetically — the order somebody scanning it expects,
        rather than the order a dict happened to be built in."""
        rank = {Kind.QEVIK: 0, Kind.EMPTY: 1, Kind.CUSTOMER: 2}
        return [o.public() for o in
                sorted(self.origins, key=lambda o: (rank[o.kind], o.name))]

    def known(self, name: str) -> bool:
        """Whether a name resolves, without raising. For validating input."""
        try:
            self.resolve(name)
        except UnknownOrigin:
            return False
        return True


#: Where a deployment declares its customer repositories, so the control plane
#: and the worker read the **same** input. `name=/path,other=/path`.
#:
#: Not published by the worker and not duplicated in the control plane: two
#: registries built from different sources are two answers to "which origins
#: exist", and they disagree on the day somebody adds one to a single process.
ENVIRONMENT = "QEVIK_ORIGINS"


def from_environment(value: str | None = None) -> dict[str, str]:
    """Customer origins from `QEVIK_ORIGINS`, or none.

    Refuses malformed input rather than skipping it. An entry silently dropped
    for a missing `=` is an origin the operator believes exists, and the first
    they hear of it is a blocked mission.
    """
    import os
    raw = value if value is not None else os.environ.get(ENVIRONMENT, "")
    return parse_pairs([part for part in raw.split(",") if part.strip()])


def parse_pairs(pairs: list[str] | None) -> dict[str, str]:
    """`name=/path/to/repo` arguments into a mapping.

    Refuses a repeated name here rather than letting a dict comprehension drop
    one silently — the same failure `Registry.build` refuses, caught one layer
    earlier where the argument list is still visible.
    """
    out: dict[str, str] = {}
    for raw in pairs or []:
        if "=" not in raw:
            raise OriginRefused(
                f"{raw!r} is not name=path. An origin needs both, or there is "
                "nothing to check the name against")
        name, _, path = raw.partition("=")
        name = name.strip()
        if name in out:
            raise OriginRefused(f"{name!r} was given twice")
        if not path.strip():
            raise OriginRefused(f"{name!r} has no path")
        out[name] = path.strip()
    return out


__all__ = ["DEFAULT_NAME", "EMPTY_NAME", "Kind", "Origin", "OriginRefused",
           "Registry", "UnknownOrigin", "builtin", "parse_pairs"]
