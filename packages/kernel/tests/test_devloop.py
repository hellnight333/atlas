"""The development loop's state machine, and the guards that make it safe.

The driver exists because neither agent can be trusted to hold state: both lose
context, stop early, and write confident reports about work they did not
finish. So the tests that matter here are the ones that prove the driver does
not believe them — and the ones that prove a crash loses nothing.
"""

from __future__ import annotations

import ast
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parents[3] / "infra"
sys.path.insert(0, str(INFRA))

from devloop import agents, boundary, gates  # noqa: E402
from devloop.queue import Queue, State, redact  # noqa: E402


@pytest.fixture
def q(tmp_path) -> Queue:
    return Queue(tmp_path / "state.db")


# --------------------------------------------------- the queue survives things


def test_a_claimed_task_whose_driver_died_becomes_runnable_again(q):
    """The lease, which is the whole reason this is SQLite and not markdown.

    A driver killed between "I took this" and "I finished it" must not hold the
    task for ever. Nothing else in the design recovers from a power cut.
    """
    ident = q.add(title="t", brief="b", origin="human", paths=["infra/"])
    assert q.claim(owner="first") is not None
    assert q.claim(owner="second") is None, "two drivers took the same task"

    # The first driver dies. Its lease expires.
    q.move(ident, State.BUILDING,
           lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    reclaimed = q.claim(owner="second")
    assert reclaimed is not None and reclaimed["id"] == ident
    assert reclaimed["attempts"] == 2
    assert any("expired lease" in t["reason"] for t in q.transitions(ident))


def test_state_survives_reopening_the_database(tmp_path):
    """Process crash, terminal closed, machine restarted: same answer."""
    path = tmp_path / "state.db"
    first = Queue(path)
    ident = first.add(title="survives", brief="b", origin="human", paths=["infra/"])
    first.claim(owner="d1")
    first.close()

    second = Queue(path)
    found = second.get(ident)
    assert found["state"] == State.BUILDING
    assert found["title"] == "survives"
    assert len(second.transitions(ident)) == 2


def test_work_with_no_evidence_cannot_claim_production_origin(q):
    """Never generate work merely to keep the agents busy."""
    with pytest.raises(ValueError, match="invented"):
        q.add(title="something", brief="b", origin="production", paths=["infra/"])
    # Negative control: with evidence it is accepted.
    assert q.add(title="something", brief="b", origin="production", paths=["infra/"],
                 evidence={"row": {"n": 4}})


def test_nothing_secret_reaches_the_database(q):
    ident = q.add(title="deploy with sk-abcdefghijklmnopqrstuvwx12",
                  brief="token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
                  origin="human", paths=["infra/"])
    found = q.get(ident)
    assert "sk-abcdefghijklmnop" not in found["title"]
    assert "ghp_abcdefghijkl" not in found["brief"]
    assert "[REDACTED]" in found["title"]


# ------------------------------------------------------ parking and resuming


def test_a_parked_task_is_never_claimed_and_resumes_where_it_stopped(q):
    """The resumption requirement.

    A boundary answered two days later must not restart work that was already
    built and gated. The stage and the commit are written down so a *different*
    driver process can pick it up.
    """
    ident = q.add(title="needs smtp", brief="b", origin="human", paths=["infra/"])
    q.claim(owner="d1")
    q.park(ident, request_id="human-credential-smtp", stage=State.GATING,
           sha="abc123", reason="SMTP credential required", run_id="r-1")

    assert q.claim(owner="d2") is None, "a parked task was handed out"
    found = q.get(ident)
    assert found["state"] == State.WAITING_FOR_HUMAN
    assert found["resume_stage"] == State.GATING
    assert found["resume_sha"] == "abc123"
    assert found["driver_run_id"] == "r-1"
    # No lease, so it can never be reclaimed by a timeout either.
    assert found["lease_expires_at"] is None

    q.release(ident, because="the credential was stored")
    assert q.claim(owner="d2")["id"] == ident


def test_one_request_releases_every_task_it_was_blocking(q):
    """A missing credential blocks sending, verification and the proof at once."""
    ids = [q.add(title=f"t{n}", brief="b", origin="human", paths=["infra/"]) for n in range(3)]
    for ident in ids:
        q.claim(owner="d1")
        q.park(ident, request_id="human-credential-smtp", stage=State.BUILDING,
               sha="abc", reason="SMTP")
    assert len(q.blocked_by("human-credential-smtp")) == 3
    for task in q.blocked_by("human-credential-smtp"):
        q.release(task["id"], because="resolved")
    assert q.blocked_by("human-credential-smtp") == []


def test_an_unreachable_control_plane_leaves_a_task_parked(monkeypatch, q):
    """Three states, and the third is the one that matters.

    A control plane that could not be read has not said the request is
    unresolved. Treating silence as "go ahead" would resume work on a boundary
    nobody cleared; treating it as "still blocked" is safe and is what happens.
    """
    ident = q.add(title="t", brief="b", origin="human", paths=["infra/"])
    q.claim(owner="d1")
    q.park(ident, request_id="human-question-x", stage=State.BUILDING,
           sha="abc", reason="a decision")
    monkeypatch.setattr(boundary, "_remote", lambda *a, **k: None)
    assert boundary.resolved("human-question-x") is None
    assert boundary.release_resolved(q) == 0
    assert q.get(ident)["state"] == State.WAITING_FOR_HUMAN


def test_a_boundary_only_becomes_a_request_when_it_names_one():
    """An agent that is merely uncertain may not manufacture a human request."""
    assert boundary.classify("SMTP credential required") == "credential"
    # A product decision arrives as a QUESTION: the agent knows what stopped
    # it, not what the options are, and a decision with no options can never
    # be answered.
    assert boundary.classify("this needs a product decision") == "question"
    assert boundary.classify("DNS records must exist") == "provisioning"
    # Anything else is a question: it accepts free text and authorises nothing.
    assert boundary.classify("I am unsure which name reads better") == "question"


# ------------------------------------------------- the reviewer stays blind


def test_the_reviewer_is_never_told_what_the_builder_did():
    """Structural, and the reason the reviewer works.

    Proved before the driver existed: given one file and no report, Codex found
    two real defects in code that had passed 3964 tests and its author's own
    review. `reviewer_prompt` takes no arguments, so there is no parameter
    through which a report could be passed.
    """
    import inspect

    signature = inspect.signature(agents.reviewer_prompt)
    assert not signature.parameters, (
        "the reviewer's prompt accepts an argument, so it can be told what the "
        "builder claims — which is the one thing that stops it reviewing")

    source = Path(INFRA / "devloop" / "agents.py").read_text()
    tree = ast.parse(source)
    review_fn = next(n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == "review")
    names = {a.arg for a in review_fn.args.args + review_fn.args.kwonlyargs}
    assert names == {"cwd", "base_sha", "out_file", "timeout", "effort"}, (
        f"review() takes {sorted(names)}; anything carrying the builder's "
        "output or the task brief must not be among them")
    # Structural, not merely disciplined: `codex exec review --base` and a
    # positional prompt are mutually exclusive, so the CLI itself refuses an
    # invocation that carried the builder's account of the change.
    assert '"--base", prepared' in source, (
        "the review is not run against a base commit in the isolated repo")


def test_the_reviewer_runs_on_an_immutable_git_range():
    source = Path(INFRA / "devloop" / "agents.py").read_text()
    call = source[source.index('"codex", "exec", "review"'):][:300]
    # `prepared` is the base commit inside the isolated repository — still a
    # git range, and one the reviewer cannot see behind.
    assert '"--base", prepared' in call, "the review unit is not a git range"
    assert '"--json"' in call, "the review is not read as structured events"


@pytest.mark.parametrize("text,expect", [
    ("- [P1] A thing — /x/y.py:3-3\n  because of z", "DEFECTS_FOUND"),
    ("I found no issues in this diff.", "CLEAN"),
])
def test_a_review_is_read_from_what_the_reviewer_actually_wrote(text, expect):
    parsed = agents.parse_review(text, repo=Path("/x"))
    assert parsed and parsed["verdict"] == expect


def test_an_empty_review_is_never_clean():
    """Fails closed on nothing at all.

    Prose with no findings section *is* clean — that is decided by shape in
    `test_a_clean_review_in_words_the_parser_had_not_seen_is_still_clean`. An
    empty message is different: the reviewer said nothing, which establishes
    nothing.
    """
    assert agents.parse_review("", repo=Path(".")) is None
    assert agents.parse_review("   \n  ", repo=Path(".")) is None


def test_severity_comes_from_the_reviewers_own_p_level():
    for level, severity in (("P1", "blocking"), ("P2", "major"), ("P3", "minor")):
        parsed = agents.parse_review(f"- [{level}] X — /x/y.py:1-1\n  why",
                                     repo=Path("/x"))
        assert parsed["findings"][0]["severity"] == severity


def test_every_finding_must_carry_all_six_fields():
    import json

    schema = json.loads((INFRA / "devloop" / "review.schema.json").read_text())
    required = set(schema["properties"]["findings"]["items"]["required"])
    assert required == {"severity", "file", "claim", "why_it_matters",
                        "failure_scenario"}


def test_a_reviewer_that_produced_nothing_is_not_a_clean_review(monkeypatch,
                                                                tmp_path):
    """Exit zero with no structured answer is broken tooling, not a pass.

    Treating it as clean is exactly how a loop ships unreviewed code all night
    and reports success in the morning.
    """
    monkeypatch.setattr(agents, "_run", lambda *a, **k: (0, "fine", False))
    out = agents.review(cwd=tmp_path, base_sha="abc",
                        out_file=tmp_path / "nothing.json", timeout=10)
    assert out.ok is False
    assert out.infrastructure_failure is True


# --------------------------------------------------------- objective gates


def test_a_gate_that_could_not_run_is_not_a_pass(tmp_path):
    """`unmeasured` is a third state, and the driver stops on it."""
    outside = gates.changed(cwd=tmp_path / "not-a-repo")
    assert outside.passed is False and outside.unmeasured is True


def test_an_empty_diff_fails_the_change_gate(tmp_path):
    import subprocess

    repo = tmp_path / "r"
    repo.mkdir()
    for argv in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"]):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "one"], cwd=repo, check=True,
                   capture_output=True)

    assert gates.changed(cwd=repo).passed is False, (
        "an agent that changed nothing passed the gate that exists to catch it")
    (repo / "b.txt").write_text("y")
    assert gates.changed(cwd=repo).passed is True


def test_required_gates_are_declared_not_inferred():
    assert gates.required({"requires_deploy": 0, "requires_prod_check": 0}) == (
        "changed", "tests", "scope", "review")
    assert "deployed" in gates.required({"requires_deploy": 1})
    assert "in_production" in gates.required({"requires_prod_check": 1})


def test_the_driver_never_treats_prose_as_success():
    """`is_error` and the exit code decide. A summary never does."""
    source = Path(INFRA / "devloop" / "agents.py").read_text()
    build_fn = source[source.index("def build("):source.index("def builder_prompt(")]
    assert 'data.get("is_error")' in build_fn and "code != 0" in build_fn
    for word in ("completed successfully", '"done" in', "looks good"):
        assert word not in build_fn


# ------------------------------------------------- a builder that stopped short


def _stopped(subtype: str) -> agents.Outcome:
    """A builder run that ended badly, the way `claude -p` reports it."""
    return agents.Outcome(
        ok=False, exit_code=1, output="",
        data={"is_error": True, "subtype": subtype}, stop_reason=subtype,
        detail=f"builder reported an error (exit 1): {subtype}")


def test_build_records_how_the_run_ended(monkeypatch):
    """The harness's own `subtype`, carried rather than flattened to a bool."""
    monkeypatch.setattr(
        agents, "_run",
        lambda *a, **k: (1, '{"is_error": true, "subtype": "error_max_turns"}',
                         False))
    out = agents.build({"title": "t", "brief": "b"}, cwd=Path("."),
                       max_turns=1, timeout=10)
    assert out.ok is False and out.stop_reason == "error_max_turns"
    assert agents.stopped_short(out) is True
    assert agents.stopped_short(_stopped("error_during_execution")) is False
    assert agents.stopped_short(_stopped("")) is False, \
        "a stop with no stated reason is unexplained, not completion-like"
    assert agents.stopped_short(agents.Outcome(ok=True, exit_code=0)) is False


def _driver_for(q, tmp_path):
    from devloop import driver as driver_mod

    ident = q.add(title="one task", brief="do it", origin="human", paths=["infra/"])
    task = q.claim(owner="test")
    return driver_mod, driver_mod.Driver(q, driver_mod.Limits(),
                                         repo=tmp_path), ident, task


def test_an_unexplained_builder_failure_never_reaches_the_gates(monkeypatch, q,
                                                                tmp_path):
    """A builder that died mid-edit has not carried out the task.

    Nothing downstream can tell finished work from half-finished: the gates
    read git and pytest, so they establish only that the repository is
    consistent, and the reviewer is blind to the brief by design. If this fell
    through, a build that failed after one valid but incomplete edit could pass
    both and be marked DONE — and deployed.
    """
    driver_mod, driver, ident, task = _driver_for(q, tmp_path)
    monkeypatch.setattr(driver_mod.agents, "build",
                        lambda *a, **k: _stopped("error_during_execution"))

    def never(**_):
        raise AssertionError("an unexplained builder failure reached the gates")

    monkeypatch.setattr(driver_mod.gates, "changed", never)

    assert driver.run_task(task) == State.FAILED
    assert q.get(ident)["state"] == State.FAILED
    assert any("error_during_execution" in t["reason"]
               for t in q.transitions(ident)), \
        "the failure was recorded without saying how the builder ended"


def test_a_builder_that_only_ran_out_of_turns_is_judged_by_the_gates(monkeypatch,
                                                                     q, tmp_path):
    """Negative control: the one known ending that may hold finished work.

    The builder is told to finish and may have done so on its last turn, so
    the tree is judged rather than discarded. The gates still decide — here
    they find nothing changed and fail it, which is the proof they were asked.
    """
    driver_mod, driver, ident, task = _driver_for(q, tmp_path)
    monkeypatch.setattr(driver_mod.agents, "build",
                        lambda *a, **k: _stopped("error_max_turns"))
    reached = []
    monkeypatch.setattr(
        driver_mod.gates, "changed",
        lambda **k: (reached.append("changed"),
                     gates.Gate("changed", False, "nothing was changed"))[1])

    assert driver.run_task(task) == State.FAILED
    assert reached == ["changed"], "the turn limit was treated as a verdict"
    assert any("nothing was changed" in t["reason"]
               for t in q.transitions(ident)), "the gates did not decide it"


