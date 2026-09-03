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


def test_a_docs_only_change_runs_the_whole_suite(tmp_path, monkeypatch):
    """Measured: `-k "00_PROJECT_STATE"` deselects all 4306 tests, exit=5.

    The selector used to be built from every touched path, so a task that
    changed only `docs/qevik-docs/00_PROJECT_STATE.md` asked pytest for a name
    no test carries. pytest exits 5 when it selected nothing, `gates.tests`
    reads any non-zero exit as a failed gate, and the round went to the fixer
    with "4306 deselected" as its failure scenario — a task with no tests
    burning its rounds on a suite that never ran a line of it.

    Empty is the documented safe direction: the whole suite runs.
    """
    import devloop.driver as drv

    driver = drv.Driver.__new__(drv.Driver)
    driver.repo = tmp_path

    monkeypatch.setattr(
        drv.Driver, "_touched",
        lambda self: ["docs/qevik-docs/00_PROJECT_STATE.md",
                      "docs/qevik-docs/90_DECISIONS.md",
                      "README.md"])
    assert driver._selector() == ""

    # Docs beside code: the code narrows the run, the docs contribute nothing.
    monkeypatch.setattr(
        drv.Driver, "_touched",
        lambda self: ["docs/qevik-docs/00_PROJECT_STATE.md",
                      "infra/devloop/driver.py",
                      "packages/kernel/tests/test_devloop.py",
                      "apps/control/src/index.html",
                      "infra/devloop/review.schema.json"])
    assert driver._selector() == "devloop or driver"


def test_the_full_suite_still_runs_before_anything_deploys():
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    ship = source[source.index("def _ship("):source.index("def _selector(")]
    assert "gates.tests(cwd=self.repo)" in ship, (
        "the deploy path runs a narrowed suite; a narrow gate is not enough to "
        "put code on a live host")


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


# ---------------------------------- measured against the work, not the last
#
# The gate ran on `base..HEAD` *before* the round was committed, so the range
# it measured held every round except the one just written. It was one round
# stale, and on round one it compared `base` with itself and could not fail.
#
# t-7f9d5d633396 paid for it: round 1 measured 0 non-test lines, round 2 saw
# round 1's 715, round 3 saw round 2's 788 — and the 812 that landed on `main`
# was past the 800-line limit and had never been measured by anything.


def test_an_empty_range_measured_nothing_and_is_not_a_small_change(monkeypatch):
    """A check satisfied by its own absence, refused where it starts.

    `base..HEAD` is empty until the round is committed, and an empty diff is
    not a small change — it is a change this gate never saw. Called a pass, it
    is what made round one unfailable, so it is `unmeasured` instead: the
    driver treats that as an infrastructure failure rather than as consent.
    """
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: (0, "", False))
    g = gates.size(cwd=Path("."), base_sha="a" * 40)
    assert g.passed is False and g.unmeasured is True
    assert g.evidence == {"files": 0, "non_test_lines": 0, "test_lines": 0}


def test_the_size_gate_records_the_counts_it_judged_on(monkeypatch):
    """Numbers a person can disagree with, not a sentence about them."""
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: (
        0, "500\t12\tsrc/a.py\n40\t0\tpackages/kernel/tests/test_a.py", False))
    g = gates.size(cwd=Path("."), base_sha="x")
    assert g.evidence == {"files": 2, "non_test_lines": 512, "test_lines": 40}


def test_the_driver_measures_size_on_the_commit_it_has_just_made():
    """A round's work is not in `base..HEAD` until it is committed.

    So the size gate sits where the scope gate sits — after the commit, before
    the review — and for the same reason: both answer about the range that
    would land, or they answer about the wrong thing.
    """
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    run_task = source[source.index("def run_task("):source.index("def _ship(")]
    commit = run_task.index("self._commit(task, round_no)")
    measured = run_task.index("gates.size(")
    review = run_task.index("agents.review(")
    assert commit < measured < review, (
        "size is measured before the round is committed, so it reads the "
        "previous round's diff and round one measures nothing at all")
    # And a size nothing could measure is refused rather than passed over.
    assert "size unmeasured" in run_task[measured:review]


def _repo_ready_for_a_run(tmp_path):
    """A repository sitting on `main`, with the ledger the driver parks into.

    (`_repo_with_a_task_branch` is defined with the scope tests below, which is
    where the repository helpers live.)
    """
    import subprocess

    repo, _ = _repo_with_a_task_branch(tmp_path, touching=[])
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    (repo / ".qevik" / "devloop").mkdir(parents=True)
    (repo / ".qevik" / "DECISION_QUEUE.md").write_text("# Decisions\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "ledgers"], cwd=repo, check=True,
                   capture_output=True)
    return repo


def _one_round(repo, tmp_path, monkeypatch, *, build):
    """One task through the real driver on a real repository.

    The reviewer records what it was asked about and then stops the run: what
    these tests are about is everything that happens before anybody is asked
    an opinion.
    """
    from devloop import driver as drv

    q = Queue(tmp_path / "s.db")
    ident = q.add(title="one module", brief="b", origin="human", paths=["src/"])
    task = q.claim(owner="test")
    reviewed: list[str] = []

    def review(**k):
        reviewed.append(k["base_sha"])
        return agents.Outcome(ok=False, exit_code=1, output="",
                              infrastructure_failure=True, detail="stop here")

    monkeypatch.setattr(drv.agents, "build", build)
    monkeypatch.setattr(drv.agents, "review", review)
    monkeypatch.setattr(drv.gates, "tests",
                        lambda **k: gates.Gate("tests", True, "1 passed"))
    state = drv.Driver(q, drv.Limits(), repo=repo).run_task(task)
    return q, ident, state, reviewed


