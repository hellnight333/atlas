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
