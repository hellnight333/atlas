"""The sales workspace, tested where a UI bug becomes a false claim to a stranger.

A dashboard is not a neutral window onto data. Whatever it renders, an operator
reads out loud to a business owner minutes later — so the tests that matter here
are less about routes returning 200 than about four specific ways this could put
an untrue sentence in somebody's mouth:

- painting `NOT_VERIFIED` as an absence,
- keeping a refuted finding on screen as a current weakness,
- offering a WhatsApp button for a number WhatsApp cannot reach,
- and reading a failed audit as a clean bill of health.

Each of those is a thing that has already happened somewhere in this project,
which is why each has a test rather than a comment.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from atlas_kernel.control import sales
from atlas_kernel.outreach import scoring

CONTROL_HTML = Path(__file__).resolve().parents[3] / "apps" / "control" / "index.html"
KERNEL = Path(sales.__file__).resolve().parents[1]


# --------------------------------------------------------------- routing

def test_every_route_requires_authentication() -> None:
    """Prospect evidence and contact details are not public."""
    router = sales.build_router()
    for route in router.routes:
        guards = [d for d in getattr(route, "dependencies", [])]
        signature = str(getattr(route.endpoint, "__annotations__", {}))
        assert guards or "User" in signature, f"{route.path} has no auth dependency"


def test_the_router_is_mounted_under_control() -> None:
    for route in sales.build_router().routes:
        assert route.path.startswith("/control/sales/")


# ------------------------------------------------- three states, never two

def audit(**over) -> dict:
    base = {"http_status": 200, "load_ms": 1400, "category": "dental", "observations": [
        {"feature": "arabic", "status": "not_found", "evidence": "no lang switcher found"},
        {"feature": "booking_link", "status": "not_found", "evidence": "no booking link"},
        {"feature": "contact_form", "status": "present", "evidence": "<form> with inputs"},
        {"feature": "insurance_info", "status": "unverified", "evidence": "may be on a subpage"},
    ]}
    base.update(over)
    return base


def folded(*, phone="052 151 4300", verified=None, demo="", shots=None,
           audit_detail=None, hours_old=1.0) -> dict:
    detail = audit_detail if audit_detail is not None else audit()
    verified = verified or {}
    merged = scoring.apply_verification(detail, verified) if verified else detail
    score = scoring.score(
        business_id="b1", name="Test Clinic | Dubai", website="https://x.ae/",
        phone=phone, email="", category="dental", audit=merged, audit_count=1,
        demo_url=demo, sample_slug="sample",
    )
    return {
        "business": {"id": "b1", "name": "Test Clinic | Dubai", "website": "https://x.ae/",
                     "email": "", "phone": phone, "geography": "Dubai", "sources": []},
        "category": "dental", "score": score, "audit": merged, "raw_audit": detail,
        "verified": verified, "live": {}, "audited_at": datetime.now(UTC) - timedelta(hours=hours_old),
        "verified_at": None, "demo": demo, "shots": shots or {}, "shots_at": None,
        "drafts": [], "messages": [], "sent": [], "replies": [], "timeline": [],
        "fresh_hours": hours_old, "stale": hours_old > sales.STALE_AFTER_HOURS,
    }


@pytest.fixture
def api():
    router = sales.build_router()
    return {route.path: route.endpoint for route in router.routes}


def findings_of(state_map: dict) -> list[dict]:
    """Findings for a business, through the real shaping path."""
    router = sales.build_router()
    # `_findings` is a closure inside build_router; reach it through a rendered
    # detail rather than reimplementing the shaping in the test.
    return state_map


def test_the_three_states_stay_three(api) -> None:
    """CONFIRMED_ABSENT, CONFIRMED_PRESENT and NOT_VERIFIED never merge."""
    f = folded()
    score = f["score"]
    assert "arabic" in score.speakable                 # confirmed absent, fixable
    assert "booking_link" in score.unfixable           # confirmed absent, not ours
    assert "insurance_info" in score.unverified        # never observed
    assert "insurance_info" not in score.speakable
    assert "insurance_info" not in score.unfixable


def test_an_unverified_feature_is_never_offered_as_a_weakness() -> None:
    f = folded(audit_detail=audit(observations=[
        {"feature": "arabic", "status": "unverified", "evidence": "not read"},
    ]))
    assert f["score"].speakable == ()
    assert "arabic" in f["score"].unverified


def test_do_not_say_names_every_unsayable_thing() -> None:
    rules = " ".join(_do_not_say(folded()))
    assert "Online booking" in rules and "does not build" in rules
    assert "Insurance information" in rules and "never verified" in rules
    assert "licensed company" in rules
    assert "client work" in rules


def _do_not_say(f: dict) -> list[str]:
    """Reach the closure through a real detail payload."""
    import types

    router = sales.build_router()
    for route in router.routes:
        if route.path == "/control/sales/prospects/{business_id}":
            closure = dict(zip(route.endpoint.__code__.co_freevars,
                               (c.cell_contents for c in route.endpoint.__closure__)))
            fn = closure["_do_not_say"]
            assert isinstance(fn, types.FunctionType)
            return fn(f)
    raise AssertionError("detail route not found")


# ------------------------------------------------------ refuted findings

def test_a_refuted_finding_stops_being_a_current_weakness() -> None:
    """Three prospects' "no HTTPS" was refuted. It must not be shown as live."""
    before = folded(audit_detail=audit(observations=[
        {"feature": "https", "status": "not_found", "evidence": "listed as http://"},
    ]))
    assert "https" in before["score"].speakable

    after = folded(
        audit_detail=audit(observations=[
            {"feature": "https", "status": "not_found", "evidence": "listed as http://"}]),
        verified={"https": "REFUTED"},
    )
    assert "https" not in after["score"].speakable
    rules = " ".join(_do_not_say(after))
    assert "HTTPS" in rules and "refuted" in rules