def test_an_oversized_first_round_is_stopped_before_anybody_reviews_it(
        tmp_path, monkeypatch):
    """The negative control: the case that was impossible to fail.

    Round one, nine hundred non-test lines, on a real repository. Run against
    the gate as it was, this measured an empty range, called it small enough,
    and sent all nine hundred lines to the reviewer — which is how 812 reached
    `main` past an 800-line limit with no gate objecting.
    """
    import subprocess

    repo = _repo_ready_for_a_run(tmp_path)

    def rev(*args) -> str:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True).stdout.strip()

    main_before = rev("rev-parse", "main")

    def build(task, *, cwd, **_):
        (cwd / "src" / "sprawl.py").write_text(
            "\n".join(f"line_{n} = {n}" for n in range(900)) + "\n")
        return agents.Outcome(ok=True, exit_code=0, output="done")

    q, ident, state, reviewed = _one_round(repo, tmp_path, monkeypatch,
                                           build=build)

    assert state == State.CONTESTED
    assert reviewed == [], "an oversized round was sent for review"
    row = q.get(ident)
    assert row["state"] == State.CONTESTED
    [oversized] = [t["reason"] for t in q.transitions(ident)
                   if t["reason"].startswith("oversized:")]
    # The number is the whole point. The gate saw *this* round's nine hundred
    # lines; the stale gate saw the zero of an empty range.
    assert "900 lines outside tests" in oversized
    assert row["review_rounds"] == 0, "it was not stopped on the first round"

    # The work is committed on the task branch — which is what the ledger entry
    # promises a person will find there, and what an uncommitted round could
    # not have offered.
    assert rev("rev-parse", f"devloop/{ident}") == row["head_sha"]
    assert rev("rev-list", "--count", f"main..devloop/{ident}") == "1"
    assert rev("rev-parse", "main") == main_before, "an oversized diff reached main"
    assert rev("branch", "--show-current") == "main"
    ledger = (repo / ".qevik" / "DECISION_QUEUE.md").read_text()
    assert f"<!-- devloop:oversized:{ident} -->" in ledger
    assert "Split it at a real boundary" in ledger


def test_a_bounded_first_round_is_measured_and_reaches_the_review(tmp_path,
                                                                  monkeypatch):
    """The other half of the control: the gate is not simply refusing rounds.

    Same driver, same repository, forty lines — measured on the same committed
    range, passed, and the reviewer is asked about exactly that range.
    """
    import subprocess

    repo = _repo_ready_for_a_run(tmp_path)
    main_before = subprocess.run(["git", "rev-parse", "main"], cwd=repo,
                                 capture_output=True, text=True).stdout.strip()

    def build(task, *, cwd, **_):
        (cwd / "src" / "small.py").write_text(
            "\n".join(f"line_{n} = {n}" for n in range(40)) + "\n")
        return agents.Outcome(ok=True, exit_code=0, output="done")

    q, ident, _, reviewed = _one_round(repo, tmp_path, monkeypatch, build=build)

    assert reviewed == [main_before], (
        "a round well inside the limit was not reviewed, or was reviewed "
        "against a range other than the one that was sized")
    assert not any(t["reason"].startswith("oversized:")
                   for t in q.transitions(ident))


def test_a_size_the_driver_could_not_measure_is_never_a_pass(tmp_path,
                                                             monkeypatch):
    """An unmeasured size gate requeues the task; it does not wave it through.

    This is what stops the defect returning quietly. Move the gate back ahead
    of the commit and round one measures an empty range — which is unmeasured,
    so the loop reports broken tooling instead of reviewing and landing work
    that nothing ever sized.
    """
    from devloop import driver as drv

    repo = _repo_ready_for_a_run(tmp_path)
    monkeypatch.setattr(drv.gates, "size", lambda **k: gates.Gate(
        "size", False, "nothing is committed in x..HEAD", unmeasured=True))

    def build(task, *, cwd, **_):
        (cwd / "src" / "small.py").write_text("x = 2\n")
        return agents.Outcome(ok=True, exit_code=0, output="done")

    q, ident, state, reviewed = _one_round(repo, tmp_path, monkeypatch,
                                           build=build)

    assert state == State.FAILED and reviewed == [], (
        "work whose size nothing could measure was sent for review")
    assert q.get(ident)["state"] == State.QUEUED, "the task was not requeued"
    assert any("infrastructure failure" in t["reason"]
               and "size unmeasured" in t["reason"]
               for t in q.transitions(ident))


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


# ================================= the loop ships the commit it tested
#
# `_ship` used to log the landed sha and then discard it: the full suite ran on
# whatever the working tree held at that moment, `./infra/deploy_control.sh` was
# called with nothing but a `cwd`, and nothing afterwards asked the host what it
# had actually installed. "The deploy shipped what was tested" was a property of
# nobody touching the tree for about fifteen minutes, and it was unmeasured.
#
# Every test below drives the real `_ship` against a real repository and a real
# queue, with one controlled drift at a time.


def _git_in(repo, *args: str) -> str:
    """A git command the test expects to succeed."""
    import subprocess

    done = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True)
    assert done.returncode == 0, \
        f"git {' '.join(args)}: {done.stdout}{done.stderr}"
    return done.stdout.strip()


def _rejecting_hook(repo, body: str = "") -> None:
    """A `pre-commit` hook that fails the squash commit, as a signing failure,
    a lint hook or a `commit-msg` rule would."""
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\n" + body + "exit 1\n")
    hook.chmod(0o755)


def _ready_to_ship(tmp_path, *, deploy=True, prod=False, evidence=None,
                   work=None):
    """A repository whose task branch is reviewed clean and ready to land.

    Everything `_ship` asks the record for is real: a review of this exact head
    with no findings, and a scope check on the same head that stayed inside the
    contract. Without both, `_ship` refuses before it reaches anything here.
    """
    from types import SimpleNamespace

    from devloop import driver as drv

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    for argv in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t"),
                 ("config", "user.name", "t"),
                 ("config", "commit.gpgsign", "false")):
        _git_in(repo, *argv)
    (repo / "src" / "app.py").write_text("x = 1\n")
    (repo / "src" / "keep.py").write_text("y = 1\n")
    _git_in(repo, "add", "-A")
    _git_in(repo, "commit", "-qm", "base")

    queue = Queue(tmp_path / "s.db")
    ident = queue.add(title="ships it", brief="the brief", origin="human",
                      paths=["src/"], evidence=evidence or {},
                      requires_deploy=deploy, requires_prod_check=prod)
    queue.claim(owner="test")
    branch = f"devloop/{ident}"
    _git_in(repo, "checkout", "-q", "-b", branch)
    if work is None:
        (repo / "src" / "app.py").write_text("x = 2\n")
    else:
        work(repo)
    _git_in(repo, "add", "-A")
    _git_in(repo, "commit", "-qm", "the task's work")
    head = _git_in(repo, "rev-parse", "HEAD")
    _git_in(repo, "checkout", "-q", "main")

    queue.move(ident, State.REVIEWING, reason="round 1", head_sha=head,
               review_rounds=1)
    queue.record_review(ident, round=1, sha=head, verdict="CLEAN", findings=0)
    queue.record_scope(ident, round=1, sha=head, declared=["src/"],
                       changed=["src/app.py"], undeclared=[])
    return SimpleNamespace(
        drv=drv, q=queue, ident=ident, branch=branch, repo=repo, head=head,
        base=_git_in(repo, "rev-parse", "main"), task=queue.get(ident),
        driver=drv.Driver(queue, drv.Limits(), repo=repo))


