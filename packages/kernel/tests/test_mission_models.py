"""The mission record itself, and the round trip it has to survive."""

from __future__ import annotations

def test_summary_carries_every_field_rehydrate_would_read():
    """`summary()` is written by hand and `rehydrate` derives from the model, so
    a new field lands in one and not the other unless something checks.

    The failure is quiet and expensive: the mission round-trips through the
    timeline losing whatever was added last, and the loss only shows up as a
    delivery that has forgotten which opportunity approved it.
    """
    from atlas_kernel.mission.models import Mission

    written = set(Mission(id="m", tenant_id="t", title="x").summary())
    # `id` is `mission_id` in the summary and `total_cost` is derived.
    expected = set(Mission.model_fields) - {"id"}
    missing = sorted(expected - written)
    assert not missing, (
        f"summary() does not carry {', '.join(missing)}; rehydrate reads every "
        "model field, so these would be dropped on the round trip")


def test_review_routes_are_not_shadowed_by_the_mission_route():
    """`/{mission_id}` is declared before these. A path parameter does not match
    across a `/`, so it cannot shadow them — but this repository has already
    shipped one route silently swallowed by an earlier `/{id}`, and the cost of
    pinning it is one test."""
    from atlas_kernel.mission.api import build_router

    routes = {(tuple(sorted(r.methods)), r.path) for r in build_router().routes
              if hasattr(r, "methods")}
    for methods, path in (
            (("GET",), "/api/missions/{mission_id}/artefact"),
            (("GET",), "/api/missions/{mission_id}/artefact/file"),
            (("POST",), "/api/missions/{mission_id}/review"),
            (("POST",), "/api/missions/deliver")):
        assert (methods, path) in routes, f"{path} is not registered"

    ordered = [r.path for r in build_router().routes if hasattr(r, "methods")]
    # `/deliver` must come before `/{mission_id}/plan` for the same reason, and
    # before anything that could match a literal segment as a parameter.
    assert ordered.index("/api/missions/deliver") < ordered.index(
        "/api/missions/{mission_id}/plan")


def _scopes_of(route) -> set:
    """Which scopes a route's dependencies actually enforce.

    Read out of the closure `auth.api.requires` builds, rather than out of the
    source text: a test that greps for `Scope.EXECUTE` passes when somebody
    leaves the words in a comment and deletes the dependency.
    """
    found = set()
    for dependency in route.dependant.dependencies:
        call = getattr(dependency, "call", None)
        for cell in (getattr(call, "__closure__", None) or ()):
            if hasattr(cell.cell_contents, "value"):
                found.add(cell.cell_contents)
    return found


def test_a_reviewer_who_may_only_read_cannot_record_a_decision():
    """READ shows the artefact; EXECUTE decides about it. A review is a decision
    the next boundary reads, so a viewer must not be able to leave one."""
    from atlas_kernel.auth.models import Scope
    from atlas_kernel.mission.api import build_router

    routes = {r.path: r for r in build_router().routes if hasattr(r, "methods")}

    review = routes["/api/missions/{mission_id}/review"]
    assert Scope.EXECUTE in _scopes_of(review), (
        "the review route does not require EXECUTE")

    for readable in ("/api/missions/{mission_id}/artefact",
                     "/api/missions/{mission_id}/artefact/file"):
        assert Scope.READ in _scopes_of(routes[readable]), readable
        assert Scope.EXECUTE not in _scopes_of(routes[readable]), (
            f"{readable} demands EXECUTE to *look*, which makes reviewing "
            "something only the person who can decide may do")


def test_the_control_plane_and_the_workers_agree_on_the_scratch_root():
    """The worker writes the artefact there and the control plane reads it. Two
    defaults that happen to agree today is not agreement."""
    import re
    from pathlib import Path

    from atlas_kernel.mission import artefact

    infra = Path(__file__).resolve().parents[3] / "infra"
    control = (infra / "qevik-control.service").read_text()
    declared = re.search(r"Environment=QEVIK_SCRATCH=(\S+)", control)
    assert declared, "the control unit does not declare QEVIK_SCRATCH"

    for unit in infra.glob("qevik-worker*.service"):
        used = re.search(r"--scratch\s+(\S+)", unit.read_text())
        if used:
            assert used.group(1) == declared.group(1), (
                f"{unit.name} writes scratch to {used.group(1)} and the control "
                f"plane reads {declared.group(1)}")
    assert artefact.DEFAULT_ROOT == declared.group(1), (
        "the reader's default disagrees with the deployment")


def test_the_awaiting_queue_is_not_swallowed_by_the_mission_route():
    """A path parameter matches a literal segment happily. Registered after
    `/{mission_id}` this route is served as a mission whose id is the string
    `awaiting-publication` — a 404 that reads as an empty queue."""
    from atlas_kernel.mission.api import build_router

    paths = [r.path for r in build_router().routes if hasattr(r, "methods")]
    assert "/api/missions/awaiting-publication" in paths
    assert paths.index("/api/missions/awaiting-publication") < paths.index(
        "/api/missions/{mission_id}")


def test_the_awaiting_queue_is_read_only_and_needs_only_read():
    """Seeing what is waiting is not deciding anything about it. Requiring
    EXECUTE to look would make the queue invisible to the people it is for."""
    from atlas_kernel.auth.models import Scope
    from atlas_kernel.mission.api import build_router

    routes = {r.path: r for r in build_router().routes if hasattr(r, "methods")}
    queue = routes["/api/missions/awaiting-publication"]
    assert queue.methods == {"GET"}, "the queue accepts a write method"
    assert Scope.READ in _scopes_of(queue)
    assert Scope.EXECUTE not in _scopes_of(queue)


def test_a_publication_is_not_judged_by_the_delivery_rule():
    """Both mission kinds name the same opportunity and run different recipes.

    The delivery guard says "a mission naming an approval must run the recipe
    that approval derived", which is right for a delivery and refuses every
    publication — found by publishing for real, not by a test.
    """
    from atlas_kernel.fabric import recipes

    delivery = recipes.get("deliver-website")
    publish = recipes.get("publish-website")
    assert delivery.delivers and not delivery.publishes
    assert publish.publishes and not publish.delivers, (
        "the two are told apart by these fields; a recipe with both would be "
        "judged by whichever rule ran first")


def test_a_publishing_recipe_cannot_smuggle_itself_into_a_delivery_mission():
    """The delivery guard is skipped for publishing recipes, so the publication
    guard has to be the thing that catches a substituted one."""
    import inspect

    from atlas_kernel.mission import toolrunner

    source = inspect.getsource(toolrunner.ToolAgent._publication)
    # It refuses a mission that names no publication to carry out. A delivery
    # mission has an empty `publishes`, so a publishing recipe substituted into
    # one is refused here rather than sliding past both guards.
    assert "not self._publishes" in source
    assert "names no authorised publication" in source
