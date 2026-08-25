"""Claiming, tested on the distinction the whole thing exists to preserve.

There are two questions and they have different answers:

1. Is the algorithm correct? `PostgresClaims` — yes, `SELECT … FOR UPDATE SKIP
   LOCKED` is the right answer and it is written out.
2. Has anybody watched it work? No. There is no database here.

Conflating those would produce the exact failure this module is about: a
deployment that believes it has multi-worker safety, runs two workers, and
commits the same change twice on two branches with two reports.

So there is deliberately **no test double that makes multi-worker correctness
pass**. A fake that appeared to serialise two processes would prove a property
the deployment does not have, which is worse than the gap it papers over.
"""

from __future__ import annotations

import threading

import pytest

from atlas_kernel.mission.claims import (
    CLAIM_SQL,
    Claims,
    LocalClaims,
    NotVerified,
    PostgresClaims,
    describe,
    verified,
)

# ============================================ the supported configuration

def test_one_worker_claims_and_a_second_is_refused() -> None:
    claims = LocalClaims()
    assert claims.acquire("mission-1", worker="a") is True
    assert claims.acquire("mission-1", worker="b") is False
    assert claims.holder("mission-1") == "a"


def test_the_holder_may_reclaim_its_own_mission() -> None:
    """A worker retrying its own mission must not lock itself out."""
    claims = LocalClaims()
    claims.acquire("mission-1", worker="a")
    assert claims.acquire("mission-1", worker="a") is True


def test_releasing_frees_it_for_somebody_else() -> None:
    claims = LocalClaims()
    claims.acquire("mission-1", worker="a")
    claims.release("mission-1", worker="a")
    assert claims.acquire("mission-1", worker="b") is True


def test_releasing_a_mission_you_do_not_hold_changes_nothing() -> None:
    """A no-op, not an error: a worker cleaning up after a crash should not
    have to know whether it got as far as claiming."""
    claims = LocalClaims()
    claims.acquire("mission-1", worker="a")
    claims.release("mission-1", worker="b")
    assert claims.holder("mission-1") == "a"


