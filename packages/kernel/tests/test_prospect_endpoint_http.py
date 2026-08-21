"""The prospect endpoint, exercised the way a browser exercises it.

This exists because of a real outage. `_digital` was defined at module scope and
called `_findings`, which lives inside `build_router` as a closure. Every call to
`GET /control/sales/prospects/{id}` raised NameError and the dashboard showed
"Could not load: Internal Server Error" for every prospect.

Nothing in the suite caught it, because the checks called the route function
directly. A direct call skips dependency resolution and response serialisation —
the two things most likely to differ — so these go through the ASGI app.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas_kernel.auth import Scope, User
from atlas_kernel.auth.api import current_user
from atlas_kernel.control import sales


class _Seeded:
    """Somewhere to hang the id of the record that must *not* be a prospect."""

    unaudited: str = ""


ids_module = _Seeded()


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(sales.build_router())
    # Authentication is not what is under test; the request path is. Overriding
    # `requires(...)` does not work — it is a factory returning a fresh function
    # per call, so the override keys on an object no route holds. Every scope
    # check resolves through `current_user`, so that is the one to replace.
    operator = User(id="test", username="test", password_hash="",
                    scopes=list(Scope), disabled=False)
    app.dependency_overrides[current_user] = lambda: operator
    return TestClient(app, raise_server_exceptions=False)


#: Five shapes the endpoint actually meets, all audited so all resolve: a clean
#: one, one with confirmed gaps, one whose verification refuted an earlier
#: finding, one with no website recorded, one reachable only on a landline.
#:
#: The suite runs against `<db>_test`, so without these the checks below skip —
#: and a skipped regression test is how the outage reached production.
SEED = [
    ("Prospect Endpoint Test — audited", "https://audited.test", "052 151 4300"),
    ("Prospect Endpoint Test — gaps", "https://gaps.test", "052 151 4301"),
    ("Prospect Endpoint Test — refuted", "https://refuted.test", "052 151 4302"),
    ("Prospect Endpoint Test — no website", "", "052 151 4303"),
    ("Prospect Endpoint Test — landline", "https://landline.test", "04 123 4567"),
]

#: Audited on purpose is what makes a business a prospect. This one never was.
UNAUDITED = ("Prospect Endpoint Test — never audited", "https://never.test", "052 151 4304")


@pytest.fixture(scope="module")
def ids(client) -> list[str]:
    """Real records through the real repository, in the test database."""
    from atlas_kernel.opportunity.models import Business, BusinessEvent
    from atlas_kernel.opportunity.repository import OpportunityRepository

    repo = OpportunityRepository()
    seeded: list[str] = []
    for index, (name, website, phone) in enumerate(SEED):
        business = repo.save_business(Business(
            name=name, geography="United Arab Emirates", website=website,
            phone=phone, email=f"test{index}@example.test", sources=["endpoint-test"],
            metadata={"category": "food"}))
        seeded.append(business.id)
        observations = [
            {"feature": "contact_form", "status": "present"},
            {"feature": "social_proof", "status": "present"},
            {"feature": "arabic", "status": "not_found"},
            {"feature": "click_to_call", "status": "not_found"},
            {"feature": "whatsapp", "status": "unverified"},
        ]
        repo.record_event(BusinessEvent(
            business_id=business.id, factory="website_audit", kind="website_audited",
            actor="endpoint-test",
            detail={"http_status": 200, "load_ms": 900, "observations": observations}))
        if "refuted" in name:
            repo.record_event(BusinessEvent(
                business_id=business.id, factory="website_audit", kind="claims_verified",
                actor="endpoint-test",
                detail={"claims": [{"feature": "arabic", "verdict": "REFUTED"}]}))

    # Never audited, so it must not appear as a prospect at all.
    never = repo.save_business(Business(
        name=UNAUDITED[0], geography="United Arab Emirates", website=UNAUDITED[1],
        phone=UNAUDITED[2], email="never@example.test", sources=["endpoint-test"],
        metadata={"category": "food"}))
    ids_module.unaudited = never.id

    response = client.get("/control/sales/prospects", params={"size": 100, "sort": "score"})
    assert response.status_code == 200, response.text
    rows = response.json().get("prospects") or response.json().get("items") or []
    live = [r.get("business_id") or r.get("id") for r in rows]
    # Seeded ids first so the checks below always cover the shapes above, then
    # whatever else this database holds.
    return seeded + [i for i in live if i not in seeded]


def test_the_listing_itself_loads(client) -> None:
    assert client.get("/control/sales/prospects").status_code == 200


def test_no_real_prospect_returns_a_server_error(client, ids) -> None:
    """The exact failure. Every real record, not a mock and not one id."""
    broken = []
    for business_id in ids:
        response = client.get(f"/control/sales/prospects/{business_id}")
        if response.status_code != 200:
            broken.append((business_id, response.status_code, response.text[:200]))
    assert not broken, f"{len(broken)} of {len(ids)} prospects failed: {broken[:3]}"


def test_at_least_five_prospects_were_actually_checked(ids) -> None:
    """A green run against an empty table proves nothing, so this cannot skip."""
    assert len(ids) >= 5, f"only {len(ids)} prospects were exercised"


def test_every_prospect_carries_the_blocks_the_console_renders(client, ids) -> None:
    for business_id in ids[:8]:
        body = client.get(f"/control/sales/prospects/{business_id}").json()
        for key in ("digital_opportunities", "media", "builds", "warnings", "demo",
                    "outreach", "score", "identity"):
            assert key in body, f"{business_id} is missing {key}"
        assert isinstance(body["digital_opportunities"], list)
        assert body["media"]["permission"] in sales.MEDIA_PERMISSION
        for job in body["builds"]["jobs"]:
            assert job["state"] in sales.JOB_STATES, job


def test_the_response_is_json_serialisable_end_to_end(client, ids) -> None:
    """A direct function call returns a dict; the app has to encode it."""
    response = client.get(f"/control/sales/prospects/{ids[0]}")
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()


def test_two_prospects_do_not_share_a_payload(client, ids) -> None:
    a = client.get(f"/control/sales/prospects/{ids[0]}").json()
    b = client.get(f"/control/sales/prospects/{ids[1]}").json()
    assert a["identity"]["listing_name"] != b["identity"]["listing_name"]
    assert a["business_id"] != b["business_id"] if "business_id" in a else True


def test_an_unknown_prospect_is_a_404_not_a_500(client) -> None:
    response = client.get("/control/sales/prospects/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404, response.text


def test_a_business_that_was_never_audited_is_excluded_not_broken(client, ids) -> None:
    """No audit means nothing is confirmed in either direction, so it is not a
    prospect. That must be a controlled 404, never a stack trace."""
    assert ids_module.unaudited
    response = client.get(f"/control/sales/prospects/{ids_module.unaudited}")
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "no such prospect"


# --- the block must degrade rather than take the page down -----------------

def test_a_broken_block_costs_the_block_and_not_the_page(client, ids, monkeypatch) -> None:
    """The outage in one line: a helper raised, and the whole page went to 500."""
    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated failure inside the opportunity block")

    monkeypatch.setattr(sales, "_digital", explode)
    response = client.get(f"/control/sales/prospects/{ids[0]}")
    assert response.status_code == 200, "one bad block must not 500 the prospect"
    body = response.json()
    assert body["digital_opportunities"] == []
    assert body["warnings"], "a degraded block must be visible, never silently empty"
    assert body["warnings"][0]["block"] == "digital_opportunities"
    assert body["identity"]["listing_name"], "the rest of the page must still be there"


def test_the_degradation_wrapper_logs_what_it_swallowed(caplog) -> None:
    """Not silently hidden: the traceback reaches the log with the business id."""
    warnings: list[dict] = []
    with caplog.at_level("ERROR"):
        result = sales._safe("block", lambda: 1 / 0, "fallback",
                             business_id="b-123", warnings=warnings)
    assert result == "fallback"
    assert warnings and warnings[0]["block"] == "block"
    assert "b-123" in caplog.text and "ZeroDivisionError" in caplog.text


def test_a_healthy_block_is_returned_untouched() -> None:
    """A wrapper that always returns the fallback would pass every test above."""
    warnings: list[dict] = []
    assert sales._safe("block", lambda: {"ok": True}, {}, business_id="b",
                       warnings=warnings) == {"ok": True}
    assert warnings == []
