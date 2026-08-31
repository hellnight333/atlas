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
    assert boundary.classify("this needs a product decision") == "decision"
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
    assert '"--base", base_sha' in source


def test_the_reviewer_runs_on_an_immutable_git_range():
    source = Path(INFRA / "devloop" / "agents.py").read_text()
    call = source[source.index('"codex", "exec", "review"'):][:300]
    assert '"--base", base_sha' in call, "the review unit is not a git range"
    assert '"--json"' in call, "the review is not read as structured events"


@pytest.mark.parametrize("text,expect", [
    ("- [P1] A thing — /x/y.py:3-3\n  because of z", "DEFECTS_FOUND"),
    ("I found no issues in this diff.", "CLEAN"),
])
def test_a_review_is_read_from_what_the_reviewer_actually_wrote(text, expect):
    parsed = agents.parse_review(text, repo=Path("/x"))
    assert parsed and parsed["verdict"] == expect


def test_an_unreadable_review_is_never_clean():
    """Fails closed. The one failure that ships unreviewed code silently."""
    assert agents.parse_review("...unexpected shape...", repo=Path(".")) is None
    assert agents.parse_review("", repo=Path(".")) is None


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


def test_the_evaluation_queue_holds_third_party_projects_unassessed(q):
    """Nothing is integrated before somebody has looked at it."""
    first = q.add_evaluation(name="Camofox", url="https://example.test/camofox",
                             why="browser automation")
    again = q.add_evaluation(name="Camofox", url="https://example.test/camofox",
                             why="duplicate")
    assert first == again, "the evaluation queue is not idempotent"
    assert q.evaluations()[0]["state"] == "UNEVALUATED"
