"""What Qevik has put on the internet, and whether it is still there.

The commercial stake: a demo URL travels inside an approved outreach message.
A dead demo means a stranger is pointed at nothing, so "we could not check it"
must never be reported as "it is fine", and never as "it is down" either.
"""

from __future__ import annotations

from types import SimpleNamespace

from atlas_kernel.publication.published import (
    DEMO_EVENT,
    PUBLICATION_EVENT,
    Liveness,
    check,
    from_events,
)


def _event(kind: str, **detail) -> dict:
    return {"kind": kind, "detail": detail}


class TestReadingBothWriters:
    def test_it_reads_mission_publications_and_outreach_demos(self) -> None:
        """Two paths publish, and the operator asked what is published — not
        which subsystem published it."""
        found = from_events([
            _event(PUBLICATION_EVENT, url="https://sites.qevik.ai/site-a/",
                   site_id="site-a", at="2026-08-27", mission_id="m-1"),
            _event(DEMO_EVENT, demo_url="https://sites.qevik.ai/demo-b/",
                   slug="demo-b", published_at="2026-08-19"),
        ])

        assert {p.url for p in found} == {
            "https://sites.qevik.ai/site-a/", "https://sites.qevik.ai/demo-b/"}
        assert {p.identifier for p in found} == {"site-a", "demo-b"}

    def test_republishing_the_same_url_is_one_row(self) -> None:
        """The mission pipeline recorded the same address three times. A list
        with one row per event answers how many times we published, when the
        question was what is published."""
        found = from_events([
            _event(PUBLICATION_EVENT, url="https://s.qevik.ai/x/", at="2026-08-27",
                   commit="aaa"),
            _event(PUBLICATION_EVENT, url="https://s.qevik.ai/x/", at="2026-08-28",
                   commit="bbb"),
        ])

        assert len(found) == 1
        assert found[0].commit == "bbb", "the newest publication should win"

    def test_a_demo_is_marked_as_one(self) -> None:
        """Its URL is inside a message somebody approved, which is why its
        liveness is a commercial fact rather than housekeeping."""
        demo, site = from_events([
            _event(DEMO_EVENT, demo_url="https://s.qevik.ai/demo/", slug="d",
                   published_at="2026-08-19"),
            _event(PUBLICATION_EVENT, url="https://s.qevik.ai/site/", at="2026-08-18"),
        ])[0], from_events([
            _event(PUBLICATION_EVENT, url="https://s.qevik.ai/site/", at="2026-08-18"),
        ])[0]

        assert demo.is_demo is True
        assert site.is_demo is False

    def test_unrelated_events_are_ignored(self) -> None:
        found = from_events([
            _event("website_audited", url="https://someone-else.example/"),
            _event("mission_transition", status="complete"),
        ])

        assert found == ()

    def test_an_event_with_no_url_is_skipped_not_guessed_at(self) -> None:
        assert from_events([_event(PUBLICATION_EVENT, site_id="site-a")]) == ()

    def test_newest_first(self) -> None:
        found = from_events([
            _event(DEMO_EVENT, demo_url="https://s/1/", published_at="2026-08-01"),
            _event(DEMO_EVENT, demo_url="https://s/2/", published_at="2026-08-29"),
        ])

        assert [p.url for p in found] == ["https://s/2/", "https://s/1/"]

    def test_a_json_encoded_detail_is_read(self) -> None:
        """Postgres hands `detail` back as text on some drivers. Reading it as a
        dict silently returns nothing at all."""
        import json

        found = from_events([{"kind": DEMO_EVENT, "detail": json.dumps(
            {"demo_url": "https://s/d/", "slug": "d", "published_at": "2026-08-19"})}])

        assert len(found) == 1
        assert found[0].identifier == "d"


class TestTellingDownFromUnreachable:
    def test_a_served_page_is_live(self) -> None:
        assert check(SimpleNamespace(status=200, bytes=1967, error="")) == (
            Liveness.LIVE, 200, "")

    def test_a_server_that_answers_404_is_a_finding(self) -> None:
        """The server spoke. That is an answer, not a failure to reach it."""
        state, status, detail = check(
            SimpleNamespace(status=404, bytes=120, error=""))

        assert state is Liveness.DOWN
        assert status == 404

    def test_a_transport_error_is_never_reported_as_down(self) -> None:
        """"We could not reach it" and "it is not there" are different facts,
        and only the second is a reason to rebuild anything."""
        state, status, detail = check(
            SimpleNamespace(status=0, bytes=0, error="connection reset"))

        assert state is Liveness.UNKNOWN
        assert "connection reset" in detail

    def test_a_200_with_an_empty_body_is_down(self) -> None:
        """The directory is there and the file is not. Reported as live, this
        is a demo URL in an approved message that shows a stranger nothing."""
        state, _, detail = check(SimpleNamespace(status=200, bytes=0, error=""))

        assert state is Liveness.DOWN
        assert "empty body" in detail

    def test_nothing_at_all_is_unknown(self) -> None:
        state, _, _ = check(SimpleNamespace(status=0, bytes=0, error=""))

        assert state is Liveness.UNKNOWN

    def test_a_500_is_down(self) -> None:
        state, status, _ = check(SimpleNamespace(status=500, bytes=50, error=""))

        assert state is Liveness.DOWN
        assert status == 500

    def test_the_default_state_is_unknown(self) -> None:
        """A row nobody has checked must not read as working."""
        found = from_events([
            _event(DEMO_EVENT, demo_url="https://s/d/", published_at="2026-08-19")])

        assert found[0].liveness is Liveness.UNKNOWN


def test_it_publishes_nothing() -> None:
    """Structural. This reads the timeline; a writer here would be a second
    path to the internet beside the two that already exist."""
    import ast
    import inspect

    from atlas_kernel.publication import published

    tree = ast.parse(inspect.getsource(published))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value.value = ""
    source = ast.unparse(tree)

    for forbidden in ("save_", "insert", "commit(", "publish(", "shutil.copy",
                      "open("):
        assert forbidden not in source, (
            f"the published-sites read references {forbidden!r}; it must read "
            "the timeline and never write to it or to a disk")
