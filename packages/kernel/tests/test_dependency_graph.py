"""The generic dependency graph (M013 step 5).

The kernel knows "A depends on B" and nothing else. These tests use deliberately
meaningless node names, because the moment they read like a video the module has
stopped being general.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from atlas_kernel import dependency
from atlas_kernel.dependency import (
    CircularDependency,
    DependencyGraph,
    UnknownNode,
    fingerprint,
)


def _chain() -> DependencyGraph:
    """a → b → c, plus d depending on a alone."""
    graph = DependencyGraph()
    graph.add("a", fingerprint=fingerprint("a1"))
    graph.add("b", fingerprint=fingerprint("b1"), depends_on=["a"])
    graph.add("c", fingerprint=fingerprint("c1"), depends_on=["b"])
    graph.add("d", fingerprint=fingerprint("d1"), depends_on=["a"])
    graph.validate()
    return graph


def test_the_graph_knows_nothing_about_media() -> None:
    """If this module learns a domain, it has stopped being the kernel's."""
    tree = ast.parse(inspect.getsource(dependency))
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    node.body = body[1:]
    code = ast.unparse(tree).lower()
    for term in ("scene", "video", "render", "narration", "asset", "publication", "ffmpeg"):
        assert term not in code, f"dependency.py names {term!r} in executable code"


def test_a_change_propagates_to_everything_downstream() -> None:
    graph = _chain()
    recorded = graph.snapshot()
    assert graph.stale(recorded) == set()

    graph.add("a", fingerprint=fingerprint("a2"))
    # b and c are downstream of a at depth 1 and 2; d is downstream too.
    assert graph.stale(recorded) == {"a", "b", "c", "d"}


def test_a_change_does_not_propagate_upstream() -> None:
    """The economic argument for the whole design: work that nothing changed
    about is not redone."""
    graph = _chain()
    recorded = graph.snapshot()

    graph.add("c", fingerprint=fingerprint("c2"), depends_on=["b"])
    assert graph.stale(recorded) == {"c"}


def test_siblings_are_independent() -> None:
    """b and d both depend on a, but not on each other."""
    graph = _chain()
    recorded = graph.snapshot()

    graph.add("b", fingerprint=fingerprint("b2"), depends_on=["a"])
    assert graph.stale(recorded) == {"b", "c"}
    assert "d" not in graph.stale(recorded)


def test_everything_is_stale_before_anything_is_built() -> None:
    """A first run has nothing recorded, and the correct answer is "all of it"."""
    graph = _chain()
    assert graph.stale({}) == {"a", "b", "c", "d"}


def test_the_rebuild_plan_is_in_dependency_order() -> None:
    """So a caller executing it top to bottom never rebuilds something before
    what it is built from."""
    graph = _chain()
    order = [node.id for node in graph.rebuild_plan({})]
    assert order.index("a") < order.index("b") < order.index("c")
    assert order.index("a") < order.index("d")


def test_declaration_order_is_not_a_change() -> None:
    """Dependencies are sorted before hashing, so listing them differently must
    not look like an edit."""
    left = DependencyGraph()
    left.add("x", fingerprint="x")
    left.add("y", fingerprint="y")
    left.add("z", fingerprint="z", depends_on=["x", "y"])

    right = DependencyGraph()
    right.add("x", fingerprint="x")
    right.add("y", fingerprint="y")
    right.add("z", fingerprint="z", depends_on=["y", "x"])

    assert left.effective_fingerprint("z") == right.effective_fingerprint("z")


def test_dependents_can_be_listed_before_the_work_starts() -> None:
    """ "Changing this affects these six things" is a better question to answer
    before the work than after."""
    graph = _chain()
    assert graph.dependents_of("a") == {"b", "c", "d"}
    assert graph.dependents_of("c") == set()


def test_a_cycle_is_refused() -> None:
    """Effective fingerprints would never settle."""
    graph = DependencyGraph()
    graph.add("one", fingerprint="1", depends_on=["two"])
    graph.add("two", fingerprint="2", depends_on=["one"])
    with pytest.raises(CircularDependency):
        graph.validate()
    with pytest.raises(CircularDependency):
        graph.effective_fingerprint("one")


def test_a_dangling_dependency_is_refused() -> None:
    """A build-time error, rather than a rebuild that quietly skips half the
    work."""
    graph = DependencyGraph()
    graph.add("only", fingerprint="1", depends_on=["missing"])
    with pytest.raises(UnknownNode, match="missing"):
        graph.validate()


def test_asking_about_an_unknown_node_is_an_error() -> None:
    with pytest.raises(UnknownNode):
        DependencyGraph().effective_fingerprint("nope")


def test_absent_and_blank_are_different_inputs() -> None:
    """Conflating them would hide a real change."""
    assert fingerprint(None) != fingerprint("")
    assert fingerprint("a", None) != fingerprint("a", "")


def test_readding_a_node_invalidates_cached_answers() -> None:
    graph = _chain()
    before = graph.effective_fingerprint("c")
    graph.add("a", fingerprint=fingerprint("changed"))
    assert graph.effective_fingerprint("c") != before