def _nothing_deploys(monkeypatch) -> None:
    """Every host-facing gate, wired to fail the test if anything reaches it."""
    def refuse(**_):
        raise AssertionError("a commit that drifted from the suite was deployed")

    monkeypatch.setattr(gates, "deployed", refuse)
    monkeypatch.setattr(gates, "provenance", refuse)
    monkeypatch.setattr(gates, "in_production", refuse)


def _nothing_is_tested(monkeypatch) -> None:
    """For the landing failures: nothing may get as far as the suite."""
    def refuse(**_):
        raise AssertionError("a failed landing reached the full suite")

    monkeypatch.setattr(gates, "tests", refuse)


def _passing_suite(monkeypatch, *, then=None):
    def suite(**_):
        if then is not None:
            then()
        return gates.Gate("tests", True, "12 passed in 60s")

    monkeypatch.setattr(gates, "tests", suite)


def _ship(ready) -> str:
    import time as clock

    return ready.driver._ship(ready.task, clock.monotonic())


def _reasons(ready) -> str:
    return " | ".join(t["reason"] for t in ready.q.transitions(ready.ident))


def test_a_commit_that_lands_while_the_suite_runs_cannot_ship(tmp_path,
                                                              monkeypatch):
    """The window the old code could not see.

    The suite runs for about eleven minutes. Anything that commits to `main` in
    that time becomes part of what the deploy script copies, and the suite that
    passed did not measure it.
    """
    ready = _ready_to_ship(tmp_path)

    def meanwhile():
        (ready.repo / "src" / "interloper.py").write_text("z = 1\n")
        _git_in(ready.repo, "add", "-A")
        _git_in(ready.repo, "commit", "-qm", "somebody else's commit")

    _passing_suite(monkeypatch, then=meanwhile)
    _nothing_deploys(monkeypatch)

    assert _ship(ready) == State.CONTESTED
    assert ready.q.get(ready.ident)["state"] == State.CONTESTED
    reasons = _reasons(ready)
    assert "refused to deploy" in reasons and "HEAD is" in reasons


def test_a_tree_dirtied_while_the_suite_runs_cannot_ship(tmp_path, monkeypatch):
    """The deploy script copies the tree, so an uncommitted edit ships too."""
    ready = _ready_to_ship(tmp_path)
    _passing_suite(monkeypatch,
                   then=lambda: (ready.repo / "src" / "stray.py").write_text("q\n"))
    _nothing_deploys(monkeypatch)

    assert _ship(ready) == State.CONTESTED
    assert "refused to deploy" in _reasons(ready)
    assert "working tree is not clean" in _reasons(ready)


def test_a_commit_no_longer_on_main_cannot_ship(tmp_path, monkeypatch):
    """HEAD is still the tested commit and the tree is clean — and `main` has
    moved out from under it, so the commit is no longer what `main` says the
    project is. The deploy script refuses a non-ancestor too; the driver must
    not get that far."""
    ready = _ready_to_ship(tmp_path)

    def rewind():
        _git_in(ready.repo, "checkout", "-q", "--detach")
        _git_in(ready.repo, "branch", "-f", "main", "HEAD~1")

    _passing_suite(monkeypatch, then=rewind)
    _nothing_deploys(monkeypatch)

    assert _ship(ready) == State.CONTESTED
    assert "no longer an ancestor of main" in _reasons(ready)


# ---------------------------------------- a landing that failed (DQ-013)
#
# Three review rounds of attempt 1 were one chain about this path: the squash
# commit was rejected and `main` was left dirty (the loop wedged), then the fix
# reset `main` hard (destroying edits the branch did not hold), then the
# cleanliness check ahead of that reset turned out to be racy. DQ-013 settles
# it: preservation outranks liveness, the proof is content-based, and there is
# no lock.


def test_a_rejected_squash_commit_is_settled_from_the_branchs_own_content(
        tmp_path, monkeypatch):
    """F1. A hook, a signing failure or a commit-time error leaves the squash
    staged on `main`. Left there, the next task's clean-tree check refuses and
    the loop is wedged over work the branch still holds."""
    ready = _ready_to_ship(tmp_path)
    _rejecting_hook(ready.repo)
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.CONTESTED
    reasons = _reasons(ready)
    assert "refused to land" in reasons
    assert f"main restored to {ready.base}" in reasons
    assert _git_in(ready.repo, "status", "--porcelain") == "", \
        "main was left dirty, which wedges the next task's clean-tree check"
    assert _git_in(ready.repo, "rev-parse", "main") == ready.base
    assert _git_in(ready.repo, "rev-parse", ready.branch) == ready.head, \
        "the reviewed work was deleted along with the failed landing"


