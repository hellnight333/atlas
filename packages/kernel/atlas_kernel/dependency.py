"""What has to be rebuilt when something changes.

The kernel knows one thing about produced work: **A depends on B**. It does not
know what A and B are. Nodes are opaque ids, fingerprints are opaque strings,
and whoever owns the domain decides what those mean.

That is the whole point. The same graph answers "which scenes need re-rendering"
for a video, "which sections need rewriting" for a blog post, and "which
listings need regenerating" for a marketplace, without learning a single thing
about any of them.

## How staleness propagates

Each node has an **own fingerprint**: the identity of its direct inputs, and
nothing else. Its **effective fingerprint** is its own combined with the
effective fingerprints of everything it depends on.

Propagation then falls out for free. Change one input and every node downstream
of it gets a different effective fingerprint, at any depth, without anyone
writing propagation rules. Change something a node does not depend on and its
fingerprint does not move -- which is what makes "keep the picture, redo the
voice" work rather than being a special case somebody has to remember.

The alternative -- invalidation rules written per relationship -- is the design
that rots. Every new output form adds rules, the rules disagree, and eventually
something either rebuilds far too much or silently ships something stale.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field


class DependencyError(RuntimeError):
    """The graph was given something it cannot make sense of."""


class UnknownNode(DependencyError):
    """A dependency was declared on a node that was never added."""


class CircularDependency(DependencyError):
    """A cycle. Effective fingerprints would never settle."""


@dataclass(frozen=True)
class Node:
    id: str
    #: Identity of this node's *direct* inputs. Not its dependencies -- those
    #: are followed by the graph, and including them here would double-count.
    fingerprint: str
    depends_on: tuple[str, ...] = ()
    #: Anything the caller wants to carry along. The graph never reads it.
    labels: Mapping[str, str] = field(default_factory=dict)


class DependencyGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._effective: dict[str, str] = {}

    # -- construction -----------------------------------------------------

    def add(
        self,
        node_id: str,
        *,
        fingerprint: str,
        depends_on: Iterable[str] = (),
        labels: Mapping[str, str] | None = None,
    ) -> Node:
        node = Node(
            id=node_id,
            fingerprint=fingerprint,
            depends_on=tuple(depends_on),
            labels=dict(labels or {}),
        )
        self._nodes[node_id] = node
        # Any cached answer may now be wrong.
        self._effective.clear()
        return node

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes

    def __len__(self) -> int:
        return len(self._nodes)

    def get(self, node_id: str) -> Node:
        node = self._nodes.get(node_id)
        if node is None:
            raise UnknownNode(f"no node {node_id!r} in the graph")
        return node

    def nodes(self) -> list[Node]:
        return list(self._nodes.values())

    # -- fingerprints -----------------------------------------------------

    def effective_fingerprint(self, node_id: str) -> str:
        """This node's identity, including everything it is built from."""
        return self._effective_fingerprint(node_id, tuple())

    def _effective_fingerprint(self, node_id: str, visiting: tuple[str, ...]) -> str:
        cached = self._effective.get(node_id)
        if cached is not None:
            return cached

        if node_id in visiting:
            cycle = " -> ".join([*visiting[visiting.index(node_id) :], node_id])
            raise CircularDependency(f"dependency cycle: {cycle}")

        node = self.get(node_id)
        parts = [node.fingerprint]
        # Sorted so that declaring the same dependencies in a different order
        # is not mistaken for a change.
        for dependency in sorted(node.depends_on):
            parts.append(self._effective_fingerprint(dependency, (*visiting, node_id)))

        digest = hashlib.sha256("\x1e".join(parts).encode("utf-8")).hexdigest()[:16]
        self._effective[node_id] = digest
        return digest

    def snapshot(self) -> dict[str, str]:
        """Every node's effective fingerprint, to be recorded after a build."""
        return {node_id: self.effective_fingerprint(node_id) for node_id in self._nodes}

    # -- what needs doing -------------------------------------------------

    def stale(self, recorded: Mapping[str, str]) -> set[str]:
        """Nodes whose effective fingerprint differs from what was recorded.

        A node with no recorded fingerprint is stale: it has never been built.
        """
        return {
            node_id
            for node_id in self._nodes
            if recorded.get(node_id) != self.effective_fingerprint(node_id)
        }

    def rebuild_plan(self, recorded: Mapping[str, str]) -> list[Node]:
        """What to rebuild, in an order where dependencies come first.

        Only what actually changed. A node whose own inputs are untouched and
        whose dependencies are untouched does not appear, which is how the
        picture survives a rewritten voiceover.
        """
        stale = self.stale(recorded)
        return [node for node in self._topological() if node.id in stale]

    def dependents_of(self, node_id: str) -> set[str]:
        """Everything downstream of a node, transitively.

        For explaining a plan to a person: "changing this affects these six
        things" is a better question to answer before the work than after.
        """
        self.get(node_id)
        found: set[str] = set()
        frontier = [node_id]
        while frontier:
            current = frontier.pop()
            for node in self._nodes.values():
                if current in node.depends_on and node.id not in found:
                    found.add(node.id)
                    frontier.append(node.id)
        return found

    def _topological(self) -> list[Node]:
        ordered: list[Node] = []
        state: dict[str, int] = {}  # 0 = visiting, 1 = done

        def visit(node_id: str, trail: tuple[str, ...]) -> None:
            mark = state.get(node_id)
            if mark == 1:
                return
            if mark == 0:
                cycle = " -> ".join([*trail[trail.index(node_id) :], node_id])
                raise CircularDependency(f"dependency cycle: {cycle}")

            state[node_id] = 0
            node = self.get(node_id)
            for dependency in sorted(node.depends_on):
                visit(dependency, (*trail, node_id))
            state[node_id] = 1
            ordered.append(node)

        for node_id in sorted(self._nodes):
            visit(node_id, tuple())
        return ordered

    def validate(self) -> None:
        """Every declared dependency exists, and there are no cycles.

        Called once after construction so a malformed graph is a build-time
        error rather than a rebuild that quietly skips half the work.
        """
        for node in self._nodes.values():
            for dependency in node.depends_on:
                if dependency not in self._nodes:
                    raise UnknownNode(
                        f"{node.id!r} depends on {dependency!r}, which is not in the graph"
                    )
        self._topological()


def fingerprint(*parts: object) -> str:
    """A stable fingerprint for a node's own inputs.

    ``None`` and an empty string are deliberately different: "this input is
    absent" and "this input is blank" are not the same state, and conflating
    them hides a real change.
    """
    material = "\x1f".join("\x00NULL" if part is None else str(part) for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
