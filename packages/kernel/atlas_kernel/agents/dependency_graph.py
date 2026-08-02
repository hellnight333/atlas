from __future__ import annotations

from collections import defaultdict, deque


class DependencyGraph:
    """Scheduling-only dependency graph with cycle validation and completion propagation."""

    def __init__(self, edges: list[tuple[str, str]]) -> None:
        self._incoming: dict[str, set[str]] = defaultdict(set)
        self._outgoing: dict[str, set[str]] = defaultdict(set)
        self._nodes: set[str] = set()

        for source, target in edges:
            self._nodes.add(source)
            self._nodes.add(target)
            self._outgoing[source].add(target)
            self._incoming[target].add(source)

        for node in list(self._nodes):
            self._incoming.setdefault(node, set())
            self._outgoing.setdefault(node, set())

    def add_node(self, node_id: str) -> None:
        self._nodes.add(node_id)
        self._incoming.setdefault(node_id, set())
        self._outgoing.setdefault(node_id, set())

    @property
    def nodes(self) -> set[str]:
        return set(self._nodes)

    def validate_no_cycles(self) -> None:
        _ = self.topological_ordering()

    def topological_ordering(self) -> list[str]:
        incoming = {node: len(self._incoming[node]) for node in self._nodes}
        queue = deque(sorted(node for node in self._nodes if incoming[node] == 0))
        ordered: list[str] = []

        while queue:
            node = queue.popleft()
            ordered.append(node)
            for neighbor in sorted(self._outgoing[node]):
                incoming[neighbor] -= 1
                if incoming[neighbor] == 0:
                    queue.append(neighbor)

        if len(ordered) != len(self._nodes):
            raise ValueError("Dependency cycle detected")

        return ordered

    def blocked_nodes(self, completed: set[str]) -> list[str]:
        blocked = [
            node
            for node in self._nodes
            if node not in completed and any(dep not in completed for dep in self._incoming[node])
        ]
        return sorted(blocked)

    def ready_nodes(self, completed: set[str], active: set[str] | None = None) -> list[str]:
        active = active or set()
        ready = [
            node
            for node in self._nodes
            if node not in completed
            and node not in active
            and all(dep in completed for dep in self._incoming[node])
        ]
        return sorted(ready)

    def parallel_groups(self) -> list[list[str]]:
        incoming = {node: len(self._incoming[node]) for node in self._nodes}
        current = sorted([node for node in self._nodes if incoming[node] == 0])
        groups: list[list[str]] = []

        while current:
            groups.append(current)
            nxt: list[str] = []
            for node in current:
                for neighbor in sorted(self._outgoing[node]):
                    incoming[neighbor] -= 1
            for node in sorted(self._nodes):
                if (
                    incoming[node] == 0
                    and node not in {n for group in groups for n in group}
                    and node not in nxt
                ):
                    nxt.append(node)
            current = nxt

        if sum(len(group) for group in groups) != len(self._nodes):
            raise ValueError("Dependency cycle detected")

        return groups

    def completion_propagation(self, completed: set[str]) -> dict[str, list[str]]:
        ready = self.ready_nodes(completed)
        blocked = self.blocked_nodes(completed)
        return {
            "ready": ready,
            "blocked": blocked,
        }
