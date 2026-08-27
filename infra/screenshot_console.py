#!/usr/bin/env python3
"""Look at the console, at both viewports, instead of asserting it is fine.

Every visual defect in this project was found by reading a screenshot and none
were found by a test: a completion bar escaping its card, a banner covering the
button underneath it, the app shell visible before sign-in. So this renders the
real `apps/control/src/index.html` in a real browser and saves the pictures.

    python3 infra/screenshot_console.py            # both viewports
    python3 infra/screenshot_console.py --page more

**The console is served unmodified.** A one-line wrapper page seeds the session
token and redirects, so nothing in the shipped artefact knows this exists — a
screenshot of a file with a test hook in it is a screenshot of a different file.

The API is stubbed here rather than run for real: the point is the layout at
390×844, and standing up Postgres and a worker to look at a nav bar would make
this too slow to run every time, which means it would stop being run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "apps" / "control" / "src"

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

#: 390×844 is an iPhone 14/15; 1280×900 a laptop. The design pass requires both,
#: because a layout designed at one and checked at the other is a layout that
#: was checked once.
VIEWPORTS = {"phone": (390, 844), "desktop": (1280, 900)}

TOKEN = "screenshot-session-not-a-real-token"

#: Enough shape for the layout to be real. Not enough to be mistaken for data:
#: every string says so, because a screenshot with plausible-looking figures in
#: it is one somebody eventually quotes.
FIXTURES: dict[str, object] = {
    "/api/me": {"username": "operator", "tenant_id": "tenant-example",
                "scopes": ["read", "execute", "admin"]},
    "/api/health": {"status": "ok", "components": {
        "claiming": {"status": "COMPLETE", "detail": "Two workers can run safely.",
                     "implementation": "PostgresClaims"},
        "sandbox": {"confinement": "FULL", "can_run_coding_agents": True},
        "credentials": {"configured": True}, "probes": {"configured": True}}},
    "/api/missions": {"missions": [
        {"mission_id": "mission-000000000001", "title": "Sample: a mission that needs review",
         "status": "awaiting_approval", "updated_at": "2026-08-25T09:00:00+00:00",
         "claimed_by": "", "plan": {"goal": "sample goal"}},
        {"mission_id": "mission-000000000002", "title": "Sample: a mission in flight",
         "status": "processing", "updated_at": "2026-08-25T09:05:00+00:00",
         "claimed_by": "worker-1"},
    ], "counts": {"total": 2, "running": 1, "awaiting_approval": 1, "blocked": 0}},
    "/api/missions/blockers": {"by_kind": {}},
    # A delivered mission, so the artefact review card can be looked at rather
    # than asserted. Every field is the shape the real endpoints return.
    "/api/missions/mission-000000000003": {
        "mission_id": "mission-000000000003",
        "title": "Deliver deliver-website for Julian\u2019s Barber Shop",
        "status": "complete", "requested_by": "ayoub",
        "created_at": "2026-08-27T05:47:27Z", "updated_at": "2026-08-27T05:47:30Z",
        "origin_name": "none", "agent_id": "website-builder",
        "recipe": "deliver-website", "signal_id": "sig-20260827054352236624",
        "approved_scope": "offer-website: performance",
        "evidence_fingerprints": ["031f00e817d53959", "e89c6afe5710ef4f",
                                  "fd5e330a2d5db52b"],
        "commits": ["2d77a5f27c684b39297a0ad9b359d38e621eb331"],
        "invocations": [], "blockers": [], "total_cost": None,
        "workspace": "/var/lib/qevik/scratch/mission-000000000003/repo",
        "plan": {"goal": "Build the site an approved opportunity asked for",
                 "steps": [{"order": 1, "title": "what was built, from which "
                                                 "observed defects"}]},
    },
    "/api/missions/mission-000000000003/history": {"history": [
        {"updated_at": "2026-08-27T05:47:30Z", "status": "complete",
         "claimed_by": "worker-delivery", "note": "report written"}]},
    "/api/missions/mission-000000000003/report": {
        "report": "# Deliver deliver-website\n\n## Delivery\n\n"
                  "**Source opportunity:** `sig-20260827054352236624`"},
    "/api/missions/mission-000000000003/artefact": {
        "mission_id": "mission-000000000003",
        "signal_id": "sig-20260827054352236624",
        "approved_scope": "offer-website: performance",
        "approved_by": "ayoub",
        "evidence_fingerprints": ["031f00e817d53959", "e89c6afe5710ef4f",
                                  "fd5e330a2d5db52b"],
        "origin_name": "none", "origin": "", "origin_kind": "empty",
        "recipe": "deliver-website", "agent_id": "website-builder",
        "tools": ["website-generator"],
        "workspace": "/var/lib/qevik/scratch/mission-000000000003/repo",
        "branch": "mission/mission-000000000003",
        "commit": "2d77a5f27c684b39297a0ad9b359d38e621eb331",
        "report_path": "docs/qevik-docs/autonomous/reports/deliver.md",
        "status": "complete",
        "files": [
            {"path": "artefact/index.html", "name": "index.html",
             "size": 1967, "blob": "a1b2c3d"},
            {"path": "artefact/provenance.json", "name": "provenance.json",
             "size": 412, "blob": "d4e5f6a"},
            {"path": "artefact/robots.txt", "name": "robots.txt",
             "size": 44, "blob": "b7c8d9e"},
            {"path": "artefact/sitemap.xml", "name": "sitemap.xml",
             "size": 201, "blob": "c1d2e3f"}],
        "provenance": {"mode": "modify", "site_state": "weak",
                       "addresses": ["a heading on every page",
                                     "a page that loads quickly"],
                       "not_published_for_want_of_a_source": ["email"]},
        "reviews": [],
    },
    # Two real shapes: one the source was silent about, one merely new. Both
    # with UNKNOWN worth, because nothing has measured one.
    "/api/discovery/opportunities": {
        # Derived from the rows below, not typed independently: one row says
        # `needs_approval` and a count that disagreed produced a screenshot of a
        # state the API cannot return.
        "counts": {"total": 2, "needing_approval": 1, "valued": 0},
        "note": ("Every opportunity carries the evidence it rests on. An "
                 "inference is labelled as one. A value of UNKNOWN means "
                 "nobody measured it, and is not zero."),
        "opportunities": [
            {"id": "sig-1", "business_id": "b-1", "kind": "missing_service",
             "source": "openstreetmap", "score": 0.598,
             "detected_at": "2026-08-27T04:15:00+00:00",
             "needs_approval": False,
             "evidence_fingerprints": ["8c23957ade3bb410"],
             "value": {"amount": None, "status": "UNKNOWN"},
             "detail": {
                 "observations": [{"statement": "openstreetmap records no "
                                                "website for Marina Dental."}],
                 "inferences": [{
                     "statement": "The business may have no website, or may "
                                  "have one this source does not record.",
                     "confidence": 0.35, "is_an_inference": True,
                     "would_be_wrong_if": "the business has a website that "
                                          "openstreetmap simply does not list"}],
                 "actions": [{"statement": "Check whether this business has a "
                                           "website before treating it as a "
                                           "prospect for one."}]}},
            {"id": "sig-2", "business_id": "b-2", "kind": "new_business",
             "source": "openstreetmap", "score": 0.585,
             "detected_at": "2026-08-27T04:15:00+00:00",
             "needs_approval": True,
             "evidence_fingerprints": ["8c23957ade3bb410"],
             "value": {"amount": None, "status": "UNKNOWN"},
             "detail": {
                 "observations": [{"statement": "Jumeirah Smile Studio appears "
                                                "in openstreetmap (Dubai), and "
                                                "Qevik had no record of it."}],
                 "inferences": [{
                     "statement": "A business Qevik has not seen before may be "
                                  "worth assessing for the services Qevik offers.",
                     "confidence": 0.3, "is_an_inference": True,
                     "would_be_wrong_if": "it is already a customer under "
                                          "another name, or it is closed"}],
                 "actions": [{"statement": "Assess Jumeirah Smile Studio "
                                           "against the services Qevik can "
                                           "deliver."}]}},
        ]},
    # Two rows on purpose: one merely new to Qevik and one the source actually
    # evidenced. The whole point of this screen is that those read differently.
    "/api/discovery": {
        "counts": {"total": 2, "claiming_about_the_world": 1},
        "note": ("A discovery is new to Qevik. Only rows with "
                 "claims_about_the_world are evidenced as new to their source, "
                 "and new to a source is not new to the world."),
        "discoveries": [
            {"business_id": "b-1", "name": "Marina Dental Clinic",
             "source": "google-places", "source_url": "https://marinadental.ae/",
             "country": "AE", "city": "Dubai",
             "state": "PROVEN_NEW_TO_SOURCE", "claims_about_the_world": True,
             "because": ("google-places reports it as new: "
                         "first_review_at=2026-08-20. This is new to "
                         "google-places, which is not the same as new to the "
                         "world"),
             "observed_at": "2026-08-26T04:15:00+00:00"},
            {"business_id": "b-2", "name": "Jumeirah Smile Studio",
             "source": "overpass", "source_url": "",
             "country": "AE", "city": "Dubai",
             "state": "DISCOVERED_BY_QEVIK", "claims_about_the_world": False,
             "because": ("absent from Qevik's memory, and surfaced by a scan "
                         "rather than supplied. Says nothing about whether the "
                         "entity is new to anybody else"),
             "observed_at": "2026-08-26T04:15:00+00:00"},
        ]},
    # Three origins, so the approval screen has a real choice on it. Names and
    # kinds only — the real endpoint returns no paths, and a fixture that
    # carried one would be a screenshot of a leak that does not exist.
    "/api/missions/origins": {"default": "qevik", "origins": [
        {"name": "qevik", "kind": "qevik", "modifies_qevik_itself": True,
         "may_run_unattended": False,
         "notes": "Qevik's own source; self-modification"},
        {"name": "none", "kind": "empty", "modifies_qevik_itself": False,
         "may_run_unattended": True,
         "notes": "no source repository; nothing at risk"},
        {"name": "acme-web", "kind": "customer", "modifies_qevik_itself": False,
         "may_run_unattended": False,
         "notes": "deployment-configured customer repository"}]},
    # The real shape `/api/missions/costs` returns. The first version of this
    # fixture invented `{"total": None}`, the card read `costs.known_total` and
    # rendered the string `undefined` — a fixture that does not match the API
    # tests a page that does not exist.
    "/api/missions/costs": {"reported": 0.0, "estimated": 0.0, "known_total": 0.0,
                            "priced_calls": 0, "unpriced_calls": 2, "currency": "",
                            "mixed_currencies": False,
                            "note": "2 call(s) reported no cost"},
    "/api/missions/schedule": {"queues": {
        "NOW": [{"mission_id": "mission-000000000002", "why": "ready, and there is capacity",
                 "priority": "normal", "runs_after": "", "placement": "either"}],
        "NEXT": [], "SCHEDULED": [],
        "WAITING": [{"mission_id": "mission-000000000001",
                     "why": "waiting for a person to approve or supply something",
                     "priority": "normal", "runs_after": "", "placement": "either"}],
        "BLOCKED": []},
        "counts": {"NOW": 1, "NEXT": 0, "SCHEDULED": 0, "WAITING": 1, "BLOCKED": 0},
        "dispatchable": ["mission-000000000002"],
        "note": "WAITING resolves on its own; BLOCKED never will."},
    "/api/chat": {"conversations": [
        {"conversation_id": "conv-000000000001",
         "title": "Add this feature: record approval wait time",
         "status": "plan_proposed", "at": "2026-08-26T09:00:00+00:00",
         "mission_id": ""},
        {"conversation_id": "conv-000000000003",
         "title": "Add this feature: show which repository a mission touches",
         "status": "plan_proposed", "at": "2026-08-26T09:30:00+00:00",
         "mission_id": ""}]},
    # A real plan awaiting approval, so the approval screen can be looked at
    # with something on it.
    #
    # Deliberately a change to Qevik itself, not to a customer repository. The
    # console can only create Qevik-origin missions today — `/decide` sends an
    # empty origin, which the registry reads as `qevik` — so a fixture showing a
    # customer plan on this screen would be a screenshot of a capability that
    # does not exist. Targeting a customer origin from the console needs an
    # endpoint listing the registered origins and a control to choose one;
    # recorded in MASTER_STATE rather than faked here.
    "/api/chat/conv-000000000003": {
        "conversation_id": "conv-000000000003",
        "title": "Add this feature: show which repository a mission touches",
        "status": "plan_proposed", "mission_id": "",
        "plan": {
            "goal": "Show which repository a mission will change, before it is approved.",
            "why": "Approving a change to Qevik itself and approving one to a "
                   "customer repository are different decisions, and the "
                   "screen showed neither.",
            "steps": [
                {"order": 1, "title": "Name the origin in words, not as a key",
                 "why": "\"qevik\" means nothing to a person",
                 "files": ["apps/control/src/index.html"]},
                {"order": 2, "title": "Assert each origin reads differently",
                 "files": ["infra/verify_console_logic.mjs"]},
            ],
            "blockers": [], "estimated_cost": 2.5, "cost_status": "ESTIMATED",
            "security_impact": "None. No credentials and no network.",
            "test_plan": "verify_console_logic asserts all three origins.",
            "rollback": "Revert the branch; it is never merged automatically.",
        },
        "messages": [
            {"role": "user", "text": "I cannot tell what a plan is going to "
                                     "change. Show me the repository.",
             "at": "2026-08-26T09:30:00+00:00"},
        ],
            },
    # A conversation whose plan is only a blocker — the state this deployment is
    # actually in, and the one the screen most has to get right.
    "/api/chat/conv-000000000001": {
        "conversation_id": "conv-000000000001",
        "title": "Add this feature: record approval wait time",
        "status": "plan_proposed", "mission_id": "",
        "plan": {
            "goal": "", "why": "", "steps": [], "estimated_cost": None,
            "cost_status": "UNKNOWN",
            "blockers": [{
                "kind": "BLOCKED_EXTERNAL_PROVIDER",
                "detail": "A credential for qwen is configured and the provider "
                          "is refusing it, so no model could be reached. Qevik "
                          "will not invent a plan without one.",
                "action": "This is a problem at qwen, not a missing credential. "
                          "Nothing here can fix it."}]},
        "messages": [
            {"role": "user", "text": "Add this feature: record how long each "
                                     "mission spends waiting for approval.",
             "at": "2026-08-26T09:00:00+00:00", "provider": "", "model": ""},
            {"role": "system", "text": "This cannot proceed yet:\n  "
                                       "[BLOCKED_EXTERNAL_PROVIDER] the provider "
                                       "is refusing the configured credential",
             "at": "2026-08-26T09:00:04+00:00", "provider": "", "model": ""}]},
    # The other state that matters: a real plan a person must decide on. This is
    # the screen where somebody takes responsibility for what runs against
    # Qevik's own source, so it is the one that must not be skimmable.
    "/api/chat/conv-000000000002": {
        "conversation_id": "conv-000000000002",
        "title": "Add this feature: record approval wait time",
        "status": "plan_proposed", "mission_id": "",
        "plan": {
            "goal": "Record how long each mission waits for approval",
            "why": "Sample plan. Nothing here was produced by a model.",
            "estimated_cost": 0.42, "cost_status": "ESTIMATED",
            "security_impact": "No new capability; reads existing timestamps.",
            "test_plan": "A unit test asserting the recorded gap.",
            "rollback": "Revert the commit; the field is additive.",
            "blockers": [],
            "steps": [
                {"order": 1, "title": "record the approval moment",
                 "why": "the gap needs both ends",
                 "files": ["packages/kernel/atlas_kernel/mission/models.py"]},
                {"order": 2, "title": "show it on mission detail",
                 "why": "a number nobody sees is not a feature",
                 "files": ["apps/control/src/index.html"]}]},
        "messages": [
            {"role": "user", "text": "Add this feature: record how long each "
                                     "mission spends waiting for approval.",
             "at": "2026-08-26T09:00:00+00:00", "provider": "", "model": ""}]},
    "/api/credentials": {"credentials": [], "connected": [], "action_required": [],
                         "vault": {"sealed": False, "locked": False}, "note": "sample"},
    "/api/status": {"version": "sample", "changed": False},
}


def safe_slug(page: str) -> str:
    """A page name as one filename component.

    `--page chat/conv-1` used to become a *directory* in the output path, so
    the file was written somewhere nobody looked and the run appeared to
    succeed. Fixed once for the screenshot filename and not for `--measure`,
    which is why it is a function now rather than an expression in two places.
    """
    return page.strip("/").replace("/", "-") or "root"


def _no_duplicate_keys() -> None:
    """Refuse a fixture declared twice.

    A Python dict literal takes the **last** of a repeated key and says nothing.
    A fixture added above one that already existed is therefore silently
    discarded, and the stub then answers with the other endpoint's payload —
    which is the same failure the prefix-matching comment above describes,
    arriving by a different route. It cost one screenshot of a page that could
    not exist, which is the only kind of bug a screenshot harness must not have.
    """
    import ast

    source = Path(__file__).read_text()
    found = None
    for node in ast.walk(ast.parse(source)):
        # Both forms. The first version of this checked `ast.Assign` only, and
        # `FIXTURES` is annotated — so it matched nothing, found no duplicates,
        # and passed. A checker that cannot fail is worse than no checker,
        # because it is also a claim.
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        else:
            continue
        if not any(getattr(t, "id", "") == "FIXTURES" for t in targets):
            continue
        found = node
        keys = [k.value for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        repeated = {k for k in keys if keys.count(k) > 1}
        if repeated:
            raise SystemExit(
                f"screenshot_console.py declares these fixtures twice: "
                f"{', '.join(sorted(repeated))}. Python keeps the last one and "
                "discards the other silently, so the stub would answer with a "
                "payload nobody meant.")
    if found is None:
        raise SystemExit(
            "the duplicate-fixture check could not find the FIXTURES literal, "
            "so it proved nothing. Fix the check rather than removing it.")


def _fixtures_agree_with_themselves() -> None:
    """Refuse a fixture whose summary contradicts its own rows.

    A count typed independently of the rows it counts is a screenshot of a page
    the API cannot return — and the whole value of this harness is that what it
    renders could actually happen. Caught once, when the header said "0 needing
    you" above a row saying "needs you".
    """
    listed = FIXTURES.get("/api/discovery/opportunities") or {}
    rows = listed.get("opportunities") or []
    counts = listed.get("counts") or {}
    if rows and counts:
        real = sum(1 for row in rows if row.get("needs_approval"))
        if counts.get("needing_approval") != real:
            raise SystemExit(
                f"the opportunities fixture says {counts.get('needing_approval')} "
                f"need approval and {real} of its rows say so.")
        if counts.get("total") != len(rows):
            raise SystemExit(
                f"the opportunities fixture says {counts.get('total')} total "
                f"and carries {len(rows)} rows.")


_no_duplicate_keys()
_fixtures_agree_with_themselves()


class Stub(BaseHTTPRequestHandler):
    """The console's files, plus enough API to render. Nothing writes."""

    def log_message(self, *_: object) -> None:            # quiet
        return

    def do_GET(self) -> None:                             # noqa: N802
        path = self.path.split("?")[0]
        if path == "/__measure":
            # Which element is actually wider than the viewport. Guessing at CSS
            # from a screenshot is how an afternoon disappears; this names the
            # node.
            page = self.path.split("page=")[-1] if "page=" in self.path else ""
            body = ("<!doctype html><meta charset=utf-8>"
                    "<style>html,body{margin:0;background:#111;color:#eee;"
                    "font:12px ui-monospace}</style><pre id=out>measuring…</pre>"
                    f"<script>sessionStorage.setItem('qevik.token',"
                    f"{json.dumps(TOKEN)});</script>"
                    "<iframe id=f style='width:390px;height:844px;border:0;"
                    "position:absolute;left:-9999px'></iframe><script>"
                    "const f=document.getElementById('f');"
                    f"f.src='/index.html#/{page}';"
                    "f.onload=()=>setTimeout(()=>{"
                    "const d=f.contentDocument,w=390,lines=[];"
                    "lines.push('viewport '+w+'  doc.scrollWidth '+"
                    "d.documentElement.scrollWidth);"
                    "lines.push('body.scrollWidth '+d.body.scrollWidth);"
                    "d.querySelectorAll('main *').forEach(el=>{"
                    "const r=el.getBoundingClientRect();"
                    "const over=r.right>w+1||el.scrollWidth>Math.ceil(r.width)+1;"
                    "lines.push((over?'OVER ':'     ')+"
                    "[el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+"
                    "(el.className&&typeof el.className==='string'?'.'+"
                    "el.className.trim().split(/\\s+/).join('.'):''),"
                    "'x='+Math.round(r.left),'right='+Math.round(r.right),"
                    "'w='+Math.round(r.width),'scrollW='+el.scrollWidth].join(' '));});"
                    "document.getElementById('out').textContent="
                    "lines.slice(0,34).join('\\n');},2500);</script>")
            return self._send(200, body.encode(), "text/html; charset=utf-8")
        if path == "/__frame":
            # The console inside an iframe of exactly the target width.
            #
            # `--window-size` did not reliably drive the *layout* viewport: the
            # image came out 390px wide while the page had laid out wider, so
            # content looked clipped and a navigation item appeared missing
            # when measurement showed everything fitted. An iframe with an
            # explicit width is not subject to that — the layout width is the
            # width, whatever the browser does with its window.
            query = self.path.split("?", 1)[-1] if "?" in self.path else ""
            fields = dict(pair.split("=", 1) for pair in query.split("&")
                          if "=" in pair)
            page = fields.get("page", "")
            width = int(fields.get("w", "390"))
            height = int(fields.get("h", "844"))
            body = (f"<!doctype html><meta charset=utf-8><style>"
                    f"html,body{{margin:0;background:#3a3a3a}}"
                    f"iframe{{width:{width}px;height:{height}px;border:0;"
                    f"display:block}}</style>"
                    f"<script>sessionStorage.setItem('qevik.token',"
                    f"{json.dumps(TOKEN)});</script>"
                    f"<iframe src='/index.html#/{page}'></iframe>")
            return self._send(200, body.encode(), "text/html; charset=utf-8")
        if path == "/__seed":
            # Seeds the session and redirects. Kept out of index.html so the
            # artefact photographed is the artefact shipped.
            page = self.path.split("page=")[-1] if "page=" in self.path else ""
            body = (f"<!doctype html><meta charset=utf-8><script>"
                    f"sessionStorage.setItem('qevik.token', {json.dumps(TOKEN)});"
                    f"location.replace('/index.html#/{page}');</script>")
            return self._send(200, body.encode(), "text/html; charset=utf-8")
        if path.startswith("/api/") or path.startswith("/auth/"):
            return self._json(path)
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (CONSOLE / name).resolve()
        if not target.is_file() or CONSOLE.resolve() not in target.parents:
            return self._send(404, b"not here", "text/plain")
        kind = ("text/html; charset=utf-8" if target.suffix == ".html"
                else "text/plain; charset=utf-8")
        return self._send(200, target.read_bytes(), kind)

    def do_POST(self) -> None:                            # noqa: N802
        self._json(self.path.split("?")[0])

    def _json(self, path: str) -> None:
        # Exact match first, then the longest prefix.
        #
        # This walked the dict in insertion order and took the first prefix
        # hit, so `/api/missions/costs` was served the *missions list* because
        # `/api/missions` was declared earlier — and the cost card rendered from
        # the wrong payload. A stub that answers the wrong endpoint produces a
        # screenshot of a page that cannot exist.
        if path in FIXTURES:
            return self._send(200, json.dumps(FIXTURES[path]).encode(),
                              "application/json")
        matches = [k for k in FIXTURES if path.startswith(k + "/")]
        if matches:
            best = max(matches, key=len)
            return self._send(200, json.dumps(FIXTURES[best]).encode(),
                              "application/json")
        return self._send(200, b"{}", "application/json")

    def _send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def shoot(url: str, out: Path, width: int, height: int) -> bool:
    if not Path(CHROME).exists():
        print(f"  no browser at {CHROME}")
        return False
    done = subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
         f"--screenshot={out}", f"--window-size={width},{height}",
         "--virtual-time-budget=4000", url],
        capture_output=True, text=True, timeout=90, check=False)
    if not out.exists():
        print(f"  chrome wrote nothing: {done.stderr.strip()[:160]}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", default="dashboard")
    parser.add_argument("--port", type=int, default=8623)
    parser.add_argument("--out", default="")
    parser.add_argument("--measure", action="store_true",
                        help="name the elements wider than the viewport")
    parser.add_argument("--tall", type=int, default=0, metavar="PX",
                        help="override the viewport height, to see a page whose "
                             "content runs past 844px. Chrome captures the "
                             "viewport rather than the document, so a control "
                             "below the fold is otherwise invisible here — "
                             "which is a limitation of the camera, not a "
                             "defect in the page")
    args = parser.parse_args()

    out = Path(args.out) if args.out else ROOT / ".screenshots"
    out.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("127.0.0.1", args.port), partial(Stub))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.4)

    if args.measure:
        target = out / f"measure-{safe_slug(args.page)}.png"
        target.unlink(missing_ok=True)
        shoot(f"http://127.0.0.1:{args.port}/__measure?page={args.page}",
              target, 900, 700)
        server.shutdown()
        print(f"  {target}")
        return 0

    written = []
    try:
        for name, (width, height) in VIEWPORTS.items():
            height = args.tall or height
            # A page like `chat/conv-1` would otherwise become a directory in
            # the filename, and Chrome writes nothing to a path that does not
            # exist — reported as "nothing was captured" with no reason.
            slug = safe_slug(args.page)
            target = out / f"console-{slug}-{name}.png"
            target.unlink(missing_ok=True)
            # The iframe fixes the layout width; the window only has to be big
            # enough to hold it.
            url = (f"http://127.0.0.1:{args.port}/__frame"
                   f"?page={args.page}&w={width}&h={height}")
            print(f"{name} {width}x{height} → {target.name}")
            if shoot(url, target, width, height):
                written.append(target)
    finally:
        server.shutdown()

    if not written:
        print("\nnothing was captured; the layout has not been looked at")
        return 1
    for path in written:
        print(f"  {path}  ({path.stat().st_size // 1024} KB)")
    print("\nNow read them. A rendered page is not a working one.")
    return 0


if __name__ == "__main__":
    if shutil.which("true") is None:                      # pragma: no cover
        pass
    raise SystemExit(main())