def test_threads_in_one_process_cannot_double_claim() -> None:
    """The case `LocalClaims` genuinely fixes. Without the lock, two threads
    reading and writing a dict interleave and both win."""
    claims = LocalClaims()
    won: list[str] = []
    barrier = threading.Barrier(8)

    def race(name: str) -> None:
        barrier.wait()
        if claims.acquire("mission-1", worker=name):
            won.append(name)

    threads = [threading.Thread(target=race, args=(f"w{i}",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(won) == 1, f"{len(won)} workers claimed one mission: {won}"


# ============================================ the gap, stated rather than faked

def test_the_local_implementation_does_not_claim_to_be_multiprocess_safe() -> None:
    """It is a dict in one process. A second worker has its own."""
    assert LocalClaims().multiprocess_safe is False


def test_the_postgres_implementation_refuses_to_be_used_unverified() -> None:
    """Its failure mode is not an exception — it is two workers quietly running
    one mission, which looks like the system working until two commits appear."""
    with pytest.raises(NotVerified, match="has not been demonstrated"):
        PostgresClaims(connection=object())


def test_correct_and_demonstrated_are_tracked_separately() -> None:
    """`multiprocess_safe` is about the algorithm. `verified` is about whether
    anybody watched it run. The architecture rests on not merging them — they
    are still two questions even now that both answers are yes."""
    local = LocalClaims()
    assert verified(local) is True
    assert local.multiprocess_safe is False, (
        "a dict in one process; a second worker has its own")

    postgres = PostgresClaims(connection=object(), i_have_a_database=True)
    assert postgres.multiprocess_safe is True


def test_the_claim_of_verification_names_the_run_that_earned_it() -> None:
    """`verified()` turned True for `PostgresClaims` on 25 August 2026. A claim
    like that with nothing behind it is precisely what this module exists to
    prevent, so the evidence is named in the source and a reader can go and
    check it."""
    from atlas_kernel.mission.claims import DEMONSTRATED_BY

    assert verified(PostgresClaims(connection=object(),
                                   i_have_a_database=True)) is True
    for named in ("infra/verify_postgres_claims.py", "PostgreSQL",
                  "qevik-core-01", "postgres_claims_verification.txt"):
        assert named in DEMONSTRATED_BY, named


def test_the_recorded_evidence_exists_and_says_it_passed() -> None:
    """The pointer must not outlive the file. A `DEMONSTRATED_BY` naming a
    report nobody can open is a citation, not evidence."""
    from pathlib import Path

    report = (Path(__file__).resolve().parents[3] / "docs" / "qevik-docs"
              / "autonomous" / "reports" / "postgres_claims_verification.txt")
    assert report.is_file(), f"{report} is named in DEMONSTRATED_BY and missing"
    text = report.read_text(encoding="utf-8")
    assert "0 failed" in text
    assert "exactly one worker claimed it" in text


def test_an_autocommit_connection_is_refused() -> None:
    """`FOR UPDATE SKIP LOCKED` holds its lock until the transaction ends. On an
    autocommit connection that is the semicolon, so the lock is gone before the
    claim is recorded and two workers claim one mission — with no error, which
    is the whole danger."""
    class Loose:
        autocommit = True

    with pytest.raises(NotVerified, match="autocommit"):
        PostgresClaims(connection=Loose(), i_have_a_database=True)


def test_a_transactional_connection_is_accepted() -> None:
    """The negative control: if every connection were refused, the check above
    would be measuring nothing."""
    class Proper:
        autocommit = False

    assert PostgresClaims(connection=Proper(),
                          i_have_a_database=True).multiprocess_safe is True


def test_the_description_says_what_this_deployment_actually_guarantees() -> None:
    local = describe(LocalClaims())
    assert local["status"] == "SINGLE_WORKER_ONLY"
    assert "run one" in local["detail"]

    postgres = describe(PostgresClaims(connection=object(),
                                       i_have_a_database=True))
    assert postgres["status"] == "COMPLETE"
    assert "Two workers can run safely" in postgres["detail"]


def test_no_fake_makes_multiprocess_safety_pass() -> None:
    """The absence is the point.

    A double that appeared to serialise two processes would prove a property
    the deployment does not have. If one is ever added, this test should be
    deleted deliberately rather than quietly satisfied.
    """
    from pathlib import Path

    from atlas_kernel.mission import claims as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for shape in ("class FakeClaims", "class InMemoryPostgres",
                  "class StubClaims"):
        assert shape not in source, shape


# ============================================ the SQL is reviewable

def test_the_statement_that_makes_this_correct_is_readable() -> None:
    """Module level, not buried in a method, so it can be reviewed and turned
    into a migration without instantiating anything."""
    assert "FOR UPDATE SKIP LOCKED" in CLAIM_SQL
    assert "%(mission_id)s" in CLAIM_SQL, "parameterised, never interpolated"


def test_the_claim_query_takes_a_staleness_bound() -> None:
    """A worker that died holding a claim must not hold it forever."""
    assert "stale_before" in CLAIM_SQL


def test_both_implementations_satisfy_the_protocol() -> None:
    assert isinstance(LocalClaims(), Claims)
    assert isinstance(PostgresClaims(connection=object(),
                                     i_have_a_database=True), Claims)


# ============================================ what the deployment actually gets

def test_no_dsn_means_one_worker_rather_than_a_database_that_is_not_there() -> None:
    from atlas_kernel.qevik.app import _claims_for

    assert isinstance(_claims_for(""), LocalClaims)
    assert isinstance(_claims_for("   "), LocalClaims)


def test_an_unreachable_database_falls_back_loudly(caplog) -> None:
    """Falling back is right — refusing to start takes the whole control plane
    down over a capability only the worker needs. Falling back *silently* is
    not: the operator would believe two workers were safe."""
    import logging

    from atlas_kernel.qevik.app import _claims_for

    with caplog.at_level(logging.ERROR):
        claims = _claims_for("postgresql://nobody@127.0.0.1:1/none")
    assert isinstance(claims, LocalClaims)
    assert any("NOT safe for two workers" in r.getMessage()
               for r in caplog.records), (
        "a silent fallback is how a deployment believes it has multi-worker "
        "safety it does not have")


def test_health_reports_which_claiming_is_in_use() -> None:
    """So "we are running two workers" is a claim the operator can check rather
    than assume."""
    from fastapi.testclient import TestClient

    from atlas_kernel.qevik.app import Wiring, create_app

    with TestClient(create_app(Wiring())) as client:
        body = client.get("/api/health").json()
    claiming = body["components"]["claiming"]
    assert claiming["implementation"] == "LocalClaims"
    assert claiming["status"] == "SINGLE_WORKER_ONLY"
    assert claiming["multiprocess_safe"] is False