def test_one_task_runs_are_still_accounted_for(monkeypatch, q, tmp_path):
    """`--once` bounds the work, and never the run's record of it.

    Returning from inside the loop skipped the accounting below it: a finished
    task was recorded against a run showing zero completed, a failed one was
    never counted against the run at all, and the reason written down read
    `finished` whatever had actually happened.
    """
    driver_mod, driver, ident, _ = _driver_for(q, tmp_path)
    q.move(ident, State.QUEUED, reason="back for the loop to claim")
    monkeypatch.setattr(driver_mod.projection, "write", lambda *a, **k: None)
    monkeypatch.setattr(driver_mod.Driver, "run_task",
                        lambda self, task: State.DONE)

    because = driver.loop(max_tasks=6, stop_after_one=True)
    assert because == f"one task attempted, ending {State.DONE}"
    run = q.run(driver.run_id)
    assert run["tasks_completed"] == 1, "the completed task was not counted"
    assert run["stopped_because"] == because, "the run recorded a stale reason"

    # And the other half of the accounting: a failed attempt is counted against
    # the run, so a `--once` invocation that failed does not read as a run that
    # did nothing.
    q.add(title="another", brief="b", origin="human", paths=["infra/"])
    monkeypatch.setattr(driver_mod.Driver, "run_task",
                        lambda self, task: State.FAILED)
    failed_run = driver.loop(max_tasks=6, stop_after_one=True)
    assert failed_run == f"one task attempted, ending {State.FAILED}"
    assert q.run(driver.run_id)["infra_failures"] == 1
    assert q.run(driver.run_id)["stopped_because"] == failed_run


def test_the_evaluation_queue_holds_third_party_projects_unassessed(q):
    """Nothing is integrated before somebody has looked at it."""
    first = q.add_evaluation(name="Camofox", url="https://example.test/camofox",
                             why="browser automation")
    again = q.add_evaluation(name="Camofox", url="https://example.test/camofox",
                             why="duplicate")
    assert first == again, "the evaluation queue is not idempotent"
    assert q.evaluations()[0]["state"] == "UNEVALUATED"


# ------------------------------- what the proving run found in the driver


def test_a_clean_review_in_words_the_parser_had_not_seen_is_still_clean():
    """The defect the first proving run hit, in the reviewer's own words.

    Round two came back "The changes consistently scope provenance and approval
    data ... without an evident regression." — a clean review. The parser knew
    a list of clean phrases, did not recognise that one, and failed closed, so
    a task that had actually passed was requeued.

    Clean is decided by shape now: `codex exec review` prints a "Review
    comment:" section when it has findings, so its absence is the verdict.
    """
    real = ("The changes consistently scope provenance and approval data to "
            "the displayed recipient and draft, preserve historical context, "
            "and add appropriate regression tests. The devloop accounting and "
            "stop-reason handling also address the identified failure modes "
            "without an evident regression.")
    parsed = agents.parse_review(real, repo=Path("."))
    assert parsed == {"verdict": "CLEAN", "findings": []}


def test_a_review_that_announces_findings_and_parses_none_is_unreadable():
    """The half that must keep failing closed.

    A reviewer that says "Review comment:" and then writes something this
    cannot read has findings nobody has seen. Reporting that clean is how
    unreviewed code ships overnight.
    """
    assert agents.parse_review(
        "Something is wrong here.\n\nReview comments:\n\n  (unparseable)",
        repo=Path(".")) is None


def test_a_task_refuses_to_start_on_a_dirty_tree(tmp_path, monkeypatch):
    """The other defect the proving run exposed.

    `_commit` stages everything, so edits made by hand while the loop ran were
    committed under the task's name and reviewed as its work — and the reviewer
    duly raised findings against code the task never touched.
    """
    import devloop.driver as drv

    q = Queue(tmp_path / "s.db")
    ident = q.add(title="t", brief="b", origin="human", paths=["infra/"])
    task = q.claim(owner="d")
    def fresh_start(*args, **kwargs):
        # No branch for this task: a fresh start, so whatever is in the tree
        # belongs to somebody else.
        if args[:2] == ("rev-parse", "--verify"):
            return 1, ""
        return 0, " M somebody_elses_file.py"

    monkeypatch.setattr(drv, "_git", fresh_start)
    driver = drv.Driver(q, drv.Limits(), repo=tmp_path)
    assert driver.run_task(task) == State.FAILED
    assert q.get(ident)["state"] == State.QUEUED, (
        "a refused task must return to the queue, not be lost")


def test_work_under_review_never_lands_on_main(tmp_path):
    """The second proving run put a defective round on `main`.

    Each round has to commit, because the review unit must be an immutable
    range. Committing them to `main` meant a round the reviewer then raised
    three blocking findings against was already there. Work under review is not
    work that has passed.
    """
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    run_task = source[source.index("def run_task("):source.index("def _ship(")]
    # Either way of getting onto the branch — created fresh, or resumed — as
    # long as the task never builds on `main` itself.
    assert ('"checkout", "-q", "-b", branch' in run_task
            and '"checkout", "-q", branch' in run_task), (
        "a task builds on `main` rather than on its own branch")
    assert '"-B", branch' not in run_task, (
        "`-B` resets the branch to HEAD and would discard a parked task's work")
    ship = source[source.index("def _ship("):source.index("def _commit(")]
    assert '"merge", "--squash", branch' in ship, (
        "reviewed work does not land as one commit")
    # Landing may only happen after the review is clean, which is the only
    # path into `_ship`.
    assert "_ship(" in run_task[run_task.index("if not must:"):
                                run_task.index("if not must:") + 200]


# ============================================================ main protection
#
# The failure this section exists for actually happened: three commits reached
# `main` carrying a task's work that had never come back clean — two rounds the
# reviewer raised blocking findings against, and a third round nothing reviewed
# at all. Prompting an agent not to do that is not a guard. These are.


def test_a_round_that_never_reviewed_can_never_land(q):
    """No recorded review means unreviewed, and unreviewed never lands."""
    ident = q.add(title="t", brief="b", origin="human", paths=["infra/"])
    assert q.review_was_clean(ident) is False, (
        "a task nothing reviewed reported itself clean")


def test_a_commit_the_reviewer_objected_to_can_never_land(q):
    ident = q.add(title="t", brief="b", origin="human", paths=["infra/"])
    q.move(ident, State.REVIEWING, head_sha="aaa", review_rounds=1)
    q.record_review(ident, round=1, sha="aaa", verdict="DEFECTS_FOUND",
                    findings=1)
    q.record_findings(ident, round=1, sha="aaa", findings=[
        {"severity": "blocking", "file": "f.py", "claim": "c",
         "why_it_matters": "w", "failure_scenario": "s"}])
    assert q.review_was_clean(ident) is False

    # Negative control: a later commit reviewed clean does land, so the refusal
    # above is the finding and not a gate that refuses everything.
    q.move(ident, State.REVIEWING, head_sha="bbb", review_rounds=2)
    q.record_review(ident, round=2, sha="bbb", verdict="CLEAN", findings=0)
    assert q.review_was_clean(ident) is True


def test_a_reopened_task_does_not_inherit_the_old_runs_objections(q):
    """The defect this cost a run to find.

    Rounds restart when a task is reopened. Keyed on round number, a clean
    review at round 2 of the new run was refused because round 2 of the *old*
    run had raised a major finding — against a different commit entirely. It
    failed in the safe direction and was still wrong.
    """
    ident = q.add(title="t", brief="b", origin="human", paths=["infra/"])
    q.move(ident, State.REVIEWING, head_sha="old", review_rounds=2)
    q.record_review(ident, round=2, sha="old", verdict="DEFECTS_FOUND",
                    findings=1)
    q.record_findings(ident, round=2, sha="old", findings=[
        {"severity": "major", "file": "f.py", "claim": "an old objection",
         "why_it_matters": "w", "failure_scenario": "s"}])

    q.move(ident, State.QUEUED, reason="reopened")
    q.move(ident, State.REVIEWING, head_sha="new", review_rounds=2)
    q.record_review(ident, round=2, sha="new", verdict="CLEAN", findings=0)
    assert q.review_was_clean(ident) is True, (
        "a clean review was refused because an earlier run objected at the "
        "same round number")


def test_a_head_nobody_reviewed_can_never_land(q):
    """A clean review records no findings, so their absence proves nothing.

    Without a record that a review of *this commit* ran, "no findings" and
    "nobody looked" are the same thing — and the second must never land.
    """
    ident = q.add(title="t", brief="b", origin="human", paths=["infra/"])
    q.move(ident, State.REVIEWING, head_sha="reviewed", review_rounds=1)
    q.record_review(ident, round=1, sha="reviewed", verdict="CLEAN", findings=0)
    assert q.review_was_clean(ident) is True

    # The builder pushed another commit; nothing has reviewed it.
    q.move(ident, State.REVIEWING, head_sha="unreviewed", review_rounds=1)
    assert q.review_was_clean(ident) is False


def test_a_minor_finding_does_not_hold_a_task_but_a_major_one_does(q):
    for severity, expected in (("minor", True), ("major", False),
                               ("blocking", False)):
        ident = q.add(title=f"t-{severity}", brief="b", origin="human", paths=["infra/"])
        q.move(ident, State.REVIEWING, head_sha="a", review_rounds=1)
        q.record_review(ident, round=1, sha="a", verdict="DEFECTS_FOUND",
                        findings=1)
        q.record_findings(ident, round=1, sha="a", findings=[
            {"severity": severity, "file": "f.py", "claim": "c",
             "why_it_matters": "w", "failure_scenario": "s"}])
        assert q.review_was_clean(ident) is expected, severity


def test_landing_asks_the_record_rather_than_the_control_flow():
    """Structural, not incidental.

    `_ship` is only reachable from a clean review *today*. A future edit could
    add a second caller, and then main protection would rest on nobody having
    made that mistake. So `_ship` re-asks the stored findings before it merges,
    and the merge is unreachable without that answer.
    """
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    ship = source[source.index("def _ship("):source.index("def _touched(")]
    guard = ship.index("review_was_clean")
    merge = ship.index('"merge", "--squash"')
    assert guard < merge, (
        "the squash-merge is not behind the recorded-review check")
    assert "CONTESTED" in ship[guard:merge], (
        "a task that fails the check is not parked before the merge")


def test_the_review_unit_never_absorbs_another_tasks_edits():
    """The uncontrolled staging that caused the contamination.

    `git add -A` swept unrelated working-tree edits into a task's commit, and
    the reviewer raised two findings against code the task had never touched.
    """
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    assert '"add", "-A"' not in source, (
        "uncontrolled staging is back; a task will absorb whatever else is in "
        "the tree and the reviewer will judge work it was not given")
    commit = source[source.index("def _commit("):source.index("def _infra(")]
    assert "self._touched()" in commit, (
        "paths are not staged explicitly from what the task changed")


def test_a_task_that_ends_contested_leaves_main_untouched():
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    run_task = source[source.index("def run_task("):source.index("def _ship(")]
    contested = run_task.index("rounds")
    section = run_task[run_task.index("if round_no == self.limits.review_rounds:"):]
    assert '"checkout", "-q", "main"' in section[:400], (
        "a contested task does not return to main, so its branch stays checked "
        "out and the next task builds on top of rejected work")
    assert "merge" not in section[:400]


def test_a_resumed_branch_is_reviewed_from_where_it_left_main():
    """A parked task's review unit must be all of its work, and only its work.

    Computed before the checkout, `base` was `main`'s tip while HEAD was a
    branch that predated it — so `base..HEAD` presented every commit `main` had
    gained meanwhile as though this task had deleted it, and the reviewer would
    have been handed a diff reversing unrelated work. Caught by watching a real
    resume log the wrong base.

    `merge-base` answers it instead, and `main` is merged in first so the base
    is current: every round the task ever produced is in the unit, including
    rounds interrupted before anything reviewed them.
    """
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    run_task = source[source.index("def run_task("):source.index("def _ship(")]
    assert '"merge-base", "main", "HEAD"' in run_task, (
        "the review unit is not the branch's divergence from main")
    assert run_task.index('"checkout", "-q", branch') < \
        run_task.index('"merge-base", "main", "HEAD"'), \
        "the base is computed before the branch is checked out"
    assert '"merge", "-q", "--no-edit", "main"' in run_task, (
        "a resumed branch is not brought up to main, so its base is stale")


def test_read_only_is_not_left_to_a_configuration_flag():
    """The flag was set and the reviewer wrote anyway.

    Kept as a guard against putting the flag back and believing it. A reviewer
    that can write is a reviewer whose diff is no longer the diff that was
    built, and `sandbox_mode` did not make that impossible —
    `test_the_review_cannot_touch_the_tree_being_built` covers what does.
    """
    source = Path(INFRA / "devloop" / "agents.py").read_text()
    call = source[source.index('"codex", "exec", "review"'):][:400]
    assert 'sandbox_mode' not in call, (
        "the review is relying on a config flag that two real runs showed is "
        "not honoured; isolation is what makes it read-only")


def test_a_resumed_task_is_not_refused_for_its_own_leftover_work(tmp_path,
                                                                 monkeypatch):
    """The guard must not strand the tasks it exists to recover.

    A round interrupted mid-edit leaves uncommitted work that belongs to the
    task. Refusing to resume on it would park every task that stopped part-way
    — the exact case the branch and the lease exist for.
    """
    import devloop.driver as drv

    q = Queue(tmp_path / "s.db")
    ident = q.add(title="t", brief="b", origin="human", paths=["infra/"])
    task = q.claim(owner="d")

    calls = {"checked_out": False}

    def fake_git(*args, **kwargs):
        if args[:1] == ("status",):
            return 0, " M its_own_leftover.py"
        if args[:2] == ("rev-parse", "--verify"):
            return 0, "abc123"          # the branch exists: this is a resume
        if args[:1] == ("checkout",):
            calls["checked_out"] = True
        return 0, ""

    monkeypatch.setattr(drv, "_git", fake_git)
    monkeypatch.setattr(drv.agents, "build",
                        lambda *a, **k: drv.agents.Outcome(
                            ok=False, exit_code=1, output="",
                            infrastructure_failure=True, detail="stop here"))
    driver = drv.Driver(q, drv.Limits(), repo=tmp_path)
    driver.run_task(task)
    assert calls["checked_out"], (
        "a resumed task was refused for its own uncommitted work")
    assert not any("not clean" in t["reason"] for t in q.transitions(ident))