def test_a_conflicted_squash_is_preserved_rather_than_settled(tmp_path,
                                                              monkeypatch):
    """The merge itself fails. A conflicted path is not the branch's blob, so
    it is not provably the task's own squash state and nothing is touched."""
    ready = _ready_to_ship(tmp_path)
    (ready.repo / "src" / "app.py").write_text("x = 99\n")
    _git_in(ready.repo, "add", "-A")
    _git_in(ready.repo, "commit", "-qm", "main moved")
    moved = _git_in(ready.repo, "rev-parse", "main")
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.BLOCKED
    reasons = _reasons(ready)
    assert "src/app.py: conflicted" in reasons
    assert "not provably only the squash" in reasons
    assert "<<<<<<<" in (ready.repo / "src" / "app.py").read_text(), \
        "the conflict was cleaned up rather than left for a person"
    assert _git_in(ready.repo, "rev-parse", "main") == moved


def test_a_hook_that_rewrites_a_file_before_rejecting_loses_nothing(tmp_path,
                                                                    monkeypatch):
    """F2. `git reset --hard HEAD` was the r1 fix, and it discards exactly this:
    content the task branch does not hold. A formatter that rewrites and then
    rejects is an ordinary pre-commit hook."""
    ready = _ready_to_ship(tmp_path)
    _rejecting_hook(ready.repo, 'echo "# rewritten by the hook" >> src/app.py\n')
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.BLOCKED
    assert "# rewritten by the hook" in (ready.repo / "src" / "app.py").read_text()
    assert _git_in(ready.repo, "status", "--porcelain") != ""
    reasons = _reasons(ready)
    assert "not provably only the squash" in reasons
    assert "src/app.py: content differs from the branch" in reasons
    assert ready.head in reasons, "the reason does not say where the work is"
    assert _git_in(ready.repo, "rev-parse", "main") == ready.base
    assert _git_in(ready.repo, "rev-parse", ready.branch) == ready.head
    assert ready.q.get(ready.ident)["state"] == State.BLOCKED


def test_work_that_appeared_in_the_window_is_preserved(tmp_path, monkeypatch):
    """F3. The r2 fix checked `status` *before* the squash, which proves nothing
    about the tree afterwards. The proof is content-based instead: an untracked
    file nobody declared is outside the squash set whenever it arrived, so
    nothing is destroyed and nothing is restored either."""
    ready = _ready_to_ship(tmp_path)
    _rejecting_hook(ready.repo, 'echo "an operator note" > NOTES.md\n')
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.BLOCKED
    assert (ready.repo / "NOTES.md").read_text() == "an operator note\n"
    assert "NOTES.md: outside the squash" in _reasons(ready)
    # And the squash set was left exactly as found: a tree that could not be
    # proved is not partially cleaned up either.
    assert (ready.repo / "src" / "app.py").read_text() == "x = 2\n"


def test_an_edit_to_a_file_outside_the_squash_is_preserved(tmp_path, monkeypatch):
    """The same rule for a tracked file: `src/keep.py` is not in the squash set,
    so an edit to it is somebody else's and is never discarded."""
    ready = _ready_to_ship(tmp_path)
    _rejecting_hook(ready.repo, 'echo "y = 2" >> src/keep.py\n')
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.BLOCKED
    assert "y = 2" in (ready.repo / "src" / "keep.py").read_text()
    assert "src/keep.py: outside the squash" in _reasons(ready)


def test_a_path_the_branch_deleted_is_restored_from_main(tmp_path, monkeypatch):
    """The cleanup has to put back what the squash removed, without a reset."""
    ready = _ready_to_ship(
        tmp_path, work=lambda repo: (repo / "src" / "keep.py").unlink())
    _rejecting_hook(ready.repo)
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.CONTESTED
    assert (ready.repo / "src" / "keep.py").read_text() == "y = 1\n"
    assert _git_in(ready.repo, "status", "--porcelain") == ""
    assert _git_in(ready.repo, "rev-parse", "main") == ready.base


def test_a_path_the_branch_added_is_removed_by_the_cleanup(tmp_path, monkeypatch):
    """And take back out what the squash added — index and worktree both, since
    an untracked leftover is what the next task's clean-tree check trips on."""
    ready = _ready_to_ship(
        tmp_path,
        work=lambda repo: (repo / "src" / "added.py").write_text("new = 1\n"))
    _rejecting_hook(ready.repo)
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.CONTESTED
    assert not (ready.repo / "src" / "added.py").exists()
    assert _git_in(ready.repo, "status", "--porcelain") == ""


def test_an_added_path_the_hook_rewrote_is_preserved(tmp_path, monkeypatch):
    """The same added path, with content the branch does not hold: removing it
    would destroy the hook's version, so it stays and a person decides."""
    ready = _ready_to_ship(
        tmp_path,
        work=lambda repo: (repo / "src" / "added.py").write_text("new = 1\n"))
    _rejecting_hook(ready.repo, 'echo "touched = 1" >> src/added.py\n')
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.BLOCKED
    assert "touched = 1" in (ready.repo / "src" / "added.py").read_text()
    assert "src/added.py: content differs from the branch" in _reasons(ready)


def test_a_mode_change_with_no_content_change_is_preserved(tmp_path, monkeypatch):
    """R1. Git tracks one permission bit and it is real work: `chmod +x` with no
    edit to a byte is a change `status` reports and a commit keeps.

    A blob-only proof cannot see it — the blob is unchanged, that being the
    point — so the path reads as "exactly what the branch holds" and the restore
    reverts the mode to the base's. The proof compares modes as well, and this
    is a `chmod` the index never saw, so the on-disk mode is what catches it."""
    ready = _ready_to_ship(tmp_path)
    _rejecting_hook(ready.repo, "chmod +x src/app.py\n")
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.BLOCKED
    assert (ready.repo / "src" / "app.py").stat().st_mode & 0o100, \
        "the cleanup reverted a mode change the branch does not hold"
    reasons = _reasons(ready)
    assert "src/app.py: mode differs from the branch" in reasons
    assert "not provably only the squash" in reasons
    assert _git_in(ready.repo, "rev-parse", "main") == ready.base
    assert _git_in(ready.repo, "rev-parse", ready.branch) == ready.head