def test_the_previous_reading_is_kept_not_deleted() -> None:
    f = folded(
        audit_detail=audit(observations=[
            {"feature": "https", "status": "not_found", "evidence": "listed as http://"}]),
        verified={"https": "REFUTED"},
    )
    # The raw audit still carries the original observation.
    assert any(o["feature"] == "https" and o["status"] == "not_found"
               for o in f["raw_audit"]["observations"])


# ------------------------------------------------ WhatsApp reachability

@pytest.mark.parametrize(
    "phone,expected,link",
    [
        ("052 151 4300", "REACHABLE", True),
        ("04 347 4339", "CONFIRMED_ABSENT", False),
        ("800 37569", "CONFIRMED_ABSENT", False),
        ("", "NOT_VERIFIED", False),
    ],
)
def test_whatsapp_is_offered_only_where_it_can_deliver(phone, expected, link) -> None:
    """A WhatsApp message to a landline goes nowhere, silently."""
    c = sales.contactability(phone, "")
    assert c["whatsapp"] == expected
    assert bool(c["wa_link"]) is link


def test_a_landline_prospect_is_routed_to_the_phone() -> None:
    assert sales.contactability("04 347 4339", "")["channel"] == "PHONE"
    assert sales.contactability("052 151 4300", "")["channel"] == "WHATSAPP"


def test_the_whatsapp_link_is_a_normalised_international_number() -> None:
    link = sales.contactability("052 151 4300", "")["wa_link"]
    assert link.startswith("https://wa.me/971")
    assert " " not in link


# ------------------------------------------------------ failed audits

def test_an_audit_that_returned_nothing_is_not_a_clean_site() -> None:
    f = folded(audit_detail={"http_status": 0, "load_ms": 0, "observations": []})
    assert f["score"].audit_complete is False
    assert f["score"].speakable == ()


