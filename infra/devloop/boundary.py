"""The bridge between a parked development task and the human who unblocks it.

The driver does not own human requests. The control plane does — one inbox,
one `ActionKind`, one place a person looks. This module is the narrow seam:
it raises a request when the builder hits a boundary, and it asks whether that
request has been resolved so the parked task can run again.

## Why the driver does not keep its own copy

A blocker stored in the driver's SQLite and again in the control plane is two
records that disagree the moment somebody answers one of them. So the driver
stores the request **id** and nothing else, and reads the answer through the
same API the console reads.

## Why the request outlives the run

A boundary hit at 02:00 is answered at 09:00, by which time the driver process
is gone. Nothing about resumption may depend on that process still existing:
the request is in Postgres, the parked task and its resume stage are in SQLite,
and a fresh driver joins them by id.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .queue import Queue, State

KEY = Path.home() / ".ssh" / "naml_hetzner"
HOST = "root@2.28.62.83"

#: Which boundary a builder ran into, from what it said. Deliberately narrow:
#: an agent that merely felt uncertain must not be able to manufacture a human
#: request, so a boundary is recognised by naming one of these things and
#: nothing else.
KINDS: tuple[tuple[str, str], ...] = (
    ("credential", "credential"),
    ("api key", "credential"),
    ("account", "credential"),
    ("dns", "provisioning"),
    ("smtp", "credential"),
    ("physical", "provisioning"),
    ("hardware", "provisioning"),
    ("machine", "provisioning"),
    # QUESTION, not DECISION. A decision is answered by choosing one of its
    # stated options, and an agent stopped at a boundary can say what stopped
    # it but cannot reliably enumerate the choices. Asked as a question the
    # answer comes in the person's own words — and a question authorises
    # nothing, which is the safe way to be wrong.
    ("product decision", "question"),
    ("architecture decision", "question"),
    ("policy", "question"),
    ("irreversible", "external_action"),
    ("send", "external_action"),
)


def classify(boundary: str) -> str:
    """Which kind of human request this boundary is. Defaults to a question.

    A question is the safest default: it accepts free text, authorises nothing,
    and cannot be turned into an approval by somebody typing "yes".
    """
    lowered = (boundary or "").lower()
    for marker, kind in KINDS:
        if marker in lowered:
            return kind
    return "question"


def _remote(script: str, *, timeout: int = 120) -> dict | None:
    """Run a small read or write against the control plane. None if unreachable."""
    if not KEY.exists():
        return None
    remote = ("cd /opt/qevik/atlas && set -a && . /opt/qevik/atlas.env && "
              "set +a && PYTHONPATH=packages/kernel .venv/bin/python - <<'PY'\n"
              f"{script}\nPY")
    try:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
             "-o", "ConnectionAttempts=3", "-i", str(KEY), HOST, remote],
            capture_output=True, text=True, timeout=timeout,
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


def raise_for(task: dict, boundary: str) -> str:
    """Ask the control plane to raise a request for this boundary.

    Returns the request id, or an empty string when the control plane could not
    be reached — in which case the caller parks the task anyway against the
    boundary's local marker. Unreachable must not mean unrecorded.
    """
    kind = classify(boundary)
    # The subject is the deduplication key, and it is derived from the boundary
    # rather than from the task: two tasks stopped by the same missing
    # credential must produce one request, not two.
    subject = re.sub(r"[^a-z0-9 ]+", " ", boundary.lower())[:80].strip()
    payload = {
        "kind": kind, "subject": subject,
        "title": boundary[:160],
        "why": (f"The development loop stopped here while carrying out "
                f"{task['title']!r}."),
        "blocks": task["title"][:200],
        "asked": boundary[:400],
        "consequence": "The parked task resumes from where it stopped.",
        "will_not_do": ("Nothing was changed, sent, deployed or decided while "
                        "waiting."),
        "next_action": "The driver re-checks this and resumes automatically.",
        "created_by": f"devloop:{task['id']}",
    }
    script = (
        "import json\n"
        "from atlas_kernel.controlplane import human\n"
        "from atlas_kernel.controlplane.actions import ActionKind\n"
        f"p = {payload!r}\n"
        "ident = human.raise_request(kind=ActionKind(p['kind']),\n"
        "    subject=p['subject'], title=p['title'], why=p['why'],\n"
        "    blocks=p['blocks'], asked=p['asked'],\n"
        "    consequence=p['consequence'], will_not_do=p['will_not_do'],\n"
        "    next_action=p['next_action'], created_by=p['created_by'])\n"
        "print(json.dumps({'id': ident}))\n")
    answer = _remote(script)
    return (answer or {}).get("id", "")


def resolved(request_id: str) -> bool | None:
    """Whether the person has answered. `None` when it could not be read.

    Three states, not two, and the third is the one that matters: a control
    plane that cannot be reached has not told us the request is unresolved, and
    treating silence as "still blocked" would be as wrong as treating it as
    "go ahead" — so the caller leaves the task parked and tries again.
    """
    if not request_id:
        return None
    script = ("import json\n"
              "from atlas_kernel.controlplane import human\n"
              f"print(json.dumps({{'resolved': human.is_resolved({request_id!r})}}))\n")
    answer = _remote(script)
    if answer is None:
        return None
    return bool(answer.get("resolved"))


def release_resolved(queue: Queue) -> int:
    """Free every parked task whose request has been answered.

    One request may hold up several tasks — a missing credential blocks
    sending, verification and the commercial proof at once — so this releases
    by request id rather than one task at a time.
    """
    freed = 0
    for request_id in {t["blocked_by"] for t in queue.waiting_on_human()
                       if t["blocked_by"]}:
        state = resolved(request_id)
        if state is not True:
            continue
        for task in queue.blocked_by(request_id):
            queue.release(task["id"], because=f"{request_id} was resolved")
            freed += 1
    return freed


__all__ = ["KINDS", "classify", "raise_for", "release_resolved", "resolved"]