def test_a_staged_mode_change_is_preserved(tmp_path, monkeypatch):
    """The same edit, this time staged before the commit was rejected: the index
    mode now disagrees with the branch even though the blob still matches."""
    ready = _ready_to_ship(tmp_path)
    _rejecting_hook(ready.repo,
                    "chmod +x src/app.py\ngit update-index --chmod=+x src/app.py\n")
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.BLOCKED
    assert "src/app.py: index disagrees (mode 100755" in _reasons(ready)
    assert _git_in(ready.repo, "ls-files", "-s", "--", "src/app.py").startswith(
        "100755"), "a staged mode change was discarded by the cleanup"


def test_a_mode_the_branch_holds_does_not_block_the_cleanup(tmp_path, monkeypatch):
    """The negative control: an executable file the *branch itself* made
    executable is what the branch holds, so the proof passes and the cleanup
    runs. Without this the mode check could pass its own test by refusing
    everything."""
    def work(repo):
        (repo / "src" / "run.sh").write_text("#!/bin/sh\necho hi\n")
        (repo / "src" / "run.sh").chmod(0o755)

    ready = _ready_to_ship(tmp_path, work=work)
    _rejecting_hook(ready.repo)
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)

    assert _ship(ready) == State.CONTESTED
    assert not (ready.repo / "src" / "run.sh").exists()
    assert _git_in(ready.repo, "status", "--porcelain") == ""


def _edit_during_the_cleanup(ready, monkeypatch, *, when: str, edit) -> None:
    """Run `edit` the moment the cleanup writes `when` — the window between a
    path's proof and a *later* path's write, which is exactly the window a
    single up-front proof pass leaves open."""
    real = ready.drv._git
    fired = []

    def spy(*args, **kwargs):
        done = real(*args, **kwargs)
        if args[:1] == ("checkout",) and args[-1] == when and not fired:
            fired.append(True)
            edit(ready.repo)
        return done

    monkeypatch.setattr(ready.drv, "_git", spy)


def test_an_edit_arriving_mid_cleanup_is_not_overwritten(tmp_path, monkeypatch):
    """R2. The proof pass finishes before the first path is touched, so by the
    time the loop reaches path N the proof of path N is as old as every restore
    before it — seconds of subprocess calls, not an instant.

    Here the operator writes to `src/keep.py` while `src/app.py` is being
    restored. Re-proving each path immediately before its own write catches it;
    a single up-front pass would have checked out over the top of it."""
    def work(repo):
        (repo / "src" / "app.py").write_text("x = 2\n")
        (repo / "src" / "keep.py").write_text("y = 2\n")

    ready = _ready_to_ship(tmp_path, work=work)
    _rejecting_hook(ready.repo)
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)
    _edit_during_the_cleanup(
        ready, monkeypatch, when="src/app.py",
        edit=lambda repo: (repo / "src" / "keep.py").write_text("y = 3\n"))

    assert _ship(ready) == State.BLOCKED
    assert (ready.repo / "src" / "keep.py").read_text() == "y = 3\n", \
        "an edit made during the cleanup was checked out over the top of"
    reasons = _reasons(ready)
    assert "src/keep.py: content differs from the branch" in reasons
    assert "it changed while the cleanup was running" in reasons
    assert "already restored the first 1 of 2 path(s)" in reasons, \
        "the reason does not say the cleanup stopped part-way"
    assert _git_in(ready.repo, "rev-parse", ready.branch) == ready.head


def test_a_file_created_mid_cleanup_is_not_deleted(tmp_path, monkeypatch):
    """The same window, on the other destructive arm: `os.remove` of a path the
    branch added. The operator's content arrives after that path was proved and
    before it is deleted, so the delete must not happen.

    The added path is named to sort *after* `src/app.py`, because the cleanup
    walks the squash set in `git diff --name-only` order and the window under
    test is the one that opens once an earlier path has been written."""
    def work(repo):
        (repo / "src" / "app.py").write_text("x = 2\n")
        (repo / "src" / "zadded.py").write_text("new = 1\n")

    ready = _ready_to_ship(tmp_path, work=work)
    _rejecting_hook(ready.repo)
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)
    _edit_during_the_cleanup(
        ready, monkeypatch, when="src/app.py",
        edit=lambda repo: (repo / "src" / "zadded.py").write_text("mine = 1\n"))

    assert _ship(ready) == State.BLOCKED
    assert (ready.repo / "src" / "zadded.py").read_text() == "mine = 1\n", \
        "a file written during the cleanup was deleted by it"
    assert "src/zadded.py: content differs from the branch" in _reasons(ready)


def test_the_cleanup_reproves_each_path_against_the_live_tree():
    """Structural, because the window is a property of *where* the proof runs,
    not of any one path: a cleanup that trusts the up-front pass is racy however
    the pass is written."""
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    settle = source[source.index("def _settle_failed_landing("):
                    source.index("def _not_the_branchs(")]
    body = settle[settle.index("if not proof:\n            # Proven"):]
    assert body.index("_not_the_branchs(") < body.index('_git("checkout"'), (
        "the cleanup writes before it re-proves the path it is writing to")
    assert body.index("_not_the_branchs(") < body.index("os.remove("), (
        "the cleanup deletes before it re-proves the path it is deleting")


def test_the_shipping_path_holds_no_destructive_reset():
    """Structural, because DQ-013 §2 is a rule about the code and not about one
    call site. A reset, a `clean` or a `checkout -- .` acts on everything in the
    tree, including whatever nothing here has proved anything about."""
    source = Path(INFRA / "devloop" / "driver.py").read_text()
    for forbidden in ('_git("reset"', '_git("clean"', '_git("checkout", "--", "."'):
        assert forbidden not in source, (
            f"{forbidden} is back in the driver: a failed landing would destroy "
            f"work no gate has proved belongs to the task")
    settle = source[source.index("def _settle_failed_landing("):]
    assert "DQ-013" in settle[:settle.index('"""', settle.index('"""') + 3)], (
        "the rule governing this path is not quoted where the diff is read")


def test_the_blocked_reason_of_a_preserved_landing_is_durable(tmp_path,
                                                              monkeypatch):
    """A person reads the queue, not this process's stdout."""
    ready = _ready_to_ship(tmp_path)
    _rejecting_hook(ready.repo, 'echo "# rewritten" >> src/app.py\n')
    _nothing_deploys(monkeypatch)
    _nothing_is_tested(monkeypatch)
    _ship(ready)

    newest = ready.q.transitions(ready.ident)[-1]
    assert newest["to_state"] == State.BLOCKED
    assert "remaining:" in newest["reason"]
    assert ready.head in newest["reason"] and ready.base in newest["reason"]
    assert ready.q.get(ready.ident)["state"] == State.BLOCKED