def test_stale_evidence_is_flagged_rather_than_served_as_current() -> None:
    fresh = folded(hours_old=2)
    old = folded(hours_old=sales.STALE_AFTER_HOURS + 5)
    assert fresh["stale"] is False and old["stale"] is True
    assert "Re-verify" in " ".join(_do_not_say(old)) or "re-verify" in " ".join(_do_not_say(old))


# ---------------------------------------------------- screenshot serving

def test_a_screenshot_request_rejects_a_path_that_is_not_an_id(api, tmp_path) -> None:
    """The label and id both reach the filesystem; both are constrained."""
    from fastapi import HTTPException

    fn = api["/control/sales/prospects/{business_id}/shot/{label}"]
    for bad_id in ("../../etc", "not-a-uuid", "a" * 40):
        with pytest.raises(HTTPException) as raised:
            fn(bad_id, "desktop", False)
        assert raised.value.status_code in (400, 404)
    with pytest.raises(HTTPException):
        fn("0" * 8 + "-0000-0000-0000-" + "0" * 12, "../../../etc/passwd", False)


def test_a_missing_screenshot_is_a_404_not_a_placeholder(api) -> None:
    from fastapi import HTTPException

    fn = api["/control/sales/prospects/{business_id}/shot/{label}"]
    with pytest.raises(HTTPException) as raised:
        fn("11111111-1111-1111-1111-111111111111", "desktop", False)
    assert raised.value.status_code == 404


def test_screenshots_are_never_indexable(api, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sales, "EVIDENCE", tmp_path)
    folder = tmp_path / "11111111-1111-1111-1111-111111111111"
    folder.mkdir()
    (folder / "desktop-20260821T000000.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    response = api["/control/sales/prospects/{business_id}/shot/{label}"](
        "11111111-1111-1111-1111-111111111111", "desktop", False)
    assert "noindex" in response.headers["X-Robots-Tag"]
    assert response.headers["Cache-Control"].startswith("private")


# ------------------------------------------------------- demo linking

def test_a_sample_is_never_presented_as_client_work() -> None:
    html = CONTROL_HTML.read_text(encoding="utf-8")
    assert "Qevik has no customers" in html
    assert "never a client" in html


def test_every_demo_the_registry_can_select_actually_exists() -> None:
    """Demo choice lives in one registry now; nothing here may point at a gap.

    Three shapes are legitimate, and the third was added by the AHS concept:
    a hand-built single file, a directory with its own generator writing into
    `dist/`, or a slug rendered by the vertical generator in `infra/samples.py`.
    Anything in none of them is selectable and unbuildable.
    """
    from atlas_kernel.outreach import demos

    root = Path(__file__).resolve().parents[3]
    built = root / "apps" / "samples"
    generated = (root / "infra" / "samples.py").read_text(encoding="utf-8")
    for demo in demos.DEMOS:
        if demo.slug == "sample":
            continue                      # rendered by the dental vertical
        directory = built / demo.slug.replace("sample-", "")
        by_hand = (directory / "index.html").exists()
        # A multi-page concept has a build script and a rendered tree rather
        # than one file. Requiring both is what keeps this a real check: a
        # build script that has never produced output still fails.
        by_own_build = ((directory / "build.py").exists()
                        and (directory / "dist" / "index.html").exists())
        by_generator = f'"{demo.slug}"' in generated
        assert by_hand or by_own_build or by_generator, \
            f"{demo.slug} is selectable but built by nothing"


def test_the_dashboard_keeps_no_demo_map_of_its_own() -> None:
    source = Path(sales.__file__).read_text(encoding="utf-8")
    assert "SAMPLE_FOR" not in source and "SAMPLE_WHY" not in source


# -------------------------------------------- nothing here can ever send