def test_the_review_cannot_touch_the_tree_being_built():
    """Configured read-only was not read-only.

    `codex exec review` has no `--sandbox` flag and did not honour
    `-c sandbox_mode="read-only"`: with it set, a real review edited
    `.qevik/CAPABILITY_LEDGER.md` in the working tree on two consecutive runs,
    and `clean_tree` stopped the round both times. A flag says what was asked
    for; a separate checkout says what is possible.
    """
    import inspect

    source = inspect.getsource(agents.review)
    assert "worktree" in source and "mkdtemp" in source, (
        "the reviewer runs in the tree being built, where it can write")
    # It must run *there*, not in the repository it was given.
    call = source[source.index('"codex", "exec", "review"'):][:400]
    assert "cwd=tree" in call, "the reviewer was pointed at the working tree"
    # And the worktree must go even when the review fails.
    assert "finally:" in source[:source.index('"codex", "exec", "review"')] or \
        "finally:" in source, "a failed review leaks a worktree"


def test_the_first_changed_file_keeps_its_whole_name(tmp_path):
    """The bug that cost three runs and a wrong diagnosis.

    `git status --porcelain` is column-aligned — two status characters then a
    space — and `_git` strips the combined output, which removes the leading
    space from the *first line only*. The first changed path came back missing
    its first character, git could not stage a file that does not exist, and it
    stayed dirty through the commit. `clean_tree` then reported it as the
    reviewer writing to the working tree, and three runs were spent isolating a
    reviewer that had never touched anything.

    A dotfile makes it visible; any first path would have been truncated.
    """
    import subprocess

    import devloop.driver as drv

    repo = tmp_path / "r"
    (repo / ".qevik").mkdir(parents=True)
    for argv in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"]):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    (repo / ".qevik" / "LEDGER.md").write_text("one\n")
    (repo / "later.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True,
                   capture_output=True)
    (repo / ".qevik" / "LEDGER.md").write_text("two\n")
    (repo / "later.py").write_text("x = 2\n")

    driver = drv.Driver.__new__(drv.Driver)
    driver.repo = repo
    touched = driver._touched()
    assert ".qevik/LEDGER.md" in touched, (
        f"the first path lost characters: {touched}")
    assert "later.py" in touched

    # Negative control: staging what it reports actually works, which is the
    # thing that silently failed.
    for path in touched:
        assert subprocess.run(["git", "add", "--", path], cwd=repo,
                              capture_output=True).returncode == 0, path
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                            cwd=repo, capture_output=True, text=True).stdout
    assert ".qevik/LEDGER.md" in staged


def test_untracked_files_are_staged_too(tmp_path):
    """A new test file is the commonest thing a task adds."""
    import subprocess

    import devloop.driver as drv

    repo = tmp_path / "r"
    repo.mkdir()
    for argv in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"]):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    (repo / "seed.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True,
                   capture_output=True)
    (repo / "test_new_thing.py").write_text("def test_x(): pass\n")

    driver = drv.Driver.__new__(drv.Driver)
    driver.repo = repo
    assert "test_new_thing.py" in driver._touched()


# ================================================== reviewer isolation
#
# The CLI flag is not the boundary. `codex exec review` has no `--sandbox`, and
# `-c sandbox_mode="read-only"` was set while a real review wrote to the
# working tree. What follows tests the property instead of the request.


def _repo_with_two_commits(tmp_path):
    """A repository with a base commit and a task commit, plus private state."""
    import subprocess

    repo = tmp_path / "origin"
    (repo / ".qevik").mkdir(parents=True)
    (repo / "src").mkdir()
    for argv in (["git", "init", "-q", "-b", "main"],
                 ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"]):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    (repo / "src" / "app.py").write_text("def f():\n    return 1\n")
    (repo / ".qevik" / "SESSION_LOG.md").write_text(
        "The builder changed f() to return 2 because the ledger said so.\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True,
                   capture_output=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    (repo / "src" / "app.py").write_text("def f():\n    return 2\n")
    (repo / "unrelated_uncommitted.py").write_text("secret = 'do not read me'\n")
    subprocess.run(["git", "add", "src/app.py"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-qm", "task"], cwd=repo, check=True,
                   capture_output=True)
    return repo, base


def test_the_reviewer_sees_the_base_and_the_task_diff_and_nothing_else(tmp_path):
    """Everything it must not see, checked one at a time."""
    repo, base = _repo_with_two_commits(tmp_path)
    into = tmp_path / "review"
    prepared, why = agents.isolate(repo, base_sha=base, into=into)
    assert prepared, why

    # The change is there, both sides of it.
    assert (into / "src" / "app.py").read_text() == "def f():\n    return 2\n"

    # The builder's own account of the change is not. This is the one that
    # matters: a reviewer that reads it is no longer reviewing the code.
    assert not (into / ".qevik").exists(), (
        "the reviewer can read the builder's session log, which is exactly the "
        "report it must never be given")

    # Uncommitted work belonging to nobody in particular is not.
    assert not (into / "unrelated_uncommitted.py").exists()

    # No history before the base, so no other task's commits are reachable.
    import subprocess
    history = subprocess.run(["git", "log", "--oneline"], cwd=into,
                             capture_output=True, text=True).stdout.strip()
    assert len(history.splitlines()) == 2, history
    # No remote, so nothing can be fetched back.
    remotes = subprocess.run(["git", "remote"], cwd=into, capture_output=True,
                             text=True).stdout.strip()
    assert remotes == "", f"the review repository has a remote: {remotes!r}"
    branches = subprocess.run(["git", "branch", "-a"], cwd=into,
                              capture_output=True, text=True).stdout
    assert "main" not in branches, branches


def test_a_reviewer_that_writes_cannot_reach_the_task_branch_or_main(tmp_path):
    """The negative control.

    A reviewer given the isolated repository writes to it — deletes a file,
    edits another, commits. The origin repository must be untouched: same HEAD,
    same tree, same working files.
    """
    import subprocess

    repo, base = _repo_with_two_commits(tmp_path)
    before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                 capture_output=True, text=True).stdout.strip()
    before_tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=repo,
                                 capture_output=True, text=True).stdout.strip()
    before_status = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                                   capture_output=True, text=True).stdout

    into = tmp_path / "review"
    prepared, why = agents.isolate(repo, base_sha=base, into=into)
    assert prepared, why

    # A hostile reviewer, doing the worst it could do in its own checkout.
    (into / "src" / "app.py").write_text("def f():\n    return 999\n")
    (into / "src" / "planted.py").write_text("# reviewer was here\n")
    subprocess.run(["git", "add", "-A"], cwd=into, capture_output=True)
    subprocess.run(["git", "-c", "user.email=r@r", "-c", "user.name=r",
                    "commit", "-qm", "reviewer edit"], cwd=into,
                   capture_output=True)

    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip() == before_head
    assert subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=repo,
                          capture_output=True, text=True).stdout.strip() == before_tree
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                          capture_output=True, text=True).stdout == before_status
    assert (repo / "src" / "app.py").read_text() == "def f():\n    return 2\n"
    assert not (repo / "src" / "planted.py").exists(), (
        "the reviewer planted a file in the repository being reviewed")


def test_the_review_checkout_is_destroyed_even_when_the_review_fails(monkeypatch,
                                                                     tmp_path):
    """A failed review must not leave the reviewer's writes on disk."""
    repo, base = _repo_with_two_commits(tmp_path)
    seen = {}

    def explode(argv, *, cwd, timeout, env=None):
        seen["cwd"] = Path(cwd)
        assert (Path(cwd) / "src" / "app.py").exists(), "not the isolated repo"
        return 124, "boom", True

    monkeypatch.setattr(agents, "_run", explode)
    out = agents.review(cwd=repo, base_sha=base,
                        out_file=tmp_path / "o.json", timeout=5)
    assert out.infrastructure_failure is True
    assert not seen["cwd"].exists(), "the review checkout outlived the review"


def test_the_driver_always_returns_to_main():
    """Three infrastructure commits were made onto a task branch because a
    failed run left it checked out and nobody looked."""
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    loop = source[source.index("    def loop("):source.index("    def replenish(")]
    assert '"checkout", "-q", "main"' in loop, (
        "a run can end with a task branch checked out")
    assert "finally:" in loop and loop.index("finally:") < loop.index('"checkout", "-q", "main"')


def test_a_decision_is_answerable_from_the_console_alone():
    """The options must be drawn as consequences, not as names.

    Choosing between "A" and "B" is not deciding. What makes a decision
    answerable from the page is what each option changes and which records it
    moves — otherwise the person has to go and read the engineer's report,
    which is the loop this whole system exists to remove.
    """
    console = Path(INFRA).parents[0] / "apps" / "control" / "src" / "index.html"
    source = console.read_text()
    detail = source[source.index("async function humanTask("):]
    for field in ("what_changes", "evidence_for", "records_affected"):
        assert field in detail, f"an option's {field} is never shown"
    # And the controls come from what the request says it accepts, so a
    # control the API would refuse is never drawn.
    assert "accepts.includes('choose')" in detail
    assert "data-respond=\"choose\"" in detail and "data-choice=" in detail


def test_the_round_gate_runs_only_what_the_task_touched(tmp_path, monkeypatch):
    """Measured: the full suite is ~14.6 minutes against a ~2 minute review.

    Running all of it every round spent roughly a third of each cycle
    re-proving code the task never went near. Narrowed, the same gate takes
    about three seconds. This narrows the loop, not the evidence — `_ship`
    still runs the whole suite before anything deploys.
    """
    import devloop.driver as drv

    driver = drv.Driver.__new__(drv.Driver)
    driver.repo = tmp_path
    monkeypatch.setattr(
        drv.Driver, "_touched",
        lambda self: ["packages/kernel/atlas_kernel/opportunity/coverage.py",
                      "packages/kernel/tests/test_audit_backlog.py"])
    selector = driver._selector()
    assert "coverage" in selector and "audit_backlog" in selector

    # Nothing recognisable changed: the whole suite, not a selector that
    # matches nothing and passes silently.
    monkeypatch.setattr(drv.Driver, "_touched", lambda self: ["__init__.py"])
    assert driver._selector() == ""


def test_the_full_suite_still_runs_before_anything_deploys():
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    finish = source[source.index("def _finish("):source.index("def _commit(")]
    assert "gates.tests(cwd=self.repo)" in finish, (
        "the deploy path runs a narrowed suite; a narrow gate is not enough to "
        "put code on a live host")
    assert finish.index("gates.tests(cwd=self.repo)") < finish.index("gates.deployed("), (
        "the deploy runs before the suite that is supposed to gate it")


def test_finding_paths_are_relative_to_the_tree_that_was_reviewed():
    """A blocking finding the reviewer raised against the loop's own change.

    Codex prints absolute paths. Once the review moved into an isolated
    checkout those pointed under the temporary tree, and relativising them
    against the repository left every finding naming a file nobody can open.
    """
    parsed = agents.parse_review(
        "Summary.\n\nReview comment:\n\n"
        "- [P1] A thing — /tmp/devloop-review-x/review/packages/kernel/a.py:3-3\n"
        "  because z\n",
        repo=Path("/tmp/devloop-review-x/review"))
    assert parsed["findings"][0]["file"].startswith("packages/kernel/a.py")

    # Negative control: a path outside the reviewed tree is left alone rather
    # than mangled into a relative path meaning something else.
    other = agents.parse_review(
        "Summary.\n\nReview comment:\n\n- [P1] X — /elsewhere/b.py:1-1\n  why\n",
        repo=Path("/tmp/devloop-review-x/review"))
    assert other["findings"][0]["file"] == "/elsewhere/b.py:1-1"


def test_the_review_reads_findings_against_the_isolated_tree():
    """Guard against restoring an older copy of this file and losing the fix."""
    source = Path(INFRA / "devloop" / "agents.py").read_text()
    assert "parse_review(message, repo=tree)" in source, (
        "findings are relativised against the wrong tree")


def test_a_decision_is_findable_from_the_landing_screen():
    """The operator could not find an open decision in the live console.

    The cause was that nothing was deployed — but the screen was also weak:
    "3 things need you" reads the same whether they are three credentials or a
    product decision nobody else can make, and only the decision stops a branch
    of work until it is answered.
    """
    console = Path(INFRA).parents[0] / "apps" / "control" / "src" / "index.html"
    source = console.read_text()

    dashboard = source[source.index("views.dashboard"):source.index("views.roadmap")]
    assert "only you can make" in dashboard, (
        "the landing screen does not say a decision is waiting")
    assert "'decision'" in dashboard, "decisions are not counted separately"

    # And the inbox leads with them, labelled as decisions rather than as
    # another thing to go and configure.
    assert "NEEDS A DECISION FROM YOU" in source
    assert "pill('DECISION'" in source


# ============================================ the gate that could not fail
#
# `gates.in_production` tested `"PROVED" in out`. A probe that correctly
# reported failure printed "NOT PROVED", which contains "PROVED", so the gate
# passed — and a task whose defect was still live on the public internet was
# marked DONE and production-verified. Every negation is checked below.


@pytest.mark.parametrize("output,expected", [
    ("PROVED {'sites': 359}", True),
    ("checking...\nPROVED all pages serve their own content", True),
    ("NOT PROVED {'pages_serving_the_homepage': ['/services/']}", False),
    ("NOT_PROVED", False),
    ("UNPROVED", False),
    ("DISPROVED", False),
    ("PROVED_NOTHING", False),
    ("the probe could not decide", False),
    ("", False),
])
def test_only_a_line_beginning_PROVED_passes_production(monkeypatch, output,
                                                        expected):
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: (0, output, False))
    assert gates.in_production(cwd=Path("."), probe="x").passed is expected


def test_no_gate_decides_by_searching_for_a_word_in_output():
    """The shape of the defect, kept out of every other gate.

    A substring search cannot distinguish a claim from its negation. Gates read
    exit codes, emptiness, or a token in a known position — never `"WORD" in
    output`.
    """
    import re

    # Code only. The comment explaining the defect necessarily contains it.
    code = "\n".join(
        line for line in Path(INFRA / "devloop" / "gates.py").read_text().splitlines()
        if not line.lstrip().startswith("#"))
    offenders = re.findall(r'"[A-Z_]{4,}"\s+in\s+out\b', code)
    assert not offenders, (
        f"a gate decides by substring search: {offenders}. "
        '"PROVED" in "NOT PROVED" is True.')