# ------------------------------------------- what actually reaches the host


def test_the_deploy_is_given_the_commit_the_suite_passed_on(tmp_path,
                                                            monkeypatch):
    """The whole point. Today the gate is called with a `cwd` and nothing else,
    so the script ships whatever the tree holds at that moment."""
    ready = _ready_to_ship(tmp_path)
    asked: list[dict] = []
    _passing_suite(monkeypatch)
    monkeypatch.setattr(gates, "deployed", lambda **k: (
        asked.append(k), gates.Gate("deployed", True, "installed",
                                    evidence={"sha": k["sha"], "exit": 0}))[1])
    monkeypatch.setattr(gates, "provenance", lambda **k: gates.Gate(
        "provenance", True, "state=installed",
        evidence={"expected": k["sha"], "marker": {"sha": k["sha"]}}))

    assert _ship(ready) == State.DONE
    landed = _git_in(ready.repo, "rev-parse", "main")
    assert len(asked) == 1 and asked[0]["sha"] == landed
    assert any(t["reason"].startswith(f"deploying {landed};")
               for t in ready.q.transitions(ready.ident))

    # The sha is recorded where it does not collide with the review key.
    done = ready.q.transitions(ready.ident)[-1]
    assert done["to_state"] == State.DONE
    assert f"deployed {landed}" in done["reason"]
    assert "provenance installed" in done["reason"]
    assert ready.q.get(ready.ident)["head_sha"] == ready.head, (
        "the landed sha overwrote the head the review and scope records are "
        "keyed by, so a landed task now looks unreviewed")


def test_a_host_that_does_not_hold_the_commit_never_reaches_production(
        tmp_path, monkeypatch):
    """The deploy script's exit code says it finished; the marker says what is
    on disk. They are not the same claim."""
    ready = _ready_to_ship(tmp_path, prod=True,
                           evidence={"production_probe": "print('PROVED')"})
    _passing_suite(monkeypatch)
    monkeypatch.setattr(gates, "deployed", lambda **k: gates.Gate(
        "deployed", True, "installed", evidence={"sha": k["sha"], "exit": 0}))
    monkeypatch.setattr(gates, "provenance", lambda **k: gates.Gate(
        "provenance", False,
        f"host holds sha={'c' * 40} state=installed, expected {k['sha']} "
        f"installed", evidence={"expected": k["sha"], "marker": {}}))

    def never(**_):
        raise AssertionError("production was asked about a host holding "
                             "something else")

    monkeypatch.setattr(gates, "in_production", never)

    assert _ship(ready) == State.FAILED
    assert ready.q.get(ready.ident)["state"] == State.FAILED
    assert "provenance does not say" in _reasons(ready)


# ------------------------------- the probe, bracketed by the marker it needs
#
# One marker read *before* the probe proves the host held S at that moment and
# nothing about what answered the probe. The probe is therefore read the way
# the suite is: the host is asked again afterwards, before the verdict is used,
# and must still be holding S.


def _deploy_and_probe(monkeypatch, *, marker, probe):
    """The gates below the landing, wired from two callables."""
    _passing_suite(monkeypatch)
    monkeypatch.setattr(gates, "deployed", lambda **k: gates.Gate(
        "deployed", True, "installed", evidence={"sha": k["sha"], "exit": 0}))
    monkeypatch.setattr(gates, "provenance", marker)
    monkeypatch.setattr(gates, "in_production", probe)


def _installed(sha: str) -> "gates.Gate":
    return gates.Gate("provenance", True, f"the host holds {sha[:12]}, "
                      f"state=installed",
                      evidence={"expected": sha, "marker": {"sha": sha}})


def _holds_something_else(sha: str) -> "gates.Gate":
    other = "c" * 40
    return gates.Gate("provenance", False,
                      f"host holds sha={other} state=installed, expected {sha} "
                      f"installed",
                      evidence={"expected": sha, "marker": {"sha": other}})


def _probing_task(tmp_path, **kw):
    return _ready_to_ship(tmp_path, prod=True,
                          evidence={"production_probe": "print('PROVED')"},
                          **kw)


def test_the_marker_is_read_before_and_after_the_probe(tmp_path, monkeypatch):
    """The happy path states the bracket: two reads of the same sha, one on
    either side of the probe."""
    ready = _probing_task(tmp_path)
    order: list[str] = []

    def marker(**k):
        order.append(f"provenance {k['sha']}")
        return _installed(k["sha"])

    def probe(**_):
        order.append("probe")
        return gates.Gate("in_production", True, "PROVED")

    _deploy_and_probe(monkeypatch, marker=marker, probe=probe)

    assert _ship(ready) == State.DONE
    landed = _git_in(ready.repo, "rev-parse", "main")
    assert order == [f"provenance {landed}", "probe", f"provenance {landed}"]


def test_a_probe_answered_by_other_bytes_is_not_verification(tmp_path,
                                                             monkeypatch):
    """The window this exists for. Another deployment lands after the marker is
    read and before the probe finishes, so `PROVED` describes whatever that
    deployment installed. Recording it as verification of the landed commit
    would mark the task DONE on a measurement of somebody else's code."""
    ready = _probing_task(tmp_path)
    reads: list[str] = []

    def marker(**k):
        reads.append(k["sha"])
        return _installed(k["sha"]) if len(reads) == 1 \
            else _holds_something_else(k["sha"])

    _deploy_and_probe(monkeypatch, marker=marker,
                      probe=lambda **_: gates.Gate("in_production", True,
                                                   "PROVED"))

    assert _ship(ready) == State.BLOCKED
    landed = _git_in(ready.repo, "rev-parse", "main")
    row = ready.q.get(ready.ident)
    assert row["state"] == State.BLOCKED, \
        "a probe of another version was accepted as verification of the landing"
    assert len(reads) == 2, "the marker was not read back after the probe"
    reasons = _reasons(ready)
    assert f"no longer holds {landed}" in reasons
    assert f"QEVIK_DEPLOY_SHA={landed}" in reasons
    assert not any(t["to_state"] == State.DONE
                   for t in ready.q.transitions(ready.ident))


