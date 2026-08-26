"""The cleanup, and the things it must refuse to do.

A mission's commits now live only on its branch — the scratch clone is the sole
copy — so a branch is not clutter, it is an artefact awaiting promotion.
Deleting one belonging to a live mission destroys work somebody is waiting to
review. These tests are mostly about the refusals.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "prune_mission_branches", ROOT / "infra" / "prune_mission_branches.py")
prune = importlib.util.module_from_spec(_spec)
sys.modules["prune_mission_branches"] = prune
_spec.loader.exec_module(prune)

LIVE = "mission-aaaaaaaaaaaa"
STALE = "mission-bbbbbbbbbbbb"
CITED = "mission-cccccccccccc"


def git(*args: str, cwd: Path) -> str:
    env = dict(os.environ) | {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@q.local",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@q.local"}
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=True, env=env).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    where = tmp_path / "repo"
    where.mkdir()
    git("init", "-b", "main", ".", cwd=where)
    (where / "f.txt").write_text("x\n")
    git("add", ".", cwd=where)
    git("commit", "-m", "initial", cwd=where)
    for branch in (f"mission/{LIVE}", f"mission/{STALE}", f"mission/{CITED}",
                   "feature/keep-me", "release/2026-08"):
        git("branch", branch, cwd=where)
    return where


@pytest.fixture
def timeline(tmp_path) -> Path:
    path = tmp_path / "missions.jsonl"
    path.write_text(json.dumps(
        {"kind": "mission", "detail": {"mission_id": LIVE, "status": "queued"}}) + "\n")
    return path


def branches(repo: Path) -> set[str]:
    return {line.strip(" *") for line in git("branch", "--list", cwd=repo).splitlines()
            if line.strip()}


# ------------------------------------------------------------- what it deletes

def test_a_branch_no_source_mentions_is_provably_stale(repo, timeline):
    verdicts = prune.assess(repo, prune.known_missions([timeline], []))
    stale = {v.mission_id for v in verdicts if v.stale}
    assert STALE in stale


def test_a_live_missions_branch_is_protected(repo, timeline):
    verdicts = prune.assess(repo, prune.known_missions([timeline], []))
    live = next(v for v in verdicts if v.mission_id == LIVE)
    assert not live.stale
    assert "artefact awaiting promotion" in live.because


def test_a_mission_only_a_report_mentions_is_protected(repo, timeline, tmp_path):
    """A completed mission may be gone from a rotated timeline and still be the
    thing a report is about."""
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "r.md").write_text(f"# done\n\n**Mission:** `{CITED}`\n")
    verdicts = prune.assess(repo, prune.known_missions([timeline], [reports]))
    cited = next(v for v in verdicts if v.mission_id == CITED)
    assert not cited.stale


@pytest.mark.parametrize("branch", ["feature/keep-me", "release/2026-08", "main"])
def test_it_never_considers_a_branch_that_is_not_a_mission(repo, timeline, branch):
    verdicts = prune.assess(repo, prune.known_missions([timeline], []))
    assert branch not in {v.branch for v in verdicts}


# ------------------------------------------------------------ what it refuses

def test_with_no_sources_at_all_nothing_is_stale(repo):
    """An empty set of known missions makes every branch look unreferenced,
    which is the most dangerous possible reading of "I found nothing"."""
    verdicts = prune.assess(repo, prune.known_missions([], []))
    assert verdicts
    assert not any(v.stale for v in verdicts)
    assert all("proves nothing" in v.because for v in verdicts)


def test_a_missing_timeline_protects_everything(repo, tmp_path):
    known = prune.known_missions([tmp_path / "not-there.jsonl"], [])
    assert not known.trustworthy
    assert not any(v.stale for v in prune.assess(repo, known))


def test_an_unparsable_timeline_protects_everything(repo, tmp_path):
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json at all\n")
    known = prune.known_missions([broken], [])
    assert not known.trustworthy
    assert not any(v.stale for v in prune.assess(repo, known))


def test_an_empty_but_readable_timeline_is_evidence(repo, tmp_path):
    """The distinction that matters. A timeline that exists and parses says
    "this deployment records missions here, and there are none". A missing one
    says "you may be looking in the wrong place"."""
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    known = prune.known_missions([empty], [])
    assert known.trustworthy
    assert all(v.stale for v in prune.assess(repo, known))


def test_a_dry_run_changes_nothing(repo, timeline, capsys):
    before = branches(repo)
    assert prune.main(["--repository", str(repo), "--timeline", str(timeline)]) == 0
    assert branches(repo) == before
    assert "DRY RUN" in capsys.readouterr().out


def test_apply_without_evidence_deletes_nothing(repo, capsys):
    before = branches(repo)
    assert prune.main(["--repository", str(repo), "--apply"]) == 0
    assert branches(repo) == before


def test_apply_with_evidence_deletes_only_the_proven(repo, timeline):
    before = branches(repo)
    assert prune.main(["--repository", str(repo), "--timeline", str(timeline),
                       "--apply"]) == 0
    after = branches(repo)
    assert after == before - {f"mission/{STALE}", f"mission/{CITED}"}
    assert f"mission/{LIVE}" in after
    assert "feature/keep-me" in after
    assert "main" in after


# ------------------------------------------------------------------ the guards

def test_the_git_allow_list_has_no_push_or_rewrite():
    for forbidden in ("push", "reset", "rebase", "filter-branch", "gc", "remote"):
        assert forbidden not in prune.ALLOWED


def test_a_subcommand_nobody_listed_is_refused(repo):
    with pytest.raises(prune.PruneError, match="not permitted"):
        prune.git(repo, "push", "origin", "main")


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path, capsys):
    (tmp_path / "plain").mkdir()
    assert prune.main(["--repository", str(tmp_path / "plain")]) == 2


def test_the_worktree_hint_is_information_not_a_rule(repo, tmp_path):
    """A worktree under /tmp says "probably a harness run", which is useful to
    the person deciding and is not proof. It must never make a branch stale by
    itself."""
    registered = repo / ".git" / "worktrees" / STALE
    registered.mkdir(parents=True)
    (registered / "gitdir").write_text(
        f"/tmp/qevik-e2e-xyz/worktrees/mission/{STALE}/.git\n")

    verdicts = prune.assess(repo, prune.known_missions([], []))
    hinted = next(v for v in verdicts if v.mission_id == STALE)
    assert "harness run" in hinted.hint
    assert not hinted.stale, "a hint about a path decided a deletion"