@pytest.mark.parametrize("reason,reaches_gates", [
    ("error_max_turns", True),
    ("success", True),
    ("error_during_execution", False),
    ("", False),
])
def test_which_builder_stops_are_judged_by_the_gates(reason, reaches_gates):
    """A resumed task with nothing left to build stopped with subtype
    `success` and exit 1, and was recorded as a failed build — discarding a
    branch that already held finished, reviewed work.

    When the agent's own account and the exit code disagree, the diff and the
    tests decide. A crash still fails without reaching them: a builder that
    died mid-edit has not carried out the task, and nothing downstream can tell
    that from finished work.
    """
    out = agents.Outcome(ok=False, exit_code=1, output="", stop_reason=reason)
    assert agents.stopped_short(out) is reaches_gates

    # A successful run is never "stopped short" — it did not stop short.
    assert agents.stopped_short(
        agents.Outcome(ok=True, exit_code=0, stop_reason=reason)) is False


def test_an_empty_diff_records_what_the_builder_said(tmp_path, monkeypatch):
    """"nothing changed" is undiagnosable on its own.

    A refusal, a crash, a boundary the builder did not phrase as one, and an
    agent that simply did nothing all leave the same empty diff. The builder's
    own words are the only thing that tells them apart afterwards.
    """
    import devloop.driver as drv

    q = Queue(tmp_path / "s.db")
    ident = q.add(title="t", brief="b", origin="human", paths=["infra/"])
    task = q.claim(owner="d")

    monkeypatch.setattr(drv, "_git", lambda *a, **k: (0, ""))
    monkeypatch.setattr(drv.agents, "build", lambda *a, **k: drv.agents.Outcome(
        ok=True, exit_code=0, output="I could not find the builder module."))
    monkeypatch.setattr(drv.gates, "changed", lambda **k: drv.gates.Gate(
        "changed", False, "nothing was changed."))
    monkeypatch.setattr(drv.agents, "stopped_short", lambda o: False)

    driver = drv.Driver(q, drv.Limits(), repo=tmp_path)
    assert driver.run_task(task) == State.FAILED
    reasons = " ".join(t["reason"] for t in q.transitions(ident))
    assert "could not find the builder module" in reasons, (
        "the failure records that nothing changed and not why")


@pytest.mark.parametrize("summary,code,passes,unmeasured", [
    ("3 passed, 8 skipped in 0.5s", 0, True, False),
    ("11 skipped in 0.4s", 0, False, True),
    ("12 passed in 3s", 0, True, False),
    ("2 failed, 9 passed in 5s", 1, False, False),
])
def test_a_run_where_everything_skipped_asserted_nothing(monkeypatch, summary,
                                                         code, passes,
                                                         unmeasured):
    """Exit zero is not the same as "something was checked".

    A task added a page to the site builder; its tests skipped because the
    artwork is gitignored and the site cannot be built locally; the gate read
    exit zero and passed; and the page was never produced by a real build. The
    tests were honest — their skip message says "Nothing below is being
    asserted" — and the gate did not read it.

    Skips are legitimate in general, so this fires only when a run selected
    tests and none of them ran.
    """
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: (code, summary, False))
    g = gates.tests(cwd=Path("."))
    assert g.passed is passes
    assert g.unmeasured is unmeasured


# ================================================= task size, enforced
#
# A 38-file, 1,863-insertion task ran three times over about two hours and
# never landed. Split at real boundaries, the same work landed in 25 and 20
# minutes — the second clean on its first review. Size is checked by the
# driver, not left to the builder's judgement.


@pytest.mark.parametrize("numstat,bounded", [
    # The four real tasks the limit is calibrated on.
    ("100\t23\tapps/public/build.py\n150\t31\tpackages/kernel/tests/t_x.py", True),
    ("70\t12\tinfra/q.Caddyfile\n200\t16\tpackages/kernel/tests/t_y.py", True),
    # A single coherent module is not oversized however long its prose. The
    # limit was 400 and parked exactly this, and splitting a module in half
    # produces two halves of one idea.
    ("379\t0\tsrc/unreviewed.py\n161\t10\tsrc/repository.py\n800\t46\t"
     "packages/kernel/tests/t_z.py", True),
    ("1400\t0\tsrc/enormous.py", False),
    ("\n".join(f"40\t3\tsrc/f{n}.py" for n in range(35)), False),
    # Tests are not the cost a review round pays: nine hundred lines of them
    # beside fifty lines of source is a small change.
    ("50\t0\tsrc/a.py\n" + "\n".join(
        f"100\t0\tpackages/kernel/tests/test_{n}.py" for n in range(9)), True),
    ("-\t-\timage.png\n3\t1\tcode.py", True),          # binary counts as a file
    ("\n".join(f"1\t1\tf{n}.py" for n in range(14)), True),   # exactly the limit
])
def test_a_task_too_large_to_finish_is_stopped_before_review(monkeypatch,
                                                             numstat, bounded):
    """Calibrated on outcomes, not taste. Non-test lines separate the tasks
    that landed from the ones that could not converge; total lines do not."""
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: (0, numstat, False))
    assert gates.size(cwd=Path("."), base_sha="x").passed is bounded


def test_an_unreadable_diff_is_unmeasured_not_oversized(monkeypatch):
    """A repository git cannot read has not shown the change is too large."""
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: (128, "not a repo", False))
    g = gates.size(cwd=Path("."), base_sha="x")
    assert g.passed is False and g.unmeasured is True


def test_the_driver_checks_size_before_it_asks_for_a_review():
    """Ordering is the point: a reviewer should not spend rounds discovering
    that a change is too large to converge on."""
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    run_task = source[source.index("def run_task("):source.index("def _ship(")]
    assert "gates.size(" in run_task, "size is never checked"
    assert run_task.index("gates.size(") < run_task.index("agents.review("), (
        "the review runs before the size check, so an oversized change still "
        "costs a review round")
    # And an oversized task is parked for a person to split, not silently failed.
    assert "park_oversized" in run_task


# ===================================== work the loop can actually finish
#
# The link to the control plane drops for long stretches — TCP connects and the
# SSH banner exchange times out. A task that must deploy or be verified in
# production cannot finish while that lasts, and starting one costs a full
# build before its deploy gate discovers the same thing.


def test_work_needing_the_host_is_skipped_while_the_host_is_unreachable(q):
    needs_host = q.add(title="deploys", brief="b", origin="human", paths=["infra/"],
                       priority=90, requires_deploy=True)
    repo_only = q.add(title="repository only", brief="b", origin="human", paths=["infra/"],
                      priority=50)

    taken = q.claim(owner="d", host_reachable=False)
    assert taken["id"] == repo_only, (
        "a task that cannot finish was started, and priority was allowed to "
        "override whether it could finish at all")

    q.move(taken["id"], State.QUEUED, reason="probe")
    assert q.claim(owner="d", host_reachable=True)["id"] == needs_host


def test_the_loop_stops_when_every_remaining_task_needs_an_unreachable_host(q):
    q.add(title="deploys", brief="b", origin="human", paths=["infra/"], requires_deploy=True)
    q.add(title="verifies", brief="b", origin="human", paths=["infra/"], requires_prod_check=True)
    assert q.claim(owner="d", host_reachable=False) is None

    source = Path(INFRA / "devloop" / "driver.py").read_text()
    loop = source[source.index("    def loop("):source.index("    def replenish(")]
    assert "host_reachable" in loop, "the loop never asks whether the host is up"
    assert loop.index("gates.host_reachable()") < loop.index("self.q.claim("), (
        "the host is checked after a task is claimed, so an unrunnable task is "
        "still started")
    assert "unreachable" in loop, (
        "the run ends without saying the host was the reason")


def test_an_unreachable_host_is_unmeasured_not_a_failure(monkeypatch):
    """It says nothing about the work.

    Recorded as unmeasured so a task is never requeued with a reason that
    blames a change for the network.
    """
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: (255, "timed out", True))
    g = gates.host_reachable()
    assert g.passed is False and g.unmeasured is True


# ============================================================ scope contract
#
# The failure this section exists for actually happened too. A task's scope
# lived in the prose of its brief — "only the repository" — and a builder that
# also rewrote the service, the schema and a second module was caught by a
# person reading the diff after three review rounds had been spent on it. The
# reports that followed said "scope held" for later tasks, and every one of
# those was somebody looking, not the loop refusing. These make it the loop.


@pytest.mark.parametrize("paths", [
    None, [], ["*"], ["**"], ["."], ["/"], ["./"], ["**/"], ["*/"],
    ["/etc/passwd"], ["../outside"], ["a/../b"], [""], ["   "],
])
def test_a_contract_that_bounds_nothing_is_refused(q, paths):
    """A task with no contract, or one that allows everything, cannot enter.

    An empty contract is the unenforced scope this gate replaced, wearing a
    field that says somebody checked. It is refused at the door rather than
    tolerated at the gate.
    """
    with pytest.raises(ValueError):
        q.add(title="t", brief="b", origin="human", paths=paths)


def test_a_contract_is_stored_as_declared(q):
    from devloop.queue import allowed_paths

    ident = q.add(title="t", brief="b", origin="human",
                  paths=["./a/b.py", "src/", "tests/test_*.py", "src/"])
    assert allowed_paths(q.get(ident)) == ["a/b.py", "src/", "tests/test_*.py"]


@pytest.mark.parametrize("path,pattern,inside", [
    ("src/a/b.py", "src/", True),
    ("src", "src/", False),
    ("srcs/a.py", "src/", False),
    ("src/a.py", "src/a.py", True),
    ("src/a.pyc", "src/a.py", False),
    ("tests/test_x.py", "tests/test_*.py", True),
    ("tests/deep/test_x.py", "tests/test_*.py", False),
    ("tests/deep/test_x.py", "tests/**/test_*.py", True),
    ("tests/deep/test_x.py", "tests/**", True),
])
def test_a_contract_entry_means_what_it_looks_like(path, pattern, inside):
    """Directory, exact file, glob — and `*` does not cross a directory."""
    assert gates.within(path, pattern) is inside


def _repo_with_a_task_branch(tmp_path, *, touching: list[str]):
    """A `main` and a task branch whose one commit changed `touching`."""
    import subprocess

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    for argv in (["git", "init", "-q", "-b", "main"],
                 ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"]):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    (repo / "src" / "app.py").write_text("x = 1\n")
    (repo / "src" / "keep.py").write_text("y = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True,
                   capture_output=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "checkout", "-qb", "task"], cwd=repo, check=True,
                   capture_output=True)
    for rel in touching:
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(target.read_text() + "z = 2\n" if target.exists()
                          else "z = 2\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "task", "--allow-empty"], cwd=repo,
                   check=True, capture_output=True)
    return repo, base


def test_the_scope_gate_reads_the_committed_diff_not_the_brief(tmp_path):
    """The evidence is four lists a person can check against git themselves."""
    repo, base = _repo_with_a_task_branch(
        tmp_path, touching=["src/app.py", "tests/test_app.py", "docs/x.md"])
    g = gates.scope(cwd=repo, base_sha=base, allowed=["src/", "tests/"])
    assert g.passed is False and g.unmeasured is False
    assert g.evidence == {
        "declared": ["src/", "tests/"],
        "changed": ["docs/x.md", "src/app.py", "tests/test_app.py"],
        "undeclared": ["docs/x.md"],
        "verdict": "out_of_scope",
    }
    assert "docs/x.md" in g.detail

    kept = gates.scope(cwd=repo, base_sha=base,
                       allowed=["src/", "tests/", "docs/*.md"])
    assert kept.passed is True
    assert kept.evidence["undeclared"] == [] and kept.evidence["verdict"] == "in_scope"


def test_a_file_moved_out_of_the_contract_is_a_write_outside_it(tmp_path):
    """Renames are not followed. A move is a deletion and a creation, and the
    creation is outside the contract; reporting it as 'src/keep.py, renamed'
    would hide exactly the write the gate exists to see."""
    import subprocess

    repo, base = _repo_with_a_task_branch(tmp_path, touching=[])
    (repo / "elsewhere").mkdir()
    subprocess.run(["git", "mv", "src/keep.py", "elsewhere/keep.py"], cwd=repo,
                   check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "move"], cwd=repo, check=True,
                   capture_output=True)
    g = gates.scope(cwd=repo, base_sha=base, allowed=["src/"])
    assert g.passed is False
    assert g.evidence["undeclared"] == ["elsewhere/keep.py"]


def test_an_unreadable_diff_is_unmeasured_not_in_scope(monkeypatch):
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: (128, "not a repo", False))
    g = gates.scope(cwd=Path("."), base_sha="x", allowed=["src/"])
    assert g.passed is False and g.unmeasured is True


def test_scope_is_a_required_gate_for_every_task():
    assert "scope" in gates.required({})
    assert gates.required({}).index("scope") < gates.required({}).index("review")


def test_a_head_no_scope_check_measured_can_never_land(q):
    """The landing gate asks the record, and a missing record is a refusal."""
    ident = q.add(title="t", brief="b", origin="human", paths=["src/"])
    q.move(ident, State.REVIEWING, reason="r", head_sha="abc")
    q.record_review(ident, round=1, sha="abc", verdict="clean", findings=0)
    assert q.review_was_clean(ident) is True
    assert q.scope_was_kept(ident) is False, (
        "a head nobody measured against the contract was allowed to land")


def test_a_head_measured_outside_its_contract_can_never_land(q):
    ident = q.add(title="t", brief="b", origin="human", paths=["src/"])
    q.move(ident, State.REVIEWING, reason="r", head_sha="abc")
    verdict = q.record_scope(ident, round=1, sha="abc", declared=["src/"],
                             changed=["src/a.py", "docs/x.md"],
                             undeclared=["docs/x.md"])
    assert verdict == "out_of_scope"
    assert q.scope_was_kept(ident) is False
    # The record keeps all four facts, decoded, in the order they happened.
    [check] = q.scope_checks(ident)
    assert (check["declared"], check["changed"], check["undeclared"],
            check["verdict"]) == (["src/"], ["src/a.py", "docs/x.md"],
                                  ["docs/x.md"], "out_of_scope")