def test_a_failing_probe_from_other_bytes_is_not_the_tasks_failure(tmp_path,
                                                                   monkeypatch):
    """The recheck is read before the verdict is, so it catches the mirror case
    too: a probe that failed against another deployment's code must not be
    recorded as this commit failing in production."""
    ready = _probing_task(tmp_path)
    reads: list[str] = []

    def marker(**k):
        reads.append(k["sha"])
        return _installed(k["sha"]) if len(reads) == 1 \
            else _holds_something_else(k["sha"])

    _deploy_and_probe(monkeypatch, marker=marker,
                      probe=lambda **_: gates.Gate("in_production", False,
                                                   "NOT PROVED"))

    assert _ship(ready) == State.BLOCKED, \
        "the task was blamed for a probe that measured other bytes"
    assert "no longer holds" in _reasons(ready)


def test_a_marker_unreadable_after_the_probe_is_not_a_pass(tmp_path,
                                                           monkeypatch):
    """A host that cannot be reached after the probe leaves the probe's answer
    unattributable. Unmeasured is never a pass, and after the landing it is
    BLOCKED rather than a requeue."""
    ready = _probing_task(tmp_path)
    reads: list[str] = []

    def marker(**k):
        reads.append(k["sha"])
        if len(reads) == 1:
            return _installed(k["sha"])
        return gates.Gate("provenance", False,
                          "could not reach the host: timed out",
                          unmeasured=True,
                          evidence={"expected": k["sha"], "marker": {}})

    _deploy_and_probe(monkeypatch, marker=marker,
                      probe=lambda **_: gates.Gate("in_production", True,
                                                   "PROVED"))

    assert _ship(ready) == State.BLOCKED
    reasons = _reasons(ready)
    assert "provenance after the probe" in reasons
    assert "could not reach the host" in reasons


def test_a_production_check_without_a_deploy_reads_no_marker(tmp_path,
                                                             monkeypatch):
    """The bracket belongs to a task that installed something. A task that only
    verifies production never wrote the marker, which names whatever the host
    was already holding — asking it about this commit would refuse for a reason
    that has nothing to do with the probe."""
    ready = _probing_task(tmp_path, deploy=False)

    def never(**_):
        raise AssertionError("the marker was read for a task that never "
                             "deployed")

    _passing_suite(monkeypatch)
    monkeypatch.setattr(gates, "deployed", never)
    monkeypatch.setattr(gates, "provenance", never)
    monkeypatch.setattr(gates, "in_production",
                        lambda **_: gates.Gate("in_production", True, "PROVED"))

    assert _ship(ready) == State.DONE


def test_a_post_landing_gate_nobody_could_measure_is_not_a_rebuild(tmp_path,
                                                                   monkeypatch):
    """`_infra` requeues, and after the landing that is a rebuild: the branch is
    gone and the work is already on `main`, so the next run builds the same task
    again from scratch."""
    ready = _ready_to_ship(tmp_path)
    _passing_suite(monkeypatch)
    monkeypatch.setattr(gates, "deployed", lambda **k: gates.Gate(
        "deployed", True, "installed", evidence={"sha": k["sha"], "exit": 0}))
    monkeypatch.setattr(gates, "provenance", lambda **k: gates.Gate(
        "provenance", False, "could not reach the host: timed out",
        unmeasured=True, evidence={"expected": k["sha"], "marker": {}}))

    assert _ship(ready) == State.BLOCKED
    landed = _git_in(ready.repo, "rev-parse", "main")
    row = ready.q.get(ready.ident)
    assert row["state"] == State.BLOCKED, "the task was requeued for a rebuild"
    reasons = _reasons(ready)
    assert f"landed as {landed}" in reasons
    assert f"QEVIK_DEPLOY_SHA={landed}" in reasons


# ------------------------------------------------------ the gates themselves


def test_a_deploy_with_no_commit_to_ship_runs_nothing(monkeypatch):
    """A gate that cannot name what it would deploy must not start a deploy."""
    def never(*a, **k):
        raise AssertionError("the deploy script ran without a commit")

    monkeypatch.setattr(gates, "_sh", never)
    for bad in ("", "main", "abc123", "z" * 40, "A" * 40):
        g = gates.deployed(cwd=Path("."), sha=bad)
        assert g.passed is False and g.detail == "no commit to deploy", bad


def test_the_deploy_gate_passes_the_sha_and_nothing_else(monkeypatch):
    seen: dict = {}

    def capture(argv, **kwargs):
        seen["argv"] = argv
        seen.update(kwargs)
        return 0, "installed and verified", False

    monkeypatch.setattr(gates, "_sh", capture)
    sha = "a" * 40
    g = gates.deployed(cwd=Path("."), sha=sha)
    assert g.passed is True
    assert seen["argv"] == ["./infra/deploy_control.sh"]
    assert seen["env"] == {"QEVIK_DEPLOY_SHA": sha}, (
        "the deploy child is handed something other than the one sha")
    assert seen["timeout"] >= 3600, (
        "the gate gives up before the script's own worst case, and a deploy "
        "still writing to the host would be killed mid-copy")
    assert g.evidence == {"sha": sha, "exit": 0}


def test_the_deploy_child_sees_only_the_sha_it_was_given(tmp_path, monkeypatch):
    """A `QEVIK_TEST_HOST=1` left in the operator's shell would redirect a
    production deploy at its test seams. It cannot reach the child."""
    monkeypatch.setenv("QEVIK_TEST_HOST", "1")
    argv = ["sh", "-c", "echo $QEVIK_DEPLOY_SHA-$QEVIK_TEST_HOST"]

    code, out, _ = gates._sh(argv, cwd=tmp_path, timeout=30,
                             env={"QEVIK_DEPLOY_SHA": "abc"})
    assert code == 0 and out.strip() == "abc-"

    # Negative control: without `env` nothing is filtered and behaviour is
    # exactly what it was.
    _, inherited, _ = gates._sh(argv, cwd=tmp_path, timeout=30)
    assert inherited.strip() == "-1"


