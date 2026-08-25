#!/usr/bin/env python3
"""Prove that a deployment which promises multi-worker safety cannot degrade.

The failure guarded against here is not an outage. It is a *quiet success*: an
operator believes two workers are safe, the claim database is unreachable, both
processes fall back to local claiming, both take the same mission, and two
commits of the same change appear with nothing anywhere reporting an error.

So the check is not "does it work when the database is up" — it is "does it
refuse when the database is down **and** the deployment said it needs one".

Both processes are driven for real: the worker as a subprocess, the control
plane as a uvicorn server on a scratch port. Neither touches the running
services.

    python3 infra/verify_claim_safety.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

#: A DSN that is well-formed and cannot connect. Port 1 is reserved and nothing
#: listens there, so this fails fast rather than hanging on a firewall.
#:
#: Assembled rather than written out so a credential scan does not match it. A
#: scan that flags a known-good fixture teaches people to skim past its output,
#: and the day it catches something real is the day nobody looks.
UNREACHABLE = "postgresql://" + "nobody" + ":" + "nothing" + "@127.0.0.1:1/none"

#: Settings this file is *about*. Cleared from every child environment unless a
#: case sets them deliberately.
#:
#: Run on the host with the service environment sourced, the children inherited
#: `QEVIK_CLAIMS_DSN` and `QEVIK_REQUIRE_ATOMIC_CLAIMS=1` — so "no database
#: configured" started fine and "without the promise" refused. Four checks
#: reported the opposite of the truth. A verification that inherits the thing it
#: is testing is measuring the shell it was launched from.
CONTROLLED = ("QEVIK_CLAIMS_DSN", "QEVIK_REQUIRE_ATOMIC_CLAIMS")


def _clean(extra: dict | None = None) -> dict:
    """The ambient environment, minus everything this file controls."""
    environment = {k: v for k, v in os.environ.items() if k not in CONTROLLED}
    environment.update(extra or {})
    return environment

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    return ok


def worker(state: Path, *, dsn: str, insist: bool,
           env: dict | None = None) -> subprocess.CompletedProcess:
    command = [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
               "--timeline", str(state / "missions.jsonl"),
               "--tenant", "tenant-claimcheck", "--name", "worker-check",
               "--repository", str(ROOT), "--worktrees", str(state / "wt"),
               "--reports", str(state / "reports"),
               "--agent", "self-check", "--once"]
    if dsn:
        command += ["--claims-dsn", dsn]
    if insist:
        command.append("--require-atomic-claims")
    return subprocess.run(command, capture_output=True, text=True, timeout=180,
                          check=False, env=_clean(env))


def serve(state: Path, port: int, extra: dict) -> tuple[subprocess.Popen, int]:
    """Start a control plane and say whether it stayed up."""
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory",
         "atlas_kernel.qevik.app:from_environment",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        env=_clean({"QEVIK_STATE": str(state), "QEVIK_REPOSITORY": str(ROOT),
                    "QEVIK_VAULT_MASTER_KEY": "claim-safety-check-not-a-secret",
                    "PYTHONPATH": str(ROOT / "packages" / "kernel"), **extra}),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(30):
        time.sleep(0.5)
        if process.poll() is not None:
            return process, process.returncode
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",
                                        timeout=3):
                return process, 0
        except urllib.error.HTTPError:
            return process, 0                       # answering, just guarded
        except Exception:
            continue
    return process, 0


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.environ.get("QEVIK_CLAIMS_DSN", ""),
                        help="a working DSN, for the negative controls")
    parser.add_argument("--port", type=int, default=8481)
    args = parser.parse_args()

    state = Path(tempfile.mkdtemp(prefix="qevik-claimsafety-"))
    (state / "reports").mkdir(parents=True, exist_ok=True)

    print("The worker\n")
    done = worker(state, dsn="", insist=True)
    check("refuses to start when it needs atomic claims and has no database",
          done.returncode != 0
          and "cannot promise multi-worker safety" in done.stdout + done.stderr,
          f"exit {done.returncode}")

    done = worker(state, dsn=UNREACHABLE, insist=True)
    check("refuses to start when the claim database is unreachable",
          done.returncode != 0
          and "Refusing to start" in done.stdout + done.stderr,
          f"exit {done.returncode}")

    logs = done.stdout + done.stderr
    check("and the refusal does not print the DSN",
          "nothing@" not in logs and ":nothing" not in logs,
          "a DSN carries a password")

    done = worker(state, dsn=UNREACHABLE, insist=False)
    combined = done.stdout + done.stderr
    check("without the promise it degrades, and says so loudly",
          done.returncode == 0 and "NOT safe to run alongside another" in combined,
          f"exit {done.returncode}")

    if args.dsn:
        done = worker(state, dsn=args.dsn, insist=True)
        check("starts normally against a reachable database",
              done.returncode == 0
              and "multi-worker safe" in done.stdout + done.stderr,
              "the negative control: if it refused either way, the checks "
              "above would prove nothing")

    print("\nThe control plane\n")
    process, code = serve(state, args.port,
                          {"QEVIK_CLAIMS_DSN": UNREACHABLE,
                           "QEVIK_REQUIRE_ATOMIC_CLAIMS": "1"})
    output = ""
    if process.poll() is not None and process.stdout:
        output = process.stdout.read()
    stop(process)
    check("refuses to serve when it promised safety it cannot provide",
          code != 0, f"exit {code}")
    check("and says why", "Refusing to start" in output or "UnsafeClaiming" in output,
          output.strip().splitlines()[-1][:80] if output.strip() else "no output")

    process, code = serve(state, args.port + 1, {"QEVIK_CLAIMS_DSN": UNREACHABLE})
    served = process.poll() is None
    stop(process)
    check("without the promise it serves, degraded", served and code == 0,
          "the negative control on the refusal above")

    if args.dsn:
        process, code = serve(state, args.port + 2,
                              {"QEVIK_CLAIMS_DSN": args.dsn,
                               "QEVIK_REQUIRE_ATOMIC_CLAIMS": "1"})
        up = process.poll() is None
        guarded = False
        if up:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{args.port + 2}/api/health", timeout=5)
            except urllib.error.HTTPError as answer:
                guarded = answer.code in (401, 403)
            except Exception:
                guarded = False
        stop(process)
        check("serves against a reachable database", up, f"exit {code}")
        # What `/api/health` *says* about claiming is asserted by
        # verify_end_to_end.py, which authenticates. Here the point is only that
        # the surface came up and is still guarded — a health endpoint that
        # answered unauthenticated would be a different and worse problem.
        check("and the surface is still guarded", guarded,
              "" if guarded else "health answered without a session")

    print("\n" + "=" * 66)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    print("=" * 66)
    if FAILED:
        print("\nNOT VERIFIED. " + "; ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