def test_a_verdict_is_derived_from_the_lists_never_asserted(q):
    """`record_scope` takes no verdict. A record naming an undeclared path
    cannot say in_scope, whatever its caller believed."""
    import inspect

    assert "verdict" not in inspect.signature(q.record_scope).parameters
    ident = q.add(title="t", brief="b", origin="human", paths=["src/"])
    q.move(ident, State.REVIEWING, reason="r", head_sha="abc")
    assert q.record_scope(ident, round=1, sha="abc", declared=["src/"],
                          changed=["src/a.py"], undeclared=[]) == "in_scope"
    assert q.scope_was_kept(ident) is True


def test_a_scope_check_on_an_older_head_does_not_cover_the_new_one(q):
    """Keyed on the sha, like the review: round one kept to its contract, round
    two did not, and it is round two that is about to land."""
    ident = q.add(title="t", brief="b", origin="human", paths=["src/"])
    q.move(ident, State.REVIEWING, reason="r1", head_sha="aaa")
    q.record_scope(ident, round=1, sha="aaa", declared=["src/"],
                   changed=["src/a.py"], undeclared=[])
    assert q.scope_was_kept(ident) is True
    q.move(ident, State.REVIEWING, reason="r2", head_sha="bbb")
    assert q.scope_was_kept(ident) is False


def test_landing_is_behind_the_scope_record_as_well_as_the_review():
    """Structural, like the review guard beside it: the squash-merge is
    unreachable without the recorded scope verdict for this head."""
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    ship = source[source.index("def _ship("):source.index("def _touched(")]
    guard = ship.index("scope_was_kept")
    merge = ship.index('"merge", "--squash"')
    assert guard < merge, "the squash-merge is not behind the scope check"
    assert "CONTESTED" in ship[guard:merge]


def test_the_driver_measures_scope_on_the_commit_before_it_asks_for_a_review():
    """After the commit, so the record names an immutable sha; before the
    review, so no round is spent on work the task was not allowed to do."""
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    run_task = source[source.index("def run_task("):source.index("def _ship(")]
    commit = run_task.index("self._commit(task, round_no)")
    scope = run_task.index("gates.scope(")
    record = run_task.index("record_scope(")
    review = run_task.index("agents.review(")
    assert commit < scope < record < review, (
        "scope is not measured on the committed unit before the review")
    assert "CONTESTED" in run_task[scope:review]
    assert "park_out_of_scope" in run_task[scope:review]


def test_a_task_without_a_contract_is_blocked_before_the_builder_runs(q, tmp_path,
                                                                     monkeypatch):
    """A row from before the column has NULL there. It is not run against a
    contract the driver invents; it is parked for a person to declare one."""
    from devloop import driver as drv

    ident = q.add(title="legacy", brief="b", origin="human", paths=["src/"])
    with q._write() as db:
        db.execute("UPDATE tasks SET paths = NULL WHERE id = ?", (ident,))
    task = q.claim(owner="test")

    def never(*a, **k):
        raise AssertionError("the builder ran with no contract")

    monkeypatch.setattr(drv.agents, "build", never)
    monkeypatch.setattr(drv, "_git", never)
    driver = drv.Driver(q, drv.Limits(), repo=tmp_path)
    assert driver.run_task(task) == State.BLOCKED
    assert q.get(ident)["state"] == State.BLOCKED
    assert any("allowed-path contract" in t["reason"] for t in q.transitions(ident))


def test_a_builder_that_leaves_its_contract_is_contested_unreviewed(tmp_path,
                                                                    monkeypatch):
    """End to end on a real repository. The builder writes one file inside the
    contract and one outside it; the driver commits, measures, records, parks —
    and never asks for a review, never lands, and leaves `main` untouched."""
    import subprocess

    from devloop import driver as drv

    repo, base = _repo_with_a_task_branch(tmp_path, touching=[])
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    (repo / ".qevik" / "devloop").mkdir(parents=True)
    (repo / ".qevik" / "DECISION_QUEUE.md").write_text("# Decisions\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "ledgers"], cwd=repo, check=True,
                   capture_output=True)
    main_before = subprocess.run(["git", "rev-parse", "main"], cwd=repo,
                                 capture_output=True, text=True).stdout.strip()

    q = Queue(tmp_path / "s.db")
    ident = q.add(title="in src only", brief="b", origin="human",
                  paths=["src/"])
    task = q.claim(owner="test")

    def build(task, *, cwd, **_):
        (cwd / "src" / "app.py").write_text("x = 2\n")
        (cwd / "docs").mkdir()
        (cwd / "docs" / "drift.md").write_text("not allowed\n")
        return drv.agents.Outcome(ok=True, exit_code=0, output="done")

    monkeypatch.setattr(drv.agents, "build", build)
    monkeypatch.setattr(drv.gates, "tests",
                        lambda **k: gates.Gate("tests", True, "1 passed"))

    def never_review(**_):
        raise AssertionError("an out-of-scope diff was sent for review")

    monkeypatch.setattr(drv.agents, "review", never_review)
    driver = drv.Driver(q, drv.Limits(), repo=repo)

    assert driver.run_task(task) == State.CONTESTED

    row = q.get(ident)
    assert row["state"] == State.CONTESTED
    [check] = q.scope_checks(ident)
    assert check["sha"] == row["head_sha"]
    assert check["undeclared"] == ["docs/drift.md"]
    assert check["changed"] == ["docs/drift.md", "src/app.py"]
    assert check["verdict"] == "out_of_scope"
    assert q.scope_was_kept(ident) is False
    assert q.review_was_clean(ident) is False, "no review should exist"
    assert any(t["reason"].startswith("out of scope:")
               for t in q.transitions(ident))
    main_after = subprocess.run(["git", "rev-parse", "main"], cwd=repo,
                                capture_output=True, text=True).stdout.strip()
    assert main_after == main_before, "an out-of-scope diff reached main"
    assert subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                          capture_output=True, text=True).stdout.strip() == "main"
    ledger = (repo / ".qevik" / "DECISION_QUEUE.md").read_text()
    assert f"<!-- devloop:scope:{ident} -->" in ledger
    assert "docs/drift.md" in ledger and "src/" in ledger


def test_a_builder_inside_its_contract_reaches_the_review(tmp_path, monkeypatch):
    """Negative control for the test above: the same driver, a builder that
    stays inside the contract, and the review is asked for."""
    import subprocess

    from devloop import driver as drv

    repo, base = _repo_with_a_task_branch(tmp_path, touching=[])
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    (repo / ".qevik" / "devloop").mkdir(parents=True)

    q = Queue(tmp_path / "s.db")
    ident = q.add(title="in src only", brief="b", origin="human",
                  paths=["src/"])
    task = q.claim(owner="test")

    def build(task, *, cwd, **_):
        (cwd / "src" / "app.py").write_text("x = 2\n")
        return drv.agents.Outcome(ok=True, exit_code=0, output="done")

    monkeypatch.setattr(drv.agents, "build", build)
    monkeypatch.setattr(drv.gates, "tests",
                        lambda **k: gates.Gate("tests", True, "1 passed"))
    asked = []

    def review(**k):
        asked.append(k["base_sha"])
        return drv.agents.Outcome(ok=False, exit_code=1, output="",
                                  infrastructure_failure=True,
                                  detail="stop here")

    monkeypatch.setattr(drv.agents, "review", review)
    driver = drv.Driver(q, drv.Limits(), repo=repo)
    driver.run_task(task)

    assert asked == [base], "an in-scope diff was not sent for review"
    [check] = q.scope_checks(ident)
    assert check["verdict"] == "in_scope" and check["undeclared"] == []
    assert q.scope_was_kept(ident) is True


def test_the_builder_is_shown_its_contract_but_is_not_the_enforcement():
    """The prompt lists the paths as a courtesy. The enforcement is the gate,
    which reads the diff whether or not the builder read the prompt."""
    task = {"title": "t", "brief": "b", "paths": '["src/", "tests/"]'}
    prompt = agents.builder_prompt(task)
    assert "  - src/" in prompt and "  - tests/" in prompt
    assert "fails the task structurally" in prompt
    source = Path(INFRA / "devloop" / "gates.py").read_text()
    scope = source[source.index("def scope("):source.index("def clean_tree(")]
    assert "brief" not in scope.replace('"only the repository" is an instruction to the builder', "") \
        .replace("read the brief", "").replace("brief that says", "")
    assert '"git", "diff", "--name-only", "--no-renames"' in scope


def _allowed_tools_in(argv: list[str]) -> list[str]:
    """The rules `--allowedTools` was given. It is variadic, so the rules run
    until the next flag."""
    assert "--allowedTools" in argv, (
        "no allow-list: `--permission-mode acceptEdits` auto-accepts file edits "
        "only, so every Bash call the agent makes is refused and it cannot run "
        "the suite it is told to run")
    rules: list[str] = []
    for token in argv[argv.index("--allowedTools") + 1:]:
        if token.startswith("--"):
            break
        rules.append(token)
    return rules


def test_the_builder_and_the_fixer_may_run_the_suite_and_nothing_else(monkeypatch):
    """Both editing agents get one shell command: the test suite.

    Before this, both ran under `acceptEdits` with no allow-list, which grants
    edits and refuses every Bash call — so the builder was told "run the
    relevant tests yourself" in a session where it could not. It was paid for:
    the fixer on t-8bdaf8c290ca edited blind for three rounds against tests it
    could never execute.
    """
    seen: list[list[str]] = []

    def capture(argv, **_):
        seen.append(list(argv))
        return 0, '{"is_error": false, "subtype": "success"}', False

    monkeypatch.setattr(agents, "_run", capture)
    task = {"title": "t", "brief": "b", "paths": '["infra/devloop/"]'}
    agents.build(task, cwd=Path("."), max_turns=1, timeout=10)
    agents.fix(task, [{"severity": "blocking", "file": "a.py:1", "claim": "c",
                       "why_it_matters": "w", "failure_scenario": "f"}],
               cwd=Path("."), max_turns=1, timeout=10)
    assert len(seen) == 2, "the builder and the fixer were not both invoked"

    for argv in seen:
        assert _allowed_tools_in(argv) == ["Bash(python3 -m pytest:*)"], (
            "the allow-list is the whole boundary; anything beyond the pytest "
            "rule is a command the agent can run that nobody decided to give it")

        # An allow-list next to a bypass is not a boundary, it is decoration.
        assert "--dangerously-skip-permissions" not in argv
        assert "bypassPermissions" not in argv
        assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"

        # No second rule quietly grants another tool. This is not a claim that
        # the agent cannot reach these — pytest runs repository code, so it
        # can — only that nothing here hands it one in a single step.
        joined = " ".join(argv)
        for reachable in ("git", "ssh", "curl", "docker", "scp", "rsync"):
            assert f"Bash({reachable}" not in joined

    # The rule is a prefix, and this is the prefix the gate itself runs — so an
    # agent can execute the command that is about to judge it. Read from
    # `gates.py` rather than restated, because the two drifting apart is the
    # failure this asserts against.
    gate = Path(INFRA / "devloop" / "gates.py").read_text()
    assert '["python3", "-m", "pytest"' in gate

    # And the builder is told what it may run, rather than left to discover the
    # refusal by spending a turn on it.
    prompt = agents.builder_prompt({"title": "t", "brief": "b", "paths": "[]"})
    assert "python3 -m pytest" in prompt


def test_the_agents_may_run_only_what_the_host_already_runs_for_them(monkeypatch):
    """The allow-list grants no execution the loop was not already performing.

    A reviewer read the pytest rule as a sandbox and asked for pytest to be
    containerised, on the ground that it grants arbitrary host-side Python.
    The first half is right and the second is not: `gates.tests` runs
    `python3 -m pytest packages/kernel/tests/` on this host, in the builder's
    own working tree, over whatever it just wrote — every round, before
    `gates.scope` has looked at a path. A `conftest.py` the builder wrote
    executes there with or without the allow-list.

    So the invariant that has to hold is not "the agent cannot execute code" —
    it can, and the loop makes it happen anyway — but that the agent is
    permitted *only the command the host already runs on its behalf*. Widening
    the rule to `Bash(python3:*)` or `Bash(bash:*)` would break that and this
    test fails if anyone does.
    """
    ran: list[list[str]] = []

    def capture(argv, **_):
        ran.append(list(argv))
        return 0, "1 passed", False

    monkeypatch.setattr(gates, "_sh", capture)
    gates.tests(cwd=Path("."))
    [gate_argv] = ran

    assert len(agents.ALLOWED_TOOLS) == 1, (
        "one rule, so that what the agent may run stays readable in one line")
    [rule] = agents.ALLOWED_TOOLS
    assert rule.startswith("Bash(") and rule.endswith(":*)")
    permitted = rule[len("Bash("):-len(":*)")]

    # A bare interpreter is not a bounded command, it is every command — and
    # it would still satisfy the prefix check below, because the gate's own
    # argv starts with `python3`.
    assert len(permitted.split()) > 1 and permitted not in (
        "bash", "sh", "zsh", "env", "python3", "python", "uv", "npx",
        "make"), (
        f"{permitted!r} permits anything that interpreter can be handed")

    # And it is a prefix of the exact argv the gate itself runs, read by
    # calling the gate rather than by restating it here — the two drifting
    # apart is what this asserts against.
    assert " ".join(gate_argv).startswith(permitted + " "), (
        f"the agent may run {permitted!r}, which is not what the gate runs "
        f"({' '.join(gate_argv)!r}) — the allow-list has stopped being a "
        f"subset of what the host does for it anyway")

    # The gate runs it on the builder's own tree, in the same round, before the
    # scope gate. That ordering is why the permission adds no exposure.
    run_task = Path(INFRA / "devloop" / "driver.py").read_text()
    run_task = run_task[run_task.index("def run_task("):]
    executed = run_task.index("gates.tests(cwd=self.repo")
    assert executed < run_task.index("gates.scope(cwd=self.repo"), (
        "the suite no longer runs before the scope gate; the builder's code is "
        "not executed on the host until after its paths are checked, and the "
        "note on ALLOWED_TOOLS needs rewriting rather than this assertion "
        "relaxing")

    # Finally, the note says what the rule is not. It was written claiming
    # "nothing here reaches outside the working tree", which pytest does not
    # give and nobody should rely on.
    source = Path(INFRA / "devloop" / "agents.py").read_text()
    note = source[:source.index("ALLOWED_TOOLS: tuple")]
    note = note[note.index("#: The only shell command"):]
    assert "conftest" in note and "not containment" in note, (
        "the allow-list must be documented as scope rather than as a sandbox")


