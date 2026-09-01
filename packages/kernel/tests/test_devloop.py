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
    ident = q.add(title="t", brief="b", origin="human")
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
    ident = first.add(title="survives", brief="b", origin="human")
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
        q.add(title="something", brief="b", origin="production")
    # Negative control: with evidence it is accepted.
    assert q.add(title="something", brief="b", origin="production",
                 evidence={"row": {"n": 4}})


def test_nothing_secret_reaches_the_database(q):
    ident = q.add(title="deploy with sk-abcdefghijklmnopqrstuvwx12",
                  brief="token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
                  origin="human")
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
    ident = q.add(title="needs smtp", brief="b", origin="human")
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
    ids = [q.add(title=f"t{n}", brief="b", origin="human") for n in range(3)]
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
    ident = q.add(title="t", brief="b", origin="human")
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
        "changed", "tests", "review")
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

    ident = q.add(title="one task", brief="do it", origin="human")
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
    q.add(title="another", brief="b", origin="human")
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
    ident = q.add(title="t", brief="b", origin="human")
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
    ident = q.add(title="t", brief="b", origin="human")
    assert q.review_was_clean(ident) is False, (
        "a task nothing reviewed reported itself clean")


def test_a_round_the_reviewer_objected_to_can_never_land(q):
    ident = q.add(title="t", brief="b", origin="human")
    q.move(ident, State.REVIEWING, review_rounds=1)
    q.record_findings(ident, round=1, sha="a", findings=[
        {"severity": "blocking", "file": "f.py", "claim": "c",
         "why_it_matters": "w", "failure_scenario": "s"}])
    assert q.review_was_clean(ident) is False

    # Negative control: the same task lands once a later round comes back with
    # nothing blocking, so the refusal above is the finding and not a gate
    # that refuses everything.
    q.move(ident, State.REVIEWING, review_rounds=2)
    assert q.review_was_clean(ident) is True


def test_a_minor_finding_does_not_hold_a_task_but_a_major_one_does(q):
    for severity, expected in (("minor", True), ("major", False),
                               ("blocking", False)):
        ident = q.add(title=f"t-{severity}", brief="b", origin="human")
        q.move(ident, State.REVIEWING, review_rounds=1)
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
    ident = q.add(title="t", brief="b", origin="human")
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