def test_a_timed_out_child_does_not_outlive_the_gate(tmp_path):
    """`subprocess.run`'s timeout kills the direct child only. For the deploy
    that leaves `ssh`/`rsync` writing to the host after the driver has given up
    and called the gate unmeasured."""
    import os
    import time as clock

    pidfile = tmp_path / "PIDFILE"
    code, _, timed_out = gates._sh(
        ["sh", "-c", f'sleep 30 & echo $! > "{pidfile}"; wait'],
        cwd=tmp_path, timeout=1)
    assert timed_out is True and code == 124

    stray = int(pidfile.read_text().strip())
    for _ in range(100):
        try:
            os.kill(stray, 0)
        except (ProcessLookupError, PermissionError):
            break
        clock.sleep(0.05)
    else:
        raise AssertionError(
            f"pid {stray} outlived the timeout: the gate reported unmeasured "
            f"while its grandchild was still writing to the host")


_S = "a" * 40
_OTHER = "b" * 40


@pytest.fixture(autouse=True)
def _a_configured_control_plane(tmp_path_factory, monkeypatch):
    """The gates read a target from `infra/deploy_targets.conf`; give them one.

    There is no default host any more — a machine that has not been told which
    production host to look at reports `unmeasured` rather than reaching for
    whichever host used to be production. The gate tests are about what the
    gates *decide*, so they run with a target configured; the two tests that are
    about the absent-target case unset it themselves.
    """
    root = tmp_path_factory.mktemp("target")
    key = root / "id"
    key.write_text("not a real key\n")
    conf = root / "targets.conf"
    conf.write_text(f"test-host|root@127.0.0.1|{key}|a fixture host\n")
    monkeypatch.setenv("QEVIK_TARGETS_FILE", str(conf))
    monkeypatch.setenv("QEVIK_DEPLOY_TARGET", "test-host")
    yield


@pytest.mark.parametrize("marker,passes,in_detail", [
    (f"sha={_S}\nstate=installed", True, ""),
    (f"sha={_S}\ninstalled_at=2026-09-02T10:00Z\nstate=installed", True, ""),
    (f"sha={_S}\nstate=rolled-back", False, "rolled-back"),
    (f"sha={_S}\nstate=installing", False, "installing"),
    (f"sha={_OTHER}\nstate=installed", False, _OTHER),
    ("state=missing", False, "no provenance recorded on the host"),
    ("", False, "no provenance recorded on the host"),
    # The sha is in the text, and not on the line that decides. A substring
    # search would pass this; a parser cannot.
    (f"attempted_sha={_S}\nsha={_OTHER}\nstate=installed", False, _OTHER),
])
def test_provenance_is_read_from_the_marker_lines(monkeypatch, marker, passes,
                                                  in_detail):
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: (0, marker, False))
    g = gates.provenance(sha=_S)
    assert g.passed is passes and g.unmeasured is False
    assert in_detail in g.detail
    if not passes:
        assert _S in g.detail or "no provenance" in g.detail


@pytest.mark.parametrize("marker,duplicate", [
    (f"sha={_S}\nstate=rolled-back\nstate=installed", "state"),
    (f"sha={_OTHER}\nsha={_S}\nstate=installed", "sha"),
    (f"sha={_S}\nstate=installed\ninstalled_at=x\ninstalled_at=y",
     "installed_at"),
    # A duplicate that agrees with itself is still a duplicate: the marker has
    # exactly one writer and never legitimately repeats a key.
    (f"sha={_S}\nstate=installed\nstate=installed", "state"),
])
def test_a_marker_that_says_a_thing_twice_fails_closed(monkeypatch, marker,
                                                       duplicate):
    """The parser defect from attempt 1's third round. Built into a dict, the
    last value wins — so `state=rolled-back` followed by `state=installed`
    passed, and a host that had rolled back read as a host holding the commit."""
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: (0, marker, False))
    g = gates.provenance(sha=_S)
    assert g.passed is False, "a contradictory marker passed"
    assert g.unmeasured is False, (
        "a marker that was read and is malformed is a failure, not an "
        "unmeasured gate")
    assert g.detail == f"malformed provenance: duplicate {duplicate}"
    assert g.evidence["duplicates"] == [duplicate]


def test_a_host_that_cannot_be_read_is_retried_and_then_unmeasured(monkeypatch):
    monkeypatch.setattr(gates, "_RETRY_PAUSE_S", 0)
    tries: list[int] = []

    def unreachable(*a, **k):
        tries.append(1)
        return 255, "ssh: connect to host port 22: Operation timed out", False

    monkeypatch.setattr(gates, "_sh", unreachable)
    g = gates.provenance(sha=_S)
    assert g.unmeasured is True and g.passed is False
    assert "could not reach the host" in g.detail
    assert len(tries) == 3, "one unreachable read was treated as an answer"

    # And a read that succeeds on the second attempt is not an infrastructure
    # failure.
    answers = [(255, "timed out", False), (0, f"sha={_S}\nstate=installed", False)]
    monkeypatch.setattr(gates, "_sh", lambda *a, **k: answers.pop(0))
    assert gates.provenance(sha=_S).passed is True


def test_provenance_and_production_reach_the_host_the_same_way(monkeypatch):
    """One argv helper, so the key, the host and the connection options cannot
    drift apart between the two gates that use them."""
    seen: list[list[str]] = []
    monkeypatch.setattr(gates, "_sh",
                        lambda argv, **k: (seen.append(argv), (0, "", False))[1])
    gates.provenance(sha=_S)
    gates.in_production(cwd=Path("."), probe="print('PROVED')")
    assert len(seen) == 2, "one of the two gates did not run"
    assert seen[0][:-1] == seen[1][:-1], (
        f"the two gates reach the host differently: {seen[0][:-1]} vs "
        f"{seen[1][:-1]}")
    assert seen[0][-1].startswith(f"cat {gates.MARKER} "), seen[0][-1]