def test_every_production_rule_declares_where_its_work_may_go():
    from devloop import inspection

    for rule in inspection.RULES:
        assert rule.get("paths"), f"{rule['key']} enqueues unbounded work"
        # And each is a real contract, not something `add` will refuse later.
        from devloop.queue import contract
        assert contract(list(rule["paths"]))


def test_a_database_from_before_the_contract_gains_the_column(tmp_path):
    """Opening an old database adds the column; the old rows keep NULL, which
    the driver reads as 'no contract' and refuses to run."""
    import sqlite3

    from devloop.queue import allowed_paths

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, brief TEXT NOT NULL,
            state TEXT NOT NULL, origin TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 50,
            evidence TEXT NOT NULL DEFAULT '{}',
            requires_deploy INTEGER NOT NULL DEFAULT 0,
            requires_prod_check INTEGER NOT NULL DEFAULT 0,
            base_sha TEXT, head_sha TEXT,
            review_rounds INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            blocked_by TEXT, resume_stage TEXT, resume_sha TEXT,
            driver_run_id TEXT, lease_owner TEXT, lease_expires_at TEXT,
            detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO tasks (id, title, brief, state, origin, created_at, updated_at)
        VALUES ('t-old', 'legacy', 'b', 'QUEUED', 'human', 'x', 'x');
    """)
    old.commit(); old.close()

    q = Queue(path)
    legacy = q.get("t-old")
    assert legacy["paths"] is None
    assert allowed_paths(legacy) == []
    # The other column added after the fact, and it defaults the other way: a
    # row nobody declared deploy-only is not one, so an old task whose builder
    # writes nothing keeps failing rather than deploying unchanged code.
    from devloop.queue import declares_deploy_only

    assert legacy["deploy_only"] == 0
    assert declares_deploy_only(legacy) is False
    # A new row on the same database carries its contract.
    fresh = q.add(title="new", brief="b", origin="human", paths=["src/"])
    assert allowed_paths(q.get(fresh)) == ["src/"]
    # And a person can set one on the legacy row, with a transition saying so.
    q.declare_paths("t-old", ["infra/devloop/"], actor="ayoub", reason="from the brief")
    assert allowed_paths(q.get("t-old")) == ["infra/devloop/"]
    assert any("allowed-path contract set to" in t["reason"]
               and t["actor"] == "ayoub" for t in q.transitions("t-old"))


def test_a_contract_is_not_changed_under_a_running_task(q):
    ident = q.add(title="t", brief="b", origin="human", paths=["src/"])
    q.claim(owner="d")
    with pytest.raises(ValueError):
        q.declare_paths(ident, ["src/", "docs/"], actor="ayoub")


# ================================== a task whose whole content is the deploy
#
# t-4f02ee7a36c0 — "Deploy and verify the unreviewed-drafts surface",
# requires_deploy=1, requires_prod_check=1 — could not pass through the loop.
# The builder is told never to deploy and to change nothing it cannot do inside
# its paths, so it changed nothing, and the `changed` gate ended the task
# FAILED "nothing changed". Nothing was deployed and nothing was verified.
#
# Every DONE task before it declared requires_deploy=0, which is why the hole
# stayed invisible: the deploy gates were reachable only after a builder's diff
# had been committed, scope-checked, reviewed and squash-merged — and a deploy
# of what `main` already carries has no diff to merge.


def _repo_on_main(tmp_path):
    """A repository with one commit on `main` and nothing uncommitted."""
    import subprocess

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    for argv in (["git", "init", "-q", "-b", "main"],
                 ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"]):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    (repo / "src" / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "what main already carries"],
                   cwd=repo, check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                         capture_output=True, text=True).stdout.strip()
    return repo, sha


def _builder_that_changes_nothing(monkeypatch, drv):
    """The builder as it actually behaves on a deploy-only task.

    It is told never to deploy and to change nothing if the task cannot be done
    inside its paths, so on a task whose content is "put what `main` already
    carries on the host" it correctly leaves the tree exactly as it found it.
    """
    monkeypatch.setattr(drv.agents, "build", lambda *a, **k: drv.agents.Outcome(
        ok=True, exit_code=0,
        output="Nothing to change: main already carries this surface."))


def _deploy_only_run(tmp_path, monkeypatch, *, deploys=True, probes=True,
                     requires_deploy=True, deploy_only=True):
    """Drive the driver over a stubbed builder that changes nothing.

    Returns everything the assertions need: the queue, the task id, the `main`
    sha that was there before the run, the terminal state, and the list the
    stubbed gates appended their own names to as they were called.
    """
    from devloop import driver as drv

    repo, main_sha = _repo_on_main(tmp_path)
    q = Queue(tmp_path / "s.db")
    ident = q.add(title="deploy and verify the unreviewed-drafts surface",
                  brief="deploy what main already carries, then verify it",
                  origin="human", paths=["infra/devloop/"],
                  requires_deploy=requires_deploy, requires_prod_check=True,
                  deploy_only=deploy_only,
                  evidence={"production_probe": "print('PROVED')"})
    task = q.claim(owner="test")
    _builder_that_changes_nothing(monkeypatch, drv)

    called: list[str] = []

    def suite(**kwargs):
        called.append("tests" if not kwargs.get("selector") else "narrowed")
        return gates.Gate("tests", True, "412 passed in 600s")

    def deployed(**_):
        called.append("deployed")
        return gates.Gate("deployed", deploys,
                          "control plane answered" if deploys
                          else "deploy_control.sh exited 2")

    def in_production(**kwargs):
        called.append("in_production")
        assert kwargs["probe"] == "print('PROVED')"
        return gates.Gate("in_production", probes,
                          "PROVED" if probes else "NOT PROVED")

    def never_review(**_):
        raise AssertionError("a deploy with no diff was sent for review")

    monkeypatch.setattr(drv.gates, "tests", suite)
    monkeypatch.setattr(drv.gates, "deployed", deployed)
    monkeypatch.setattr(drv.gates, "in_production", in_production)
    monkeypatch.setattr(drv.agents, "review", never_review)

    driver = drv.Driver(q, drv.Limits(), repo=repo)
    return q, ident, main_sha, driver.run_task(task), called, repo


def test_a_deploy_only_task_runs_the_gates_without_inventing_a_diff(tmp_path,
                                                                    monkeypatch):
    """The full suite, the deploy and the probe, in that order, on `main`.

    Not a second deploy mechanism: the same three gates the merged path runs,
    in the same order, from the same `_finish`. What replaces the diff is the
    record of which sha went to the host.
    """
    q, ident, main_sha, outcome, called, repo = _deploy_only_run(tmp_path,
                                                                 monkeypatch)
    assert outcome == State.DONE, (
        "a task that only deploys still cannot pass through the loop")
    assert called == ["tests", "deployed", "in_production"], (
        f"the gates ran as {called}; a narrowed suite, a skipped deploy or a "
        "probe before the deploy are each a weaker gate than the merged path")

    row = q.get(ident)
    assert row["state"] == State.DONE
    assert row["head_sha"] == main_sha, (
        "the sha that was deployed was not written down, so nobody can say "
        "afterwards what is on the host")

    reasons = {t["to_state"]: t["reason"] for t in q.transitions(ident)}
    assert main_sha in reasons[State.DONE], (
        "the DONE transition does not name the deployed sha")
    assert main_sha in reasons[State.GATING], (
        "nothing records which sha this task decided to deploy")
    assert "412 passed" in reasons[State.DEPLOYING], (
        "the deploy transition does not carry the suite's own detail")
    assert main_sha[:12] in reasons[State.DEPLOYING]
    assert main_sha[:12] in reasons[State.VERIFYING]

    # No review and no scope check, because there is nothing to review and
    # nothing to measure — and, so that this can never be mistaken for a head
    # that passed them, the landing gates still refuse it.
    assert q.scope_checks(ident) == []
    assert q.scope_was_kept(ident) is False
    assert q.review_was_clean(ident) is False

    # And `main` is where it was left: the deploy script copies the working
    # tree and refuses to run from anywhere else.
    import subprocess

    assert subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                          capture_output=True, text=True).stdout.strip() == "main"
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip() == main_sha
    assert f"devloop/{ident}" not in subprocess.run(
        ["git", "branch"], cwd=repo, capture_output=True, text=True).stdout


@pytest.mark.parametrize("deploys,probes,ran", [
    (False, True, ["tests", "deployed"]),
    (True, False, ["tests", "deployed", "in_production"]),
])
def test_a_deploy_only_task_still_fails_when_a_gate_refuses(tmp_path, monkeypatch,
                                                            deploys, probes, ran):
    """No diff is not a licence to skip anything.

    A deploy that exits non-zero, or a probe production disagrees with, ends
    the task FAILED exactly as it would after a merge — and a refused deploy
    never reaches the probe.
    """
    q, ident, main_sha, outcome, called, _ = _deploy_only_run(
        tmp_path, monkeypatch, deploys=deploys, probes=probes)
    assert outcome == State.FAILED
    assert q.get(ident)["state"] == State.FAILED
    assert called == ran
    reasons = " ".join(t["reason"] for t in q.transitions(ident))
    assert main_sha[:12] in reasons, "the failure does not name the sha it tried"


def test_a_task_that_does_not_deploy_and_changes_nothing_still_fails(tmp_path,
                                                                     monkeypatch):
    """The gate that catches the commonest silent failure keeps catching it.

    An agent that reports success having written nothing is still a failure —
    the deploy-only declaration is what makes an empty diff legitimate, and a
    task that declares nothing of the kind has simply not been carried out.
    """
    q, ident, _, outcome, called, _ = _deploy_only_run(tmp_path, monkeypatch,
                                                       requires_deploy=False,
                                                       deploy_only=False)
    assert outcome == State.FAILED
    assert called == [], "a task that declares no deploy reached the deploy gates"
    reasons = " ".join(t["reason"] for t in q.transitions(ident))
    assert "nothing was changed" in reasons
    assert "main already carries this surface" in reasons, (
        "the builder's own words were not kept with the failure")


def test_a_build_and_deploy_task_whose_builder_did_nothing_still_fails(tmp_path,
                                                                       monkeypatch):
    """The finding this declaration exists for, as a test.

    `requires_deploy=1` is not a statement that a task has nothing to build.
    Every task that must build something and *then* deploy it carries it —
    including every task production inspection enqueues, which is all of them.
    So a builder that silently succeeded without doing its work leaves exactly
    what a genuine deploy-only task leaves: an empty diff on a branch identical
    to `main`.

    Classifying on the flag alone would deploy unchanged code, skip the review,
    and write DONE against work nobody did. The task must say so itself; when
    it has not, the empty diff stays the failure it was, and the failure names
    the declaration so a person can correct it.
    """
    q, ident, _, outcome, called, _ = _deploy_only_run(tmp_path, monkeypatch,
                                                       requires_deploy=True,
                                                       deploy_only=False)
    assert outcome == State.FAILED, (
        "a build-and-deploy task whose builder wrote nothing was accepted")
    assert called == [], (
        f"the gates ran as {called}; unchanged code was deployed for a task "
        "whose work was never done")
    row = q.get(ident)
    assert row["state"] == State.FAILED
    assert not row["head_sha"], "an undone task recorded a deployed sha"

    reasons = " ".join(t["reason"] for t in q.transitions(ident))
    assert "nothing was changed" in reasons
    assert "declare-deploy-only" in reasons, (
        "the failure does not say how a genuine deploy-only task declares "
        "itself, so the one legitimate case has no route out")
    assert State.DONE not in {t["to_state"] for t in q.transitions(ident)}


def test_a_deploy_only_task_that_did_build_something_is_still_reviewed(tmp_path,
                                                                       monkeypatch):
    """Negative control, and the boundary of the whole change.

    Declaring a task deploy-only does not buy it a way past the review. The
    moment the builder writes anything, the task takes today's path — commit,
    scope, review — and nothing is deployed until that has finished. The
    declaration says what the task is *for*; the diff still decides which path
    it takes, and the two disagreeing resolves towards the review.
    """
    from devloop import driver as drv

    repo, main_sha = _repo_on_main(tmp_path)
    q = Queue(tmp_path / "s.db")
    ident = q.add(title="deploys, and builds", brief="b", origin="human",
                  paths=["src/"], requires_deploy=True, deploy_only=True)
    task = q.claim(owner="test")

    def build(task, *, cwd, **_):
        (cwd / "src" / "app.py").write_text("x = 2\n")
        return drv.agents.Outcome(ok=True, exit_code=0, output="done")

    asked: list[str] = []

    def review(**k):
        asked.append(k["base_sha"])
        return drv.agents.Outcome(ok=False, exit_code=1, output="",
                                  infrastructure_failure=True, detail="stop here")

    def never_deploy(**_):
        raise AssertionError("an unreviewed diff was deployed")

    monkeypatch.setattr(drv.agents, "build", build)
    monkeypatch.setattr(drv.agents, "review", review)
    monkeypatch.setattr(drv.gates, "deployed", never_deploy)
    monkeypatch.setattr(drv.gates, "tests",
                        lambda **k: gates.Gate("tests", True, "1 passed"))

    drv.Driver(q, drv.Limits(), repo=repo).run_task(task)
    assert asked == [main_sha], "a deploy-only task skipped the review it needed"
    [check] = q.scope_checks(ident)
    assert check["verdict"] == "in_scope"


def test_the_deploy_without_a_review_is_refused_when_anything_is_pending(tmp_path,
                                                                        monkeypatch):
    """Structural: the guard lives in the code that deploys.

    `_deploy_only` is only reachable today from a measured-empty diff on a
    branch identical to `main`. That is a property of the caller, and a second
    caller would make it a property of nobody — so the method asks git itself,
    and refuses rather than deploying work no reviewer has seen.
    """
    from devloop import driver as drv

    repo, main_sha = _repo_on_main(tmp_path)
    q = Queue(tmp_path / "s.db")
    ident = q.add(title="t", brief="b", origin="human", paths=["src/"],
                  requires_deploy=True, deploy_only=True)
    q.claim(owner="test")
    (repo / "src" / "unreviewed.py").write_text("nobody has seen this\n")

    def never_deploy(**_):
        raise AssertionError("uncommitted work was deployed without a review")

    monkeypatch.setattr(drv.gates, "deployed", never_deploy)
    driver = drv.Driver(q, drv.Limits(), repo=repo)
    assert driver._deploy_only(q.get(ident), 0.0) == State.CONTESTED
    assert any("refused to deploy" in t["reason"] for t in q.transitions(ident))


def test_the_deploy_without_a_review_is_refused_when_nobody_declared_it(tmp_path,
                                                                        monkeypatch):
    """The same structural guard, over the classification itself.

    The caller decides which tasks come here, and today it asks the row. A
    second caller — or an edit that widened the condition back to
    `requires_deploy` — would put an ordinary build-and-deploy task on the one
    path that deploys without a review. So the method asks the row again, and a
    task that never declared its content to be the deploy is refused where the
    deploy actually happens.
    """
    from devloop import driver as drv

    repo, _ = _repo_on_main(tmp_path)
    q = Queue(tmp_path / "s.db")
    ident = q.add(title="builds, then deploys", brief="b", origin="human",
                  paths=["src/"], requires_deploy=True)
    q.claim(owner="test")

    def never_deploy(**_):
        raise AssertionError("an undeclared task was deployed without a review")

    monkeypatch.setattr(drv.gates, "deployed", never_deploy)
    monkeypatch.setattr(drv.gates, "tests",
                        lambda **k: gates.Gate("tests", True, "1 passed"))
    driver = drv.Driver(q, drv.Limits(), repo=repo)
    assert driver._deploy_only(q.get(ident), 0.0) == State.FAILED
    assert any("does not declare" in t["reason"] for t in q.transitions(ident))


def test_both_ways_to_a_deploy_run_the_same_gates_in_the_same_order():
    """One deploy mechanism, not two.

    The reviewed-and-merged path and the deploy-only path both end in
    `_finish`, so a gate cannot be added to one and forgotten in the other.
    """
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    ship = source[source.index("def _ship("):source.index("def _deploy_only(")]
    deploy_only = source[source.index("def _deploy_only("):source.index("def _finish(")]
    finish = source[source.index("def _finish("):source.index("def _commit(")]

    assert "self._finish(" in ship and "self._finish(" in deploy_only, (
        "a deploy path bypasses the shared gates")
    for other in ("gates.deployed(", "gates.in_production("):
        assert other not in ship and other not in deploy_only, (
            f"{other} is called outside `_finish`; there are two deploy "
            "mechanisms now, and only one of them is tested")

    # The whole suite, then the deploy, then the probe. A narrowed run is a
    # real gate for a narrow change and is not enough to put code on a host.
    assert "gates.tests(cwd=self.repo)" in finish
    assert (finish.index("gates.tests(cwd=self.repo)")
            < finish.index("gates.deployed(")
            < finish.index("gates.in_production(")), (
        "the deploy gates do not run in the order the loop depends on")

    # And the deploy-only path neither reviews nor merges: there is nothing to
    # review, and a merge of nothing would be a commit nobody asked for.
    for forbidden in ("agents.review(", '"merge"', "gates.scope("):
        assert forbidden not in deploy_only, (
            f"the deploy-only path calls {forbidden}")


# ------------------------------------ the declaration that classifies a task


def test_a_deploy_only_task_is_declared_and_implies_the_deploy(q):
    """It is a statement about the task, made by whoever enqueued it.

    And it implies `requires_deploy`, because a deploy-only task that does not
    deploy would have nothing left to do — the flag exists to say the deploy is
    the whole of the work.
    """
    from devloop.queue import declares_deploy_only

    only = q.get(q.add(title="deploy what main carries", brief="b",
                       origin="human", paths=["infra/"], deploy_only=True))
    assert only["deploy_only"] == 1
    assert only["requires_deploy"] == 1
    assert declares_deploy_only(only) is True

    # The two tasks it must be distinguishable from, and neither is.
    builds = q.get(q.add(title="build it, then deploy it", brief="b",
                         origin="human", paths=["infra/"],
                         requires_deploy=True))
    assert declares_deploy_only(builds) is False
    plain = q.get(q.add(title="build it", brief="b", origin="human",
                        paths=["infra/"]))
    assert declares_deploy_only(plain) is False


def test_a_row_that_predates_the_flag_can_be_declared_deploy_only(q):
    """t-4f02ee7a36c0's own route out, and a person makes it.

    The task that motivated the whole deploy-without-a-diff path was enqueued
    before the flag existed. Without a way to declare it afterwards the fix
    would not reach the task it was written for — so this is the counterpart of
    `declare-paths`, and it records who decided, like that one does.
    """
    from devloop.queue import declares_deploy_only

    ident = q.add(title="deploy and verify the unreviewed-drafts surface",
                  brief="b", origin="human", paths=["infra/devloop/"],
                  requires_deploy=True)
    assert declares_deploy_only(q.get(ident)) is False

    q.declare_deploy_only(ident, actor="ayoub", reason="main already has it")
    assert declares_deploy_only(q.get(ident)) is True
    assert any("declared deploy-only" in t["reason"] and t["actor"] == "ayoub"
               for t in q.transitions(ident)), (
        "nothing records who decided this task builds nothing")

    # And withdrawn again, because a flag set by mistake must be removable —
    # it is the one thing standing between an empty diff and a deploy. The
    # deploy itself stays: the task still has to reach the host, it simply has
    # to build something first.
    q.declare_deploy_only(ident, actor="ayoub", deploy_only=False)
    assert declares_deploy_only(q.get(ident)) is False
    assert q.get(ident)["requires_deploy"] == 1


def test_a_task_is_not_reclassified_while_the_driver_is_deciding(q):
    """Not under a running task, for the same reason a contract is not.

    The driver reads this field to choose between deploying `main` and failing
    the task, and a field that changes mid-run makes that choice unattributable.
    """
    ident = q.add(title="t", brief="b", origin="human", paths=["src/"],
                  requires_deploy=True)
    q.claim(owner="d")
    with pytest.raises(ValueError):
        q.declare_deploy_only(ident, actor="ayoub")
    assert q.get(ident)["deploy_only"] == 0


def test_the_cli_can_declare_a_deploy_only_task_both_ways(tmp_path, monkeypatch):
    """The declaration has to be reachable, or the one legitimate case is stuck.

    A person is the only one who can say a task's whole content is the deploy,
    so there must be a way for them to say it — at enqueue time, and afterwards
    on a row that predates the flag.
    """
    from devloop import driver as drv
    from devloop.queue import declares_deploy_only

    monkeypatch.setattr(drv, "REPO", tmp_path)
    assert drv.main(["enqueue", "--title", "deploy what main carries",
                     "--brief", "b", "--path", "infra/devloop/",
                     "--deploy-only"]) == 0
    assert drv.main(["enqueue", "--title", "build it, then deploy it",
                     "--brief", "b", "--path", "infra/devloop/",
                     "--deploy"]) == 0

    q = Queue(tmp_path / ".qevik" / "devloop" / "state.db")
    only, builds = sorted(q.tasks(), key=lambda t: t["title"])[::-1]
    assert declares_deploy_only(only) is True
    assert declares_deploy_only(builds) is False, (
        "--deploy alone declared a task deploy-only")

    assert drv.main(["declare-deploy-only", builds["id"], "--actor", "ayoub",
                     "--reason", "main already has it"]) == 0
    assert declares_deploy_only(q.get(builds["id"])) is True
    assert drv.main(["declare-deploy-only", builds["id"], "--no",
                     "--actor", "ayoub"]) == 0
    assert declares_deploy_only(q.get(builds["id"])) is False


def test_the_classification_reads_the_declaration_and_not_the_deploy_flag():
    """Structural, because the difference is invisible at the call site.

    `requires_deploy` and `deploy_only` are one word apart and mean opposite
    things here: the first is carried by every task that must build something
    and then deploy it, and reading it as the second is what would deploy
    unchanged code for work that was never done. The condition guarding the
    bypass may only ask the declaration.
    """
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    run_task = source[source.index("def run_task("):source.index("def _ship(")]
    span = run_task[run_task.index("if not diff.passed:"):
                    run_task.index("self._deploy_only(")]
    # The code only. Both names are discussed at length in the comments there,
    # and a test that read those would be about the prose.
    bypass = "\n".join(line for line in span.splitlines()
                       if not line.strip().startswith("#"))
    assert "declares_deploy_only(task)" in bypass
    assert "requires_deploy" not in bypass and "gates.required(" not in bypass, (
        "the deploy-without-a-review path is chosen by a flag that ordinary "
        "build-and-deploy tasks also carry")


# ------------------------------ a repair reaches the task it was made for
#
# Classifying a task and making it runnable are two different things, and the
# task the deploy-only declaration was written for needed both: t-4f02ee7a36c0
# was already FAILED when the declaration arrived. `claim` reads the state, the
# declaration does not touch it, and nothing else moves a terminal row — so the
# declaration landed on a task nothing would ever pick up again.


def test_a_declared_task_that_already_failed_can_actually_run_again(q):
    """The legacy scenario end to end, on the queue that has to serve it.

    The declaration is a statement about the task and changes two flags. It is
    not a claim, and a FAILED row is not runnable: `claim` takes QUEUED rows
    and in-flight rows whose lease expired, and a terminal row is neither. So
    declaring the task is half the repair, and without the other half the fix
    never reaches the task it was written for.
    """
    from devloop.queue import declares_deploy_only

    ident = q.add(title="deploy and verify the unreviewed-drafts surface",
                  brief="b", origin="human", paths=["infra/devloop/"],
                  requires_deploy=True)
    q.claim(owner="the driver that failed it")
    q.move(ident, State.FAILED, reason="nothing was changed")

    # The declaration, made afterwards, exactly as a person would make it.
    q.declare_deploy_only(ident, actor="ayoub", reason="main already has it")
    assert declares_deploy_only(q.get(ident)) is True
    assert q.get(ident)["state"] == State.FAILED
    assert q.claim(owner="d") is None, (
        "declaring a failed task deploy-only was enough to make it runnable, "
        "so this test is no longer about anything")

    # And the half that makes the repair reach it.
    assert q.requeue(ident, actor="ayoub", reason="declared deploy-only") is True
    claimed = q.claim(owner="d")
    assert claimed is not None and claimed["id"] == ident, (
        "a task a person declared and requeued is still unreachable; the "
        "deploy-only path cannot run for the task it was written for")
    assert declares_deploy_only(claimed) is True, (
        "the requeue lost the declaration the driver reads to choose the "
        "deploy-only route")
    assert any(t["reason"].startswith("requeued from FAILED")
               and t["actor"] == "ayoub" for t in q.transitions(ident)), (
        "nothing records who put the task back, or what it was put back from")


def test_a_task_is_put_back_only_from_an_ending_a_person_can_undo(q):
    """Requeue is for a task that stopped, not for one that is running or done.

    DONE is the one refusal that matters: re-running a finished task would
    deploy again under a row that already says it completed, and the work
    somebody wants again is new work. The rest follow from the same rule —
    a claimed task is being worked on now, and a parked one is held at a human
    boundary that resolving the boundary clears.
    """
    ident = q.add(title="t", brief="b", origin="human", paths=["src/"])

    q.claim(owner="d")
    with pytest.raises(ValueError):
        q.requeue(ident, actor="ayoub")
    assert q.get(ident)["state"] == State.BUILDING

    q.park(ident, request_id="h-1", stage=State.BUILDING, sha="abc",
           reason="a credential")
    with pytest.raises(ValueError):
        q.requeue(ident, actor="ayoub")
    assert q.get(ident)["state"] == State.WAITING_FOR_HUMAN, (
        "a parked task was unparked by something other than its boundary "
        "clearing, so it will walk into the same wall every lap")

    q.move(ident, State.DONE, reason="finished")
    with pytest.raises(ValueError):
        q.requeue(ident, actor="ayoub")
    assert q.get(ident)["state"] == State.DONE, (
        "a completed task was queued to run again, which would deploy under a "
        "row that already says it finished")

    # CONTESTED and BLOCKED are undone like FAILED: the reason each of them
    # ended lives outside the loop, and a person deals with it there.
    for ending in (State.CONTESTED, State.BLOCKED, State.FAILED):
        q.move(ident, ending, reason="ended")
        assert q.requeue(ident, actor="ayoub") is True
        row = q.get(ident)
        assert row["state"] == State.QUEUED
        assert row["lease_owner"] is None and row["lease_expires_at"] is None, (
            "a queued task carries the lease of the driver that ended it")

    # Idempotent, and it says so rather than raising: a person who runs it
    # twice has not made a mistake.
    assert q.requeue(ident, actor="ayoub") is False
    assert len([t for t in q.transitions(ident)
                if t["reason"].startswith("requeued from")]) == 3

    with pytest.raises(KeyError):
        q.requeue("t-nothing", actor="ayoub")


def test_the_cli_carries_a_reclassified_task_all_the_way_back(tmp_path,
                                                              monkeypatch,
                                                              capsys):
    """Both halves of the repair are reachable from the command line.

    The driver's own failure text tells the reader to declare the task and
    requeue it. That text named a command that did not exist, so the route out
    it described could not be walked — and the one task the deploy-only path
    was written for is the task that failure text was printed for.
    """
    from devloop import driver as drv
    from devloop.queue import declares_deploy_only

    monkeypatch.setattr(drv, "REPO", tmp_path)
    assert drv.main(["enqueue", "--title", "deploy the unreviewed-drafts surface",
                     "--brief", "b", "--path", "infra/devloop/",
                     "--deploy"]) == 0

    q = Queue(tmp_path / ".qevik" / "devloop" / "state.db")
    [row] = q.tasks()
    ident = row["id"]
    q.claim(owner="the driver that failed it")
    q.move(ident, State.FAILED, reason="nothing was changed")

    assert drv.main(["declare-deploy-only", ident, "--actor", "ayoub"]) == 0
    # And it says what is still missing, rather than leaving a person to work
    # out from a queue that never moves that declaring was not enough.
    said = capsys.readouterr().out
    assert "requeue" in said and ident in said, (
        "declaring a task that had already ended says nothing about how to "
        "make it runnable again")

    assert drv.main(["requeue", ident, "--actor", "ayoub",
                     "--reason", "declared deploy-only"]) == 0
    claimed = q.claim(owner="d")
    assert claimed is not None and claimed["id"] == ident
    assert declares_deploy_only(claimed) is True

    # A task that cannot be requeued is refused with a reason, not a traceback.
    q.move(ident, State.DONE, reason="finished")
    assert drv.main(["requeue", ident]) == 1
    assert drv.main(["requeue", "t-nothing"]) == 1


# ------------------------------- the DONE record says what actually happened


def test_the_done_record_names_the_gates_that_ran_and_only_those(tmp_path,
                                                                  monkeypatch):
    """A deploy with no diff runs three of its six gates. It records three.

    `gates.required` is what a task *demands*: every task requires `changed`,
    `scope` and `review`, and none of the three runs on this route — `changed`
    is how the task reached it, having failed. Copying the requirement into the
    DONE transition would record a passed review against a task nobody
    reviewed, on the one route that deliberately has no reviewer, and the
    transitions table is where a person goes to find out what was checked.
    """
    q, ident, main_sha, outcome, called, _ = _deploy_only_run(tmp_path,
                                                              monkeypatch)
    assert outcome == State.DONE
    done = [t for t in q.transitions(ident) if t["to_state"] == State.DONE][-1]

    ran, _, not_run = done["reason"].partition("| not run on this route:")
    for name in called:
        assert name in ran, f"{name} ran and the DONE record does not say so"
    for name in ("changed", "scope", "review"):
        assert name not in ran, (
            f"the DONE record claims {name} passed; it never ran, and the "
            f"record is the only thing anybody has afterwards")
        assert name in not_run, (
            f"{name} was required of this task and was not run, and nothing "
            f"says so")
    assert main_sha in done["reason"]

    # The rest of the record already refuses to call this head reviewed. The
    # transition must not be the one place that says otherwise.
    assert q.review_was_clean(ident) is False
    assert q.scope_was_kept(ident) is False


def test_the_merged_route_records_every_gate_it_ran(tmp_path, monkeypatch):
    """Negative control: a task that really did pass all six says all six.

    The fix must narrow the record to what happened, not narrow every record.
    A task built, gated, scope-checked, reviewed, merged and deployed ran every
    gate it declared, and its DONE transition names them with nothing left out.
    """
    from devloop import driver as drv

    repo, _ = _repo_on_main(tmp_path)
    q = Queue(tmp_path / "s.db")
    ident = q.add(title="build it, then deploy it", brief="b", origin="human",
                  paths=["src/"], requires_deploy=True)
    task = q.claim(owner="test")

    def build(task, *, cwd, **_):
        (cwd / "src" / "app.py").write_text("x = 2\n")
        return drv.agents.Outcome(ok=True, exit_code=0, output="done")

    def review(**_):
        return drv.agents.Outcome(ok=True, exit_code=0, output="",
                                  data={"verdict": "clean", "findings": []})

    monkeypatch.setattr(drv.agents, "build", build)
    monkeypatch.setattr(drv.agents, "review", review)
    monkeypatch.setattr(drv.gates, "tests",
                        lambda **k: gates.Gate("tests", True, "412 passed"))
    monkeypatch.setattr(drv.gates, "deployed",
                        lambda **k: gates.Gate("deployed", True, "answered"))

    assert drv.Driver(q, drv.Limits(), repo=repo).run_task(task) == State.DONE
    done = [t for t in q.transitions(ident) if t["to_state"] == State.DONE][-1]
    for name in gates.required(q.get(ident)):
        assert name in done["reason"], (
            f"{name} ran on the merged route and the DONE record drops it")
    assert "not run" not in done["reason"], (
        "a task that passed every gate it declared is recorded as having "
        "skipped one")


# ---------------------------- a requeue that could only fail is not offered
#
# `_ship` squash-merges into `main` and deletes the branch *before* `_finish`
# runs the full suite, the deploy and the probe. So an ordinary build-and-deploy
# task reaches FAILED — deploy refused, or production disagreed — with its work
# already on `main`, and reaches CONTESTED the same way when the post-merge full
# suite fails. Putting either back hands a builder a tree that already carries
# the work; it correctly writes nothing, and the `changed` gate ends the run
# before it reaches the deploy the requeue was for.
#
# So the ending alone does not say the task can run again. Where the work is
# does, and that is measured from git.


def _landed_then(tmp_path, monkeypatch, *, deploys=True, full_suite=True):
    """Land a build-and-deploy task on `main`, then fail it after the merge.

    The whole point of the fixture is what happens between the two: `_ship`
    merges and deletes the branch, and only then does `_finish` run the gates
    that this makes fail. Returns the queue, the task, the repository, the
    terminal state and the `main` sha from before the run.
    """
    from devloop import driver as drv

    repo, before = _repo_on_main(tmp_path)
    q = Queue(tmp_path / "s.db", repo=repo)
    ident = q.add(title="build the surface, then deploy it", brief="b",
                  origin="human", paths=["src/"], requires_deploy=True)
    task = q.claim(owner="test")

    def build(task, *, cwd, **_):
        (cwd / "src" / "app.py").write_text("x = 2\n")
        return drv.agents.Outcome(ok=True, exit_code=0, output="done")

    def review(**_):
        return drv.agents.Outcome(ok=True, exit_code=0, output="",
                                  data={"verdict": "clean", "findings": []})

    def suite(**kwargs):
        # The narrowed run inside the review loop always passes. The one this
        # controls is `_finish`'s whole suite, which runs *after* the merge.
        if kwargs.get("selector"):
            return gates.Gate("tests", True, "3 passed")
        return gates.Gate("tests", full_suite,
                          "412 passed" if full_suite else "1 failed")

    monkeypatch.setattr(drv.agents, "build", build)
    monkeypatch.setattr(drv.agents, "review", review)
    monkeypatch.setattr(drv.gates, "tests", suite)
    monkeypatch.setattr(drv.gates, "deployed", lambda **k: gates.Gate(
        "deployed", deploys,
        "control plane answered" if deploys else "deploy_control.sh exited 2"))

    outcome = drv.Driver(q, drv.Limits(), repo=repo).run_task(task)
    return q, ident, repo, outcome, before


def _branches(repo) -> str:
    import subprocess

    return subprocess.run(["git", "branch"], cwd=repo, capture_output=True,
                          text=True).stdout


def test_a_failed_task_whose_work_already_landed_is_not_put_back(tmp_path,
                                                                  monkeypatch):
    """The finding, as the run that produced it.

    The deploy refused, so the task is FAILED — but the reviewed diff is on
    `main` and the branch is gone. Requeuing it would start a run whose builder
    finds the work already implemented, and the `changed` gate ends that run
    before the deploy it was put back for. Refused, with the sha named and the
    route that does work named too.
    """
    import subprocess

    from devloop.queue import landed_sha, landing_marker

    q, ident, repo, outcome, before = _landed_then(tmp_path, monkeypatch,
                                                   deploys=False)
    assert outcome == State.FAILED, "the fixture no longer fails after the merge"

    # The state the finding is about, established from git rather than assumed.
    landed = landed_sha(ident, repo=repo)
    assert landed and landed != before, (
        "the task's work is not on main, so this test is not about the "
        "condition the finding describes")
    message = subprocess.run(["git", "log", "-1", "--format=%B", landed],
                             cwd=repo, capture_output=True, text=True).stdout
    assert landing_marker(ident) in message, (
        "the squash commit does not carry the marker the queue reads back, so "
        "the landing is invisible to everything but this test")
    assert f"devloop/{ident}" not in _branches(repo), (
        "the branch still exists, so the run would not start from main")

    with pytest.raises(ValueError) as refused:
        q.requeue(ident, actor="ayoub", reason="retry the deploy")
    said = str(refused.value)
    assert landed[:12] in said, (
        "the refusal does not name the sha main already carries, so a person "
        "cannot check the claim it is refusing on")
    assert "deploy-only" in said, (
        "the refusal does not name the path that redeploys what main carries, "
        "so it stops a person without telling them what to do instead")
    assert q.get(ident)["state"] == State.FAILED, (
        "the row moved despite the refusal")


def test_a_contested_task_whose_work_already_landed_is_not_put_back(tmp_path,
                                                                     monkeypatch):
    """The same landing, reached through the other post-merge ending.

    `_finish` runs the whole suite after `_ship` has merged, so a suite that
    fails there leaves CONTESTED with the work on `main` — exactly as far past
    the point of no return as the failed deploy, and just as unrunnable again.
    """
    from devloop.queue import landed_sha

    q, ident, repo, outcome, _ = _landed_then(tmp_path, monkeypatch,
                                              full_suite=False)
    assert outcome == State.CONTESTED
    landed = landed_sha(ident, repo=repo)
    assert landed, "the post-merge suite failure did not leave the work on main"

    with pytest.raises(ValueError) as refused:
        q.requeue(ident, actor="ayoub", reason="the suite is green again now")
    assert landed[:12] in str(refused.value)
    assert q.get(ident)["state"] == State.CONTESTED


def test_the_route_the_refusal_names_deploys_what_main_already_carries(
        tmp_path, monkeypatch):
    """And the route it names actually runs, which is the point of naming it.

    The refusal is only useful if what it sends a person to works. A deploy-only
    task over the same `main` reaches the deploy gates instead of failing
    `changed` — which is the whole difference between the two, and the reason
    this is the answer rather than a requeue.
    """
    from devloop import driver as drv

    q, failed, repo, outcome, _ = _landed_then(tmp_path, monkeypatch,
                                               deploys=False)
    assert outcome == State.FAILED

    again = q.add(title="deploy what main already carries",
                  brief="the work landed; put it on the host",
                  origin="human", paths=["src/"], deploy_only=True)
    task = q.claim(owner="test")
    assert task is not None and task["id"] == again, (
        "the landed task was handed out again, which is what this refuses")

    _builder_that_changes_nothing(monkeypatch, drv)

    def never_review(**_):
        raise AssertionError("a deploy with no diff was sent for review")

    monkeypatch.setattr(drv.agents, "review", never_review)
    monkeypatch.setattr(drv.gates, "tests",
                        lambda **k: gates.Gate("tests", True, "412 passed"))
    monkeypatch.setattr(drv.gates, "deployed",
                        lambda **k: gates.Gate("deployed", True, "answered"))

    assert drv.Driver(q, drv.Limits(), repo=repo).run_task(task) == State.DONE
    reasons = " ".join(t["reason"] for t in q.transitions(again))
    assert "nothing was changed" not in reasons, (
        "the run the refusal sends a person to fails on the empty diff too, so "
        "the refusal leaves them with nowhere to go")
    assert State.DEPLOYING in {t["to_state"] for t in q.transitions(again)}
    # And what it deployed is the landed task's own work: `main`'s head is the
    # squash commit `_ship` made before the deploy that failed.
    from devloop.queue import landed_sha

    assert q.get(again)["head_sha"] == landed_sha(failed, repo=repo)


def test_a_task_that_failed_before_landing_is_still_put_back(tmp_path):
    """The negative control, and the case requeue exists for.

    Nothing about this narrows to endings that happen to be pre-merge by
    accident: a task that failed its `changed` gate, and one contested over
    three rounds of findings, both left `main` untouched, and both are put back
    exactly as before.
    """
    from devloop.queue import landed_sha

    repo, _ = _repo_on_main(tmp_path)
    q = Queue(tmp_path / "s.db", repo=repo)
    ident = q.add(title="deploy and verify the unreviewed-drafts surface",
                  brief="b", origin="human", paths=["infra/devloop/"],
                  requires_deploy=True)

    for ending in (State.FAILED, State.CONTESTED, State.BLOCKED):
        q.claim(owner="the driver that ended it")
        q.move(ident, ending, reason="ended before anything landed")
        assert landed_sha(ident, repo=repo) == "", (
            "git reports work on main that no run ever put there")
        assert q.requeue(ident, actor="ayoub", reason="declared") is True, (
            f"a task that ended {ending} with nothing on main was refused; the "
            f"repair a person makes outside the loop can no longer reach it")
        claimed = q.claim(owner="d")
        assert claimed is not None and claimed["id"] == ident


def test_a_landing_that_could_not_be_measured_is_not_guessed(tmp_path,
                                                              monkeypatch):
    """A repository that will not answer is unknown, and unknown is refused.

    The whole guard is a measurement, so a measurement that did not happen
    cannot be reported as "nothing landed" — that is the answer that starts the
    run which cannot succeed. It fails towards the person, who can read the
    reason and fix the repository.
    """
    from devloop import queue as queue_module

    repo, _ = _repo_on_main(tmp_path)
    q = Queue(tmp_path / "s.db", repo=repo)
    ident = q.add(title="t", brief="b", origin="human", paths=["src/"],
                  requires_deploy=True)
    q.claim(owner="d")
    q.move(ident, State.FAILED, reason="the deploy failed")

    answering = queue_module._git

    def refuses_the_question(*args, cwd):
        if args and args[0] == "log":
            return 128, ""
        return answering(*args, cwd=cwd)

    monkeypatch.setattr(queue_module, "_git", refuses_the_question)
    with pytest.raises(ValueError, match="could not be read"):
        q.requeue(ident, actor="ayoub")
    assert q.get(ident)["state"] == State.FAILED

    # And a queue that lives outside every repository is not the same thing:
    # there is no `main` for anything to have landed on, so nothing has.
    assert queue_module.landed_sha(ident, repo=None) == ""
    assert queue_module.landed_sha(ident, repo=tmp_path / "not-a-repo") == ""


def test_the_landing_is_written_and_read_through_one_spelling():
    """Structural: two copies of the marker would disable the guard silently.

    `_ship` writes it into the squash commit and `landed_sha` greps `main` for
    it. Nothing fails when the two drift apart — the guard simply stops finding
    landings, and the requeue it exists to refuse starts working again.
    """
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    ship = source[source.index("def _ship("):source.index("def _deploy_only(")]
    code = "\n".join(line for line in ship.splitlines()
                     if not line.strip().startswith("#"))
    assert "landing_marker(ident)" in code, (
        "the squash commit does not use the marker the queue reads back")
    assert "devloop task" not in code, (
        "the landing marker is spelled out a second time in _ship; the queue "
        "greps for the first spelling and would stop seeing landings the "
        "moment either changed")


def test_the_driver_hands_its_queue_the_repository_it_lands_work_in():
    """The guard measures git, so the queue has to know which tree to ask.

    A queue with no repository answers "nothing has landed" — correctly, since
    there is no `main` outside a repository — so the driver's own queue must be
    given one, or the refusal quietly never fires in the one place it matters.
    """
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    call = source[source.index("Queue(REPO"):][:200]
    assert "repo=REPO" in call, (
        "the driver builds its queue without naming the repository, so "
        "`requeue` cannot see that a task's work is already on main")
