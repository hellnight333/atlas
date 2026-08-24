"""Per-mission reports, and the failure they must not flatter.

P-B1 §9. A report written only on success is a record that flatters itself, and
a failed mission with no report is the case nobody can learn from — so the
tests below are mostly about the unhappy paths reading honestly.

This module was written by the first real mission through the pipeline
(`mission-8571422ba764`, commit `1492a3a7`) and promoted onto main afterwards.
These tests were written here, against the promoted file.
"""

from __future__ import annotations

from datetime import UTC, datetime

from atlas_kernel.mission import (
    AgentInvocation,
    Blocker,
    Mission,
    MissionStatus,
    Plan,
    PlanStep,
    reports,
)


def _mission(**overrides) -> Mission:
    base = dict(id="mission-abc123", tenant_id="tenant-alpha",
                title="Persist a durable report for every mission",
                requested_by="ayoub", status=MissionStatus.COMPLETE,
                plan=Plan(goal="a durable report",
                          steps=(PlanStep(order=1, title="Write reports.py"),)))
    base.update(overrides)
    return Mission(**base)


# ============================================ one report per mission, kept

def test_a_report_is_named_for_its_mission_not_just_its_day() -> None:
    """Two missions on one day with the same title are different work, and a
    report that overwrote the other would destroy the first one's evidence."""
    first = _mission(id="mission-one")
    second = _mission(id="mission-two")
    assert reports.filename(first) != reports.filename(second)
    assert "mission-one" in reports.filename(first)


def test_the_filename_sorts_by_date() -> None:
    early = reports.filename(_mission(), at=datetime(2026, 1, 2, tzinfo=UTC))
    late = reports.filename(_mission(), at=datetime(2026, 11, 2, tzinfo=UTC))
    assert early < late
    assert early.startswith("2026-01-02_")


def test_writing_a_report_creates_a_file(tmp_path) -> None:
    path = reports.write(_mission(), root=tmp_path, attempts=1,
                         committed="abc123", tests="passed")
    assert path.exists()
    assert path.parent == tmp_path / reports.REPORTS
    assert "Persist a durable report" in path.read_text()


def test_two_missions_do_not_overwrite_each_other(tmp_path) -> None:
    first = reports.write(_mission(id="mission-one"), root=tmp_path)
    second = reports.write(_mission(id="mission-two"), root=tmp_path)
    assert first != second
    assert first.exists() and second.exists()


# ============================================ the failure reads honestly

def test_a_failed_mission_still_gets_a_report() -> None:
    body = reports.render(_mission(status=MissionStatus.FAILED), attempts=3,
                          detail="the import check never passed")
    assert "failed" in body
    assert "the import check never passed" in body
    assert "What did not happen" in body


def test_a_mission_that_committed_nothing_says_so() -> None:
    """Not an empty field — a sentence."""
    body = reports.render(_mission(status=MissionStatus.FAILED))
    assert "none — nothing was committed" in body


def test_a_blocked_mission_records_what_would_unblock_it() -> None:
    blocked = _mission(
        status=MissionStatus.BLOCKED,
        blockers=(Blocker(kind="PENDING_CREDENTIAL",
                          detail="no Cloudflare token",
                          action="Add QEVIK_CLOUDFLARE_API_TOKEN"),))
    body = reports.render(blocked)
    assert "PENDING_CREDENTIAL" in body
    assert "Add QEVIK_CLOUDFLARE_API_TOKEN" in body


def test_every_report_states_that_nothing_was_pushed() -> None:
    """Stated rather than omitted, because omission reads as unknown."""
    assert "**Pushed:** no" in reports.render(_mission())


# ============================================ cost is never invented

def test_a_mission_with_no_reported_cost_says_so() -> None:
    body = reports.render(_mission())
    assert "not reported by any provider" in body
    assert "0.0" not in body.split("Total cost:")[1][:60]


def test_an_agent_that_reported_no_tokens_says_unavailable() -> None:
    mission = _mission(invocations=(
        AgentInvocation(provider="scripted", model="deterministic",
                        task="implement", cost_status="UNKNOWN"),))
    body = reports.render(mission)
    assert "tokens unavailable" in body
    assert "cost UNKNOWN" in body


def test_a_reported_cost_is_shown_with_its_provenance() -> None:
    mission = _mission(invocations=(
        AgentInvocation(provider="qwen", model="qwen-plus", task="implement",
                        input_tokens=1200, output_tokens=400, cost=0.004,
                        cost_status="ESTIMATED"),))
    body = reports.render(mission)
    assert "1200 in / 400 out" in body
    assert "cost ESTIMATED" in body
    assert "0.004" in body


def test_no_invocation_at_all_is_stated_plainly() -> None:
    assert "No agent invocation was recorded." in reports.render(_mission())


# ============================================ provenance

def test_the_report_carries_the_branch_and_the_files() -> None:
    body = reports.render(_mission(), branch="mission/mission-abc123",
                          files=("packages/kernel/atlas_kernel/mission/reports.py",),
                          committed="1492a3a7", tests="import check passed")
    assert "mission/mission-abc123" in body
    assert "reports.py" in body
    assert "1492a3a7" in body
    assert "import check passed" in body


def test_the_plan_is_included_so_the_result_can_be_judged_against_it() -> None:
    body = reports.render(_mission())
    assert "## Plan" in body
    assert "a durable report" in body
    assert "1. Write reports.py" in body


def test_tests_that_were_not_recorded_say_so() -> None:
    assert "not recorded" in reports.render(_mission())