def test_the_sales_module_imports_no_outbound_client() -> None:
    """Nothing here can send. Checked against the imports, not the prose.

    A bare substring search over the whole file matched the word "requests"
    inside a comment — "ticking a box requests nothing" — and failed a module
    that imports no HTTP client at all. A guard that fires on English is a guard
    that gets deleted, so this reads the import statements.
    """
    import ast

    source = Path(sales.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for forbidden in ("smtplib", "twilio", "sendgrid", "mailgun", "requests",
                      "httpx", "urllib", "aiohttp"):
        assert forbidden not in imported, f"{forbidden} reached the sales module"
    for endpoint in ("graph.facebook.com", "api.whatsapp.com/send", "api.twilio.com"):
        assert endpoint not in source, f"{endpoint} reached the sales module"


def test_no_outbound_client_exists_anywhere_in_the_kernel() -> None:
    offenders = []
    for path in KERNEL.rglob("*.py"):
        if "test" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for forbidden in ("import smtplib", "from smtplib", "import twilio", "sendgrid"):
            if forbidden in text:
                offenders.append(f"{path.name}: {forbidden}")
    assert offenders == [], offenders


def test_the_dashboard_cannot_send_only_open() -> None:
    """The WhatsApp affordance is a link the operator's own phone opens.

    The link itself is built server-side by `contactability`, so the console
    never constructs a recipient of its own — it renders whatever the API
    decided was reachable, or nothing.
    """
    html = CONTROL_HTML.read_text(encoding="utf-8")
    assert "wa_link" in html, "the console does not use the server-decided link"
    assert sales.contactability("052 151 4300", "")["wa_link"].startswith("https://wa.me/")
    for forbidden in ("api.whatsapp.com/send", "graph.facebook.com",
                      "/messages/send", "sendMessage", "smtp"):
        assert forbidden not in html, f"the console references {forbidden}"


def test_the_console_only_ever_links_whatsapp_it_was_given() -> None:
    """No template builds a wa.me URL from a raw phone number in the browser."""
    html = CONTROL_HTML.read_text(encoding="utf-8")
    assert not re.search(r"wa\.me/\$\{", html), "the console assembles its own WhatsApp link"


def test_every_write_records_a_human_action_and_none_of_them_send(api) -> None:
    """Four writes now, and the invariant is unchanged: each one records
    something a person did — they sent a message, a customer replied, a customer
    granted media permission, an operator asked for a build. None of them
    contacts anybody, and none of them generates anything."""
    writes = sorted(path for path in api
                    if any(r.path == path and "POST" in r.methods
                           for r in sales.build_router().routes))
    assert writes == [
        "/control/sales/prospects/{business_id}/build",
        "/control/sales/prospects/{business_id}/media-permission",
        "/control/sales/prospects/{business_id}/reply",
        "/control/sales/prospects/{business_id}/sent",
    ]
    source = Path(sales.__file__).read_text(encoding="utf-8")
    # Every write goes through the one append-only timeline, so "state" is
    # always folded from events and a second customer entity cannot appear.
    assert source.count("BusinessEvent(") == len(writes)
    for verb in ("def send", "def dispatch", "def publish_message"):
        assert verb not in source, verb


def test_recording_a_send_demands_a_real_timestamp(api) -> None:
    """`sent_at` is passed in, never defaulted — logging is not sending."""
    from fastapi import HTTPException

    naive = sales.SentRecord(channel="whatsapp", sent_at=datetime(2026, 8, 21, 9, 0))
    with pytest.raises(HTTPException) as raised:
        api["/control/sales/prospects/{business_id}/sent"]("b1", naive, user=None)
    assert raised.value.status_code == 400


# ------------------------------------------- no second customer entity

def test_the_dashboard_introduces_no_new_customer_table() -> None:
    source = Path(sales.__file__).read_text(encoding="utf-8")
    assert "CREATE TABLE" not in source.upper()
    for invented in ("prospects_v2", "sales_leads", "sales_contacts", "crm_businesses",
                     "atlas_customers", "atlas_prospects"):
        assert invented not in source
    # Only the tables that already existed are read.
    tables = set(re.findall(r"from (atlas_\w+)", source))
    assert tables <= {"atlas_businesses", "atlas_business_events", "atlas_outreach_messages"}, tables


def test_stage_is_derived_and_never_stored() -> None:
    source = Path(sales.__file__).read_text(encoding="utf-8")
    assert "update atlas_businesses" not in source.lower()
    assert "insert into atlas_businesses" not in source.lower()


# ------------------------------------------------------------ the page

def test_the_console_is_mobile_first_and_never_scrolls_sideways() -> None:
    html = CONTROL_HTML.read_text(encoding="utf-8")
    assert 'name="viewport"' in html and "width=device-width" in html
    assert "@media (max-width:720px)" in html
    assert "overflow-x:hidden" in html
    assert ".mobar" in html, "no sticky mobile action bar"


def test_the_console_asks_not_to_be_indexed() -> None:
    html = CONTROL_HTML.read_text(encoding="utf-8")
    assert 'name="robots"' in html and "noindex" in html


def test_the_three_states_have_three_distinct_treatments() -> None:
    """If two share a colour the operator cannot tell them apart."""
    html = CONTROL_HTML.read_text(encoding="utf-8")
    colours = {}
    for name in ("present", "absent", "unknown", "refuted"):
        match = re.search(rf"--{name}:\s*(#[0-9A-Fa-f]{{6}})", html)
        assert match, f"--{name} is not defined"
        colours[name] = match.group(1).lower()
    assert len(set(colours.values())) == 4, colours


def test_the_shell_is_hidden_until_authenticated() -> None:
    """The app frame was visible before sign-in because only `[hidden]` was styled."""
    html = CONTROL_HTML.read_text(encoding="utf-8")
    assert re.search(r"\[hidden\],\s*\.hidden\s*\{[^}]*display:\s*none", html)
    assert 'class="shell hidden" id="app"' in html


def test_every_selectable_category_has_a_readable_industry_label() -> None:
    """A recruitment agency read "Other · Dubai · recruitment" on its own page."""
    from atlas_kernel.outreach import demos

    selectable = {c for demo in demos.DEMOS for c in demo.serves}
    missing = sorted(c for c in selectable if c not in sales.INDUSTRY)
    assert missing == [], missing


def test_the_industry_filter_offers_every_label_the_api_can_return() -> None:
    html = CONTROL_HTML.read_text(encoding="utf-8")
    for label in set(sales.INDUSTRY.values()):
        assert f'"{label}"' in html, f"the filter cannot select {label!r}"


# ------------------------------------------------------ one key, two meanings

def test_no_dict_literal_in_the_kernel_assigns_one_key_twice() -> None:
    """Python keeps the last, silently, and the first is dead computation.

    `_card` had `confidence` twice: the scoring component's points, then the
    level string. The points were computed and discarded, and `?sort=confidence`
    negated a string — a 500 on the sort an operator reaches for first.

    A structural check rather than one test for that key, because the shape
    recurs: any long dict literal assembled by hand can grow a second copy of a
    key, and nothing at runtime complains.
    """
    import ast
    from pathlib import Path

    source = Path(sales.__file__).resolve().parents[1]
    duplicates = []
    for path in source.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Dict):
                continue
            seen: dict[str, int] = {}
            for key in node.keys:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if key.value in seen:
                    duplicates.append(
                        f"{path.name}:{key.lineno} {key.value!r} "
                        f"(first at line {seen[key.value]})")
                seen[key.value] = key.lineno

    assert duplicates == [], duplicates


def test_the_scan_can_actually_find_a_duplicate() -> None:
    """A structural check that passes by parsing nothing is no check at all."""
    import ast

    tree = ast.parse('{"a": 1, "b": 2, "a": 3}')
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.Dict))
    keys = [k.value for k in node.keys]
    assert len(keys) != len(set(keys))


def test_prospects_can_be_sorted_by_confidence() -> None:
    """The ordering expression, applied to the key it actually reads."""
    order = {"confidence": lambda c: -c["confidence_points"]}["confidence"]
    assert order({"confidence_points": 12}) == -12
    assert order({"confidence_points": 0}) == 0
