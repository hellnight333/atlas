"""What production says is worth doing, when the queue runs dry.

An empty queue must never become a question for the owner, and it must never
become an invitation for an agent to invent work. It becomes a query.

That rule is not a preference. Three times in the last week "there is nothing
ready" was reached by asking which *tracks* were open, and three times reading
what the running system was actually producing found something material: 43
businesses told their sites were dead by our own crawler, four of five
publications unable to say what they had published, and an observation record
with no scheduled producer at all. None was visible in the repository.

## What it may enqueue

Only findings that are **deterministic, safe and evidenced**. Each rule below
states the query, and a finding carries the numbers it was derived from, so a
task's `evidence` can be read back and disagreed with. A rule that cannot
express its evidence does not belong here.

Anything that would need a credential, a decision, an account, a machine or an
irreversible action is **not** enqueued as work. It is a human boundary, and
the control plane already derives those.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

HOST = "root@2.28.62.83"
KEY = Path.home() / ".ssh" / "naml_hetzner"


@dataclass(frozen=True)
class Finding:
    """One thing production says is wrong, and what it would take to fix."""

    key: str
    title: str
    brief: str
    priority: int
    evidence: dict = field(default_factory=dict)
    requires_deploy: bool = False
    requires_prod_check: bool = False


#: Each rule is a SQL query and a reading of its row. Declared together so a
#: finding cannot cite a number no query produced.
RULES: tuple[dict, ...] = (
    {
        "key": "publication-offer-unknown",
        "sql": """SELECT count(*) n FROM atlas_business_events
                  WHERE kind = 'publication_completed'
                    AND coalesce(detail->>'offer', '') = ''""",
        "when": lambda r: r["n"] > 0,
        "title": "Publications that cannot say what they published",
        "brief": ("Some `publication_completed` events record no `offer`, and "
                  "`outreach.preparation.prepare` refuses a publication that "
                  "cannot describe itself. Find out whether the value is "
                  "recoverable from the delivering mission's recipe, and if it "
                  "is, resolve it on read without rewriting history."),
        "priority": 80,
    },
    {
        "key": "audit-observations-stale",
        "sql": """WITH latest AS (
                    SELECT DISTINCT ON (business_id) business_id, at
                    FROM atlas_business_events WHERE kind = 'website_audited'
                    ORDER BY business_id, at DESC)
                  SELECT count(*) FILTER (WHERE at < now() - interval '8 days') n,
                         count(*) total FROM latest""",
        "when": lambda r: r["n"] > (r["total"] or 1) * 0.5,
        "title": "Most observation records are more than a week old",
        "brief": ("The majority of businesses carry observations older than a "
                  "week while the nightly pass runs every night. Establish "
                  "whether the refresh path actually reaches them, and if the "
                  "cadence is simply the backlog, make that visible rather "
                  "than changing it."),
        "priority": 70,
    },
    {
        "key": "outreach-blocked-not-stated",
        "sql": """SELECT count(*) n FROM atlas_outreach_messages
                  WHERE status = 'draft' AND approved_fingerprint IS NULL""",
        "when": lambda r: r["n"] > 6,
        "title": "Drafted outreach that has never been reviewed",
        "brief": ("Several outreach drafts exist that nobody has decided "
                  "about. Establish from the records why each is unreviewed "
                  "and surface it; do not approve, send or delete anything."),
        "priority": 40,
    },
    {
        "key": "our-own-failed-checks",
        "sql": """SELECT count(*) n FROM (
                    SELECT DISTINCT ON (business_id) business_id, detail
                    FROM atlas_business_events WHERE kind = 'website_audited'
                    ORDER BY business_id, at DESC) latest
                  WHERE detail->>'error' LIKE '%interrupted%'""",
        "when": lambda r: r["n"] > 0,
        "title": "Businesses dropped from the funnel by our own failed checks",
        "brief": ("Some businesses' most recent audit failed for a reason that "
                  "was ours, not theirs, so they carry no evidence and leave "
                  "the funnel without appearing as a loss. Establish how many "
                  "and whether the rotation is recovering them."),
        "priority": 60,
    },
)


def _query(sql: str) -> dict | None:
    """Run one read-only query on the control plane. Returns the first row."""
    if not KEY.exists():
        return None
    script = (
        "import json\n"
        "from sqlalchemy import text\n"
        "from atlas_kernel.db import SessionLocal\n"
        "with SessionLocal() as s:\n"
        f"    r = s.execute(text('''{sql}''')).mappings().first()\n"
        "    print(json.dumps(dict(r) if r else {}, default=str))\n")
    remote = ("cd /opt/qevik/atlas && set -a && . /opt/qevik/atlas.env && "
              "set +a && PYTHONPATH=packages/kernel .venv/bin/python - <<'Q'\n"
              f"{script}\nQ")
    try:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
             "-o", "ConnectionAttempts=3", "-i", str(KEY), HOST, remote],
            capture_output=True, text=True, timeout=180,
            stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    for line in reversed((done.stdout or "").splitlines()):
        if line.strip().startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def findings() -> list[Finding]:
    """Ask production. An unreachable host yields nothing, never a false all-clear."""
    found: list[Finding] = []
    for rule in RULES:
        row = _query(rule["sql"])
        if row is None:
            # NOT_VERIFIED, not "no problem". A query that did not run has
            # established nothing, and enqueuing on that basis — or reporting
            # all-clear on it — would both be inventions.
            continue
        try:
            if not rule["when"](row):
                continue
        except (KeyError, TypeError):
            continue
        found.append(Finding(
            key=rule["key"], title=rule["title"], brief=rule["brief"],
            priority=rule["priority"],
            evidence={"query": " ".join(rule["sql"].split()), "row": row},
            requires_deploy=True, requires_prod_check=False))
    return found


def enqueue_from_production(queue, *, repo: Path) -> int:
    """Enqueue what production supports, once each. Returns how many were new.

    Idempotent on the rule key: a finding that is still true tomorrow does not
    become a second task, and a task already open for it is left alone.
    """
    open_titles = {t["title"] for t in queue.tasks()
                   if t["state"] not in ("DONE", "FAILED")}
    added = 0
    for one in findings():
        if one.title in open_titles:
            continue
        queue.add(title=one.title, brief=one.brief, origin="production",
                  priority=one.priority, evidence=one.evidence,
                  requires_deploy=one.requires_deploy,
                  requires_prod_check=one.requires_prod_check)
        added += 1
    return added


__all__ = ["Finding", "RULES", "enqueue_from_production", "findings"]
