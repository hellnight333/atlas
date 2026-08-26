"""Which repository a mission may touch, and why it cannot be talked into another.

Moving the choice of repository from a worker flag onto the mission is the point
where a model gets a say in what it writes to. These tests are about the ways
that could go wrong: naming a path, naming somebody else's repository, naming
Qevik under a different name, or naming nothing and being given Qevik quietly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from atlas_kernel.mission import origins, policy, scratch, service
from atlas_kernel.mission.models import MissionStatus, Plan, PlanStep


def a_repo(where: Path) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", "."], cwd=where,
                   capture_output=True, check=True)
    (where / "f.txt").write_text("x\n")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@q.local",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@q.local",
           "PATH": "/usr/bin:/bin:/usr/local/bin"}
    subprocess.run(["git", "add", "."], cwd=where, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=where, env=env,
                   capture_output=True, check=True)
    return where


# --------------------------------------------------------------- the built-ins

def test_a_deployment_always_has_empty_and_qevik():
    registry = origins.Registry.build()
    assert set(registry.names()) == {"none", "qevik"}


def test_qevik_is_derived_not_configured():
    """Its path comes from `running_from()`, so it cannot be pointed elsewhere."""
    qevik = origins.Registry.build().resolve("qevik")
    assert qevik.kind is origins.Kind.QEVIK
    assert Path(qevik.path) == scratch.running_from().resolve()


def test_empty_has_no_path_and_may_run_unattended():
    none = origins.Registry.build().resolve("none")
    assert none.path == ""
    assert none.location() is None
    assert none.may_run_unattended
    assert not none.modifies_qevik_itself


def test_qevik_may_not_run_unattended():
    qevik = origins.Registry.build().resolve("qevik")
    assert qevik.modifies_qevik_itself
    assert not qevik.may_run_unattended


# ------------------------------------------------- cross-origin confusion

def test_a_customer_origin_pointing_at_qevik_is_refused(tmp_path):
    """The whole reason the registry exists.

    "Register the customer `totally-not-qevik` at /opt/qevik/atlas" would route
    self-modification through the customer path, where policy does not ask for
    approval — a bypass by configuration, silently.
    """
    mine = str(scratch.running_from())
    with pytest.raises(origins.OriginRefused, match="Qevik's own repository"):
        origins.Registry.build({"totally-not-qevik": mine})


def test_a_customer_origin_is_not_qevik_and_qevik_is_not_a_customer(tmp_path):
    registry = origins.Registry.build({"acme": str(a_repo(tmp_path / "acme"))})
    assert registry.resolve("acme").kind is origins.Kind.CUSTOMER
    assert not registry.resolve("acme").modifies_qevik_itself
    assert registry.resolve("qevik").kind is origins.Kind.QEVIK
    assert registry.resolve("acme").path != registry.resolve("qevik").path


def test_two_customer_repositories_never_share_a_location(tmp_path):
    registry = origins.Registry.build({"a": str(a_repo(tmp_path / "a")),
                                       "b": str(a_repo(tmp_path / "b"))})
    assert registry.resolve("a").path != registry.resolve("b").path


def test_a_repeated_name_is_refused_rather_than_last_one_winning(tmp_path):
    a = str(a_repo(tmp_path / "a"))
    with pytest.raises(origins.OriginRefused, match="twice"):
        origins.parse_pairs([f"acme={a}", f"acme={a}"])


def test_a_customer_may_not_take_a_builtin_name(tmp_path):
    with pytest.raises(origins.OriginRefused, match="already an origin"):
        origins.Registry.build({"qevik": str(a_repo(tmp_path / "x"))})
    with pytest.raises(origins.OriginRefused, match="already an origin"):
        origins.Registry.build({"none": str(a_repo(tmp_path / "y"))})


# ------------------------------------------------------ names are not paths

@pytest.mark.parametrize("attempt", [
    "../../etc", "/opt/qevik/atlas", "./qevik", "a/b",
    "qevik/../qevik", "C:\\repo", "qevik:latest",
])
def test_a_name_that_looks_like_a_path_cannot_resolve(attempt):
    """A planner emits strings. A string must never become a location."""
    registry = origins.Registry.build()
    with pytest.raises(origins.UnknownOrigin):
        registry.resolve(attempt)


@pytest.mark.parametrize("attempt", ["../x", "a/b", "a.b", "a:b", "a\\b"])
def test_such_a_name_cannot_even_be_declared(attempt):
    with pytest.raises(ValueError, match="looks like a path"):
        origins.Origin(name=attempt, kind=origins.Kind.EMPTY)


def test_whitespace_around_a_name_is_refused():
    """`" qevik"` and `"qevik"` resolving to the same thing is two names for one
    origin, which is one more than the registry can keep honest."""
    with pytest.raises(ValueError, match="whitespace"):
        origins.Origin(name=" qevik", kind=origins.Kind.QEVIK, path="/x")


def test_an_unknown_name_is_refused_and_never_defaulted():
    """The dangerous convenience. A typo must not run against Qevik."""
    registry = origins.Registry.build()
    with pytest.raises(origins.UnknownOrigin, match="no origin named"):
        registry.resolve("acme-web")


def test_not_asking_gives_the_origin_that_needs_a_person():
    """An undeclared mission is one nobody thought about."""
    assert origins.Registry.build().resolve("").name == origins.DEFAULT_NAME
    assert origins.Registry.build().resolve("").modifies_qevik_itself


def test_a_non_repository_is_refused_at_startup(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(origins.OriginRefused, match="not a git repository"):
        origins.Registry.build({"acme": str(tmp_path / "empty")})


def test_pairs_without_a_path_are_refused():
    with pytest.raises(origins.OriginRefused, match="not name=path"):
        origins.parse_pairs(["acme"])
    with pytest.raises(origins.OriginRefused, match="no path"):
        origins.parse_pairs(["acme="])


# ------------------------------------------------------ policy still decides

def a_plan() -> Plan:
    return Plan(goal="do a thing",
                steps=(PlanStep(order=1, title="s", files=("reports/x.md",)),),
                estimated_cost=0.1, approval_required=False)


@pytest.mark.parametrize("name,expected", [
    ("qevik", MissionStatus.AWAITING_APPROVAL),
    ("none", MissionStatus.QUEUED),
])
def test_the_origin_decides_whether_a_person_is_asked(name, expected):
    registry = origins.Registry.build()
    origin = registry.resolve(name)
    tenant = "tenant-origins"
    mission, _ = service.create(tenant=tenant, title="t", requested_by="x",
                                origin_name=name)
    mission, _ = service.transition(mission, MissionStatus.PLANNING,
                                    tenant=tenant, actor="x")
    mission, _ = service.attach_plan(
        mission, a_plan(), tenant=tenant, agent_id="self-check",
        modifies_qevik_itself=origin.modifies_qevik_itself)
    assert mission.status is expected


def test_a_customer_origin_does_not_need_the_self_modification_approval(tmp_path):
    registry = origins.Registry.build({"acme": str(a_repo(tmp_path / "acme"))})
    origin = registry.resolve("acme")
    tenant = "tenant-origins"
    mission, _ = service.create(tenant=tenant, title="t", requested_by="x",
                                origin_name="acme")
    mission, _ = service.transition(mission, MissionStatus.PLANNING,
                                    tenant=tenant, actor="x")
    mission, _ = service.attach_plan(
        mission, a_plan(), tenant=tenant, agent_id="self-check",
        modifies_qevik_itself=origin.modifies_qevik_itself)
    assert mission.status is MissionStatus.QUEUED
    # ...and the worker's later guard agrees, on the origin rather than the plan.
    assert not policy.refuse_unapproved_self_modification(
        [{"status": "planning"}, {"status": "queued"}],
        origin_is_qevik=origin.modifies_qevik_itself)


def test_the_declared_origin_survives_the_round_trip():
    tenant = "tenant-origins"
    mission, _ = service.create(tenant=tenant, title="t", requested_by="x",
                                origin_name="none")
    back = service.rehydrate(mission.summary(), tenant=tenant)
    assert back.origin_name == "none"


def test_a_declared_name_and_a_recorded_path_are_different_fields():
    """One is a request, the other is what happened. A single field would make a
    refused mission look like one that ran."""
    tenant = "tenant-origins"
    mission, _ = service.create(tenant=tenant, title="t", requested_by="x",
                                origin_name="acme")
    assert mission.origin_name == "acme"
    assert mission.origin == "" and mission.origin_kind == ""
