"""First-run state and demo installation.

The demo tests assert that installing creates *real* records, because a demo
that only looks real is exactly what this milestone forbids.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from atlas_kernel.api import app
from atlas_kernel.demos import BY_ID, CATALOGUE, get
from atlas_kernel.onboarding import STEP_ORDER, OnboardingState, OnboardingStep, Theme

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_onboarding():
    """Setup state is one row per installation, so tests must not inherit it."""
    client.post("/onboarding/reset")
    yield
    client.post("/onboarding/skip")


# --------------------------------------------------------------------------
# Onboarding
# --------------------------------------------------------------------------


def test_a_fresh_install_has_not_completed_setup() -> None:
    state = client.get("/onboarding").json()
    assert state["completed"] is False
    assert state["current_step"] == "welcome"
    assert state["progress"] == 0.0


def test_steps_advance_in_order() -> None:
    for expected in STEP_ORDER:
        state = client.get("/onboarding").json()
        assert state["current_step"] == str(expected)
        client.post(f"/onboarding/step/{expected}", json={})

    final = client.get("/onboarding").json()
    assert final["completed"] is True
    assert final["current_step"] == "done"
    assert final["progress"] == 1.0


def test_completing_a_step_twice_does_not_duplicate_it() -> None:
    """A user can go back and change an answer."""
    client.post("/onboarding/step/welcome", json={})
    client.post("/onboarding/step/welcome", json={})
    state = client.get("/onboarding").json()
    assert state["completed_steps"].count("welcome") == 1


def test_a_step_records_only_what_it_was_given() -> None:
    client.post("/onboarding/step/workspace", json={"workspace_name": "Studio"})
    state = client.get("/onboarding").json()
    assert state["workspace_name"] == "Studio"
    # Untouched fields keep their defaults rather than being nulled.
    assert state["theme"] == "dark"


def test_skipping_is_recorded_as_skipped_not_completed() -> None:
    client.post("/onboarding/skip")
    state = client.get("/onboarding").json()
    assert state["completed"] is True
    assert state["skipped"] is True


def test_reset_starts_setup_again() -> None:
    client.post("/onboarding/skip")
    client.post("/onboarding/reset")
    state = client.get("/onboarding").json()
    assert state["completed"] is False
    assert state["completed_steps"] == []


def test_an_unknown_step_is_rejected() -> None:
    assert client.post("/onboarding/step/not-a-step", json={}).status_code == 422


def test_progress_never_exceeds_one() -> None:
    state = OnboardingState(completed_steps=[str(s) for s in STEP_ORDER] + ["done", "bogus"])
    assert state.progress <= 1.0


def test_state_survives_a_round_trip() -> None:
    original = OnboardingState(
        completed=True,
        current_step=OnboardingStep.DEMOS,
        theme=Theme.LIGHT,
        workspace_name="Round trip",
        configured_providers=["anthropic"],
    )
    restored = OnboardingState.from_dict(original.to_dict())
    assert restored.theme is Theme.LIGHT
    assert restored.workspace_name == "Round trip"
    assert restored.configured_providers == ["anthropic"]


def test_unknown_enum_values_fall_back_rather_than_crash() -> None:
    """A record written by a newer Atlas must not break an older one."""
    restored = OnboardingState.from_dict({"current_step": "teleport", "theme": "neon"})
    assert restored.current_step is OnboardingStep.WELCOME
    assert restored.theme is Theme.DARK


# --------------------------------------------------------------------------
# Demo catalogue
# --------------------------------------------------------------------------


def test_all_five_required_demos_exist() -> None:
    required = {
        "content-studio",
        "automation-studio",
        "research-assistant",
        "youtube-pipeline",
        "production-pipeline",
    }
    assert required <= set(BY_ID)


def test_every_demo_is_fully_described() -> None:
    """No placeholders: every field a card renders must carry real content."""
    for demo in CATALOGUE:
        assert demo.name and demo.tagline and demo.description
        assert len(demo.description) > 120, f"{demo.id} description is too thin to be real"
        assert demo.demonstrates, f"{demo.id} claims to teach nothing"
        assert demo.steps, f"{demo.id} has no steps"
        for step in demo.steps:
            assert step.name and step.description
            assert "lorem" not in step.description.lower()
            assert "TODO" not in step.description


def test_at_least_one_demo_runs_with_no_provider_at_all() -> None:
    """A fresh install has no keys, so something must work immediately."""
    offline = [d for d in CATALOGUE if d.runs_fully_offline]
    assert offline, "no demo is runnable on a machine with no credentials"
    assert any(d.id == "automation-studio" for d in offline)


def test_every_demo_has_some_step_that_runs_offline() -> None:
    for demo in CATALOGUE:
        assert demo.offline_steps, f"{demo.id} does nothing without a provider"


def test_provider_requirements_are_declared_per_step() -> None:
    """The UI needs this to avoid offering a button that would fail."""
    for demo in CATALOGUE:
        summary = demo.summary()
        assert (
            summary["offline_step_count"] + summary["provider_step_count"] == summary["step_count"]
        )


def test_catalogue_endpoint_matches_the_catalogue() -> None:
    body = client.get("/demos").json()
    assert len(body) == len(CATALOGUE)
    assert {d["id"] for d in body} == set(BY_ID)


def test_demo_detail_and_unknown_demo() -> None:
    assert client.get("/demos/automation-studio").json()["id"] == "automation-studio"
    assert client.get("/demos/nope").status_code == 404
    assert get("nope") is None


# --------------------------------------------------------------------------
# Demo installation — the records must be real
# --------------------------------------------------------------------------


def test_installing_creates_a_real_project_that_can_be_opened() -> None:
    result = client.post("/demos/automation-studio/install").json()
    assert result["created"] in (True, False)
    project_id = result["project_id"]
    assert client.get(f"/projects/{project_id}").status_code == 200


def test_installing_creates_real_automation_rules() -> None:
    result = client.post("/demos/automation-studio/install").json()
    rules = client.get("/automation").json()
    installed = [r for r in rules if r["id"] in result["automations"]]
    # Idempotent re-install returns the existing project with no new rules.
    if result["created"]:
        assert len(installed) == len(result["automations"]) > 0


def test_installed_rules_arrive_switched_off() -> None:
    """A demo must never start doing work nobody asked for."""
    result = client.post("/demos/research-assistant/install").json()
    if not result["created"]:
        pytest.skip("already installed by an earlier run")
    for rule_id in result["automations"]:
        rule = client.get(f"/automation/{rule_id}").json()
        assert rule["enabled"] is False


def test_installed_rules_are_not_dry_run() -> None:
    """A dry-run rule reports success having done nothing, which makes the
    Run button a lie. Being switched off is the safety, not pretending."""
    result = client.post("/demos/production-pipeline/install").json()
    if not result["created"]:
        pytest.skip("already installed by an earlier run")
    for rule_id in result["automations"]:
        assert client.get(f"/automation/{rule_id}").json()["dry_run"] is False


def test_a_disabled_rule_refuses_to_run_and_says_so() -> None:
    result = client.post("/demos/content-studio/install").json()
    if not result["created"] or not result["automations"]:
        pytest.skip("already installed by an earlier run")
    rule_id = result["automations"][0]
    run = client.post(f"/automation/{rule_id}/run", json={}).json()
    assert run["status"] == "skipped"
    assert "disabled" in str(run["outputs"]).lower()


def test_an_enabled_rule_actually_applies_its_action() -> None:
    """The proof that a demo is executable on a machine with no credentials."""
    result = client.post("/demos/youtube-pipeline/install").json()
    if not result["created"] or not result["automations"]:
        pytest.skip("already installed by an earlier run")
    rule_id = result["automations"][0]
    client.post(f"/automation/{rule_id}/enable")
    run = client.post(f"/automation/{rule_id}/run", json={}).json()
    assert run["status"] == "completed"
    actions = run["outputs"]["state_actions"]
    assert actions and all(action["applied"] for action in actions)


def test_installing_twice_does_not_duplicate_the_project() -> None:
    first = client.post("/demos/automation-studio/install").json()
    second = client.post("/demos/automation-studio/install").json()
    assert second["project_id"] == first["project_id"]
    assert second["created"] is False


def test_installing_an_unknown_demo_is_a_404() -> None:
    assert client.post("/demos/imaginary/install").status_code == 404


def test_installation_is_recorded_against_setup() -> None:
    client.post("/demos/automation-studio/install")
    assert "automation-studio" in client.get("/onboarding").json()["installed_demos"]


def test_install_notes_are_honest_about_provider_requirements() -> None:
    result = client.post("/demos/automation-studio/install").json()
    if not result["created"]:
        # A re-install reports that it opened the existing project instead.
        assert any("Already installed" in note for note in result["notes"])
        return
    assert any("without a provider" in note for note in result["notes"])


def test_a_provider_dependent_demo_says_how_much_runs_now() -> None:
    summary = client.get("/demos/youtube-pipeline").json()
    assert summary["runs_fully_offline"] is False
    assert 0 < summary["offline_step_count"] < summary["step_count"]


# --------------------------------------------------------------------------
# The /api prefix the desktop client uses
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/version", "/health/report", "/demos", "/onboarding", "/projects", "/automation"],
)
def test_every_route_answers_under_both_prefixes(path: str) -> None:
    """Regression: the desktop addresses /api/projects while the kernel defines
    /projects. Without the rewrite the packaged app 404s on every request while
    the kernel underneath is perfectly healthy."""
    assert client.get(path).status_code == client.get(f"/api{path}").status_code == 200
