#!/usr/bin/env bash
# Put the kernel and the console on the host that serves app.qevik.ai.
#
#   QEVIK_DEPLOY_SHA=<commit> ./infra/deploy_control.sh [--rehearse] [user@host]
#
# The console has no build step and the kernel is pure Python, so a deploy is a
# file copy and a restart. What this adds over `rsync && systemctl restart` is
# the part that keeps it honest:
#
#   * it refuses rather than half-deploying,
#   * it **verifies afterwards** instead of reporting success because rsync
#     exited zero, and
#   * it puts the previous tree back if the service does not come up.
#
# A deploy that reports success on a dead service is worse than one that fails,
# because the next person debugs the application instead of the deploy.
#
# Everything it ships comes from the single commit named by QEVIK_DEPLOY_SHA:
# extracted from the git object store into a private directory and checked
# against that commit's own tree before anything is sent. The working tree is
# never read for deployed content, so a checkout or an edit while a copy is in
# flight cannot change what lands on the host (ADR-0010 Step 1).
#
# Exit codes: 0 deployed, or rehearsed; 1 a preflight refusal or a deploy that
# failed; 2 refused before any host contact -- arguments, seams, sha, tree;
# 3 the export did not match the commit.
#
# QEVIK_REMOTE_APP, QEVIK_CONSOLE_DIR, QEVIK_UNIT_DIR, QEVIK_ENV_FILE,
# QEVIK_HEALTH_URL and QEVIK_ROLLBACK_DIR redirect the host paths so the tests
# can drive a whole run against a fake host. Production never sets them: all six
# together and only under QEVIK_TEST_HOST=1, or this script refuses.
set -euo pipefail

REHEARSE=0
TARGET=""
for arg in "$@"; do
  case "$arg" in
    --rehearse) REHEARSE=1 ;;
    -*)
      echo "REFUSED: unknown option '$arg'" >&2
      echo "  usage: QEVIK_DEPLOY_SHA=<commit> $0 [--rehearse] [user@host]" >&2
      exit 2 ;;
    *)
      if [ -n "$TARGET" ]; then
        echo "REFUSED: one target only; got '$TARGET' and '$arg'" >&2
        exit 2
      fi
      TARGET="$arg" ;;
  esac
done

TARGET="${TARGET:-root@2.28.62.83}"
KEY="$HOME/.ssh/naml_hetzner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE="qevik-control.service"
WORKERS="qevik-worker.service qevik-worker-research.service qevik-worker-delivery.service qevik-worker-publish.service qevik-worker-healthcheck.service"

# The six host paths move together or not at all: a seam left behind in an
# operator's shell must never redirect *part* of a production deploy.
SEAMS=0
for seam in "${QEVIK_REMOTE_APP:-}" "${QEVIK_CONSOLE_DIR:-}" "${QEVIK_UNIT_DIR:-}" \
            "${QEVIK_ENV_FILE:-}" "${QEVIK_HEALTH_URL:-}" "${QEVIK_ROLLBACK_DIR:-}"; do
  if [ -n "$seam" ]; then SEAMS=$((SEAMS + 1)); fi
done
if [ "$SEAMS" -ne 0 ] && { [ "$SEAMS" -ne 6 ] || [ "${QEVIK_TEST_HOST:-}" != "1" ]; }; then
  echo "REFUSED: the test seams are partially set ($SEAMS of 6 set," >&2
  echo "  QEVIK_TEST_HOST='${QEVIK_TEST_HOST:-}'). All of QEVIK_REMOTE_APP," >&2
  echo "  QEVIK_CONSOLE_DIR, QEVIK_UNIT_DIR, QEVIK_ENV_FILE, QEVIK_HEALTH_URL," >&2
  echo "  QEVIK_ROLLBACK_DIR and QEVIK_TEST_HOST=1, or none of them." >&2
  exit 2
fi

REMOTE_APP="${QEVIK_REMOTE_APP:-/opt/qevik/atlas}"
CONSOLE_DIR="${QEVIK_CONSOLE_DIR:-/srv/qevik-control}"
UNIT_DIR="${QEVIK_UNIT_DIR:-/etc/systemd/system}"
ENV_FILE="${QEVIK_ENV_FILE:-/opt/qevik/atlas.env}"
HEALTH="${QEVIK_HEALTH_URL:-http://127.0.0.1:8081/api/health}"
ROLLBACK_DIR="${QEVIK_ROLLBACK_DIR:-/opt/qevik/rollback}"

# Connections to this host drop intermittently — the loss is on the operator's
# side, not the server's, and it shows up as "timed out during banner exchange"
# on roughly one attempt in five. A deploy makes a dozen round trips, so a
# single-attempt option set turns a working link into a failed deploy that has
# already copied half the tree.
#
# `ConnectionAttempts` retries the handshake inside ssh itself; the keepalives
# stop a long rsync being torn down by a stall rather than a disconnect. None of
# this hides a real outage: the whole set still gives up, just not on the first
# lost packet.
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=20 -o ConnectionAttempts=4
          -o ServerAliveInterval=10 -o ServerAliveCountMax=6)
# `ConnectionAttempts` retries the TCP connect, which is not where this link
# fails: it fails *after* connecting, during the banner exchange. So each call
# is retried here instead. Every command this script sends is idempotent — copy
# a rollback, apply the schema, chown, restart, read a status — so repeating one
# that may have half-run costs nothing. Only exit 255 is retried, because that is
# ssh's own status for every connection-level failure and any other status is the
# remote command's own answer, which retrying would merely delay by 165 seconds.
ssh_() {
  local try rc
  for try in 1 2 3 4 5 6 7 8 9 10 11 12; do
    rc=0
    ssh "${SSH_OPTS[@]}" -i "$KEY" "$TARGET" "$@" || rc=$?
    if [ "$rc" -eq 0 ]; then return 0; fi
    if [ "$rc" -ne 255 ] || [ "$try" -eq 12 ]; then return "$rc"; fi
    echo "    (link dropped; retry $try)" >&2
    sleep $(( try < 6 ? try * 3 : 20 ))
  done
}
#: rsync resumes rather than restarting when a transfer is cut mid-file.
RSYNC_SSH="ssh ${SSH_OPTS[*]} -i $KEY"
# `--dry-run --itemize-changes` under --rehearse, empty otherwise. Deliberately
# unquoted where it is used: empty has to expand to no argument at all, and
# bash 3.2 has no clean empty-array expansion under `set -u`.
RSYNC_DRY=""

# Same reason as `ssh_`, and safe for the same reason: rsync is idempotent by
# construction, and `--partial` means a retry continues the file it was cut in
# rather than starting the tree again. Unlike ssh, rsync reports a cut transport
# as its own exit codes (12 and 30 among them), so every non-zero stays retried.
rsync_() {
  local try rc
  for try in 1 2 3 4 5 6 7 8 9 10 11 12; do
    rc=0
    # shellcheck disable=SC2086
    rsync -a --partial --timeout=120 $RSYNC_DRY -e "$RSYNC_SSH" "$@" || rc=$?
    if [ "$rc" -eq 0 ]; then return 0; fi
    if [ "$try" -eq 12 ]; then return "$rc"; fi
    echo "    (transfer cut; retry $try)" >&2
    sleep $(( try < 6 ? try * 3 : 20 ))
  done
}

# Refuse rather than half-deploy. `infra/` went unshipped for the whole life of
# this script and nobody noticed, because a deploy that sends less than it
# should still exits zero. This asks the opposite question: is anything that
# changed *not* covered by what we send?
#
# Tracked, modified, runtime files only -- tests and documents do not run in
# production. Committed work is covered too: the comparison is against what the
# host has, not against the last commit.
SHIPPED_PREFIXES="packages/kernel/atlas_kernel/ infra/ apps/control/src/"
UNSHIPPED=""
for f in $(git -C "$ROOT" ls-files -mo --exclude-standard 2>/dev/null); do
  case "$f" in
    */tests/*|tests/*|*.md|docs/*) continue ;;
  esac
  covered=""
  for prefix in $SHIPPED_PREFIXES; do
    case "$f" in "$prefix"*) covered=yes ;; esac
  done
  [ -z "$covered" ] && UNSHIPPED="$UNSHIPPED $f"
done
if [ -n "$UNSHIPPED" ]; then
  echo "REFUSED: these changed runtime files are not shipped by this script:"
  for f in $UNSHIPPED; do echo "    $f"; done
  echo "  Add the directory to the rsyncs above, or this deploy would leave"
  echo "  production running code that is not in this repository."
  exit 1
fi

# Never ship what nobody reviewed.
#
# The payload comes from a commit, not from this tree, but these two stay: they
# are fail-safes about the operator's own checkout. The development loop builds
# on a `devloop/<task>` branch and only merges to `main` after a clean review,
# and it deploys from `_ship`, on `main`, after the full suite.
branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
if [ "$branch" != "main" ]; then
  echo "refusing to deploy from '$branch'." >&2
  echo "  Only 'main' holds reviewed work. A devloop/* branch is mid-review." >&2
  exit 2
fi
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
  echo "refusing to deploy with uncommitted changes:" >&2
  git -C "$ROOT" status --short >&2
  echo "  Commit them or put them away; what ships must be what was gated." >&2
  exit 2
fi

# The sha contract. It is an environment variable rather than `$1` because `$1`
# is the ssh target and always has been; a positional would be silently taken
# for a host by an older habit. An older commit is allowed on purpose: that is
# how a person redeploys the previous state.
SHA="${QEVIK_DEPLOY_SHA:-}"
if [ -z "$SHA" ]; then
  echo "REFUSED: QEVIK_DEPLOY_SHA is unset; there is no commit to deploy." >&2
  echo "  What ships comes from a commit, never from this working tree." >&2
  exit 2
fi
if ! git -C "$ROOT" rev-parse --verify --quiet "$SHA^{commit}" >/dev/null; then
  echo "REFUSED: QEVIK_DEPLOY_SHA '$SHA' is not a commit in this repository." >&2
  exit 2
fi
SHA="$(git -C "$ROOT" rev-parse --verify "$SHA^{commit}")"
if ! git -C "$ROOT" merge-base --is-ancestor "$SHA" main; then
  echo "REFUSED: $SHA is not landed on main." >&2
  echo "  Only work that reached 'main' has been through review." >&2
  exit 2
fi

# The payload, from the object store. Extracted to a private directory and then
# checked file by file against the commit's own tree: an export that is missing
# a file (an `export-ignore` attribute is enough) or holds different bytes is
# not this commit, and shipping it would be shipping something nobody reviewed.
EXPORT="$(mktemp -d)"
trap 'rm -rf "$EXPORT"' EXIT
if ! git -C "$ROOT" archive --format=tar "$SHA" \
     -- packages/kernel/atlas_kernel infra apps/control/src | tar -x -C "$EXPORT"; then
  echo "REFUSED: could not export $SHA" >&2
  exit 3
fi

EXPECTED=0
MISMATCH=0
while read -r mode type object path; do
  [ "$type" = blob ] || continue
  EXPECTED=$((EXPECTED + 1))
  # A symlink is a blob too -- mode 120000, whose content is the target text and
  # nothing else. `hash-object` on the path would *follow* the link and hash
  # whatever it points at, so it is read as a link and hashed as the bytes the
  # commit actually holds. The kind is checked both ways: a link where the commit
  # has a file, or a file where it has a link, is not this commit even if the
  # bytes happen to agree.
  if [ "$mode" = 120000 ]; then
    if [ -L "$EXPORT/$path" ]; then
      got="$(printf '%s' "$(readlink "$EXPORT/$path")" | git -C "$ROOT" hash-object --stdin)"
    else
      got=""
    fi
  elif [ -L "$EXPORT/$path" ]; then
    got=""
  else
    got="$(git -C "$ROOT" hash-object "$EXPORT/$path" 2>/dev/null || true)"
  fi
  if [ "$got" != "$object" ]; then
    MISMATCH=$((MISMATCH + 1))
    echo "    export mismatch ($mode): $path" >&2
  fi
done <<EOF
$(git -C "$ROOT" ls-tree -r "$SHA" -- packages/kernel/atlas_kernel infra apps/control/src)
EOF
# `-type l` for the same reason: `git archive` writes a symlink as a symlink and
# `rsync -a` preserves it, so a link the commit carries is a blob that was
# extracted. Counting only regular files here would reject every valid commit
# that holds one.
FOUND="$(find "$EXPORT" \( -type f -o -type l \) | wc -l | tr -d ' ')"
if [ "$MISMATCH" -ne 0 ] || [ "$FOUND" -ne "$EXPECTED" ]; then
  echo "REFUSED: the export does not match $SHA" >&2
  echo "  $EXPECTED file(s) in the commit, $FOUND extracted, $MISMATCH mismatched." >&2
  exit 3
fi
echo "export verified: $EXPECTED files from $SHA"

[ -f "$EXPORT/packages/kernel/atlas_kernel/qevik/app.py" ] || {
  echo "REFUSED: $SHA carries no kernel"; exit 1; }

echo "targets: app=$REMOTE_APP console=$CONSOLE_DIR units=$UNIT_DIR rollback=$ROLLBACK_DIR"

echo "==> checking access to $TARGET"
ssh_ true || { echo "REFUSED: no SSH access to $TARGET"; exit 1; }

if [ "$REHEARSE" = 1 ]; then
  # Every transfer a real run would make, planned rather than made, against the
  # real target. The host has no staging twin, so this is the only way to see
  # what a deploy would do before it does it.
  RSYNC_DRY="-n -i"
  PLANNED=0
  plan() {
    local heading="$1" out rc=0
    shift
    out="$(rsync_ "$@")" || rc=$?
    if [ "$rc" -ne 0 ]; then
      echo "FAILED: could not plan the transfer of $heading" >&2
      exit 1
    fi
    echo "==> $heading (dry run)"
    PLANNED=0
    if [ -n "$out" ]; then
      echo "$out" | sed 's/^/    /'
      PLANNED="$(printf '%s\n' "$out" | wc -l | tr -d ' ')"
    fi
    echo "    $PLANNED change(s)"
  }

  plan "the kernel" --delete --exclude '__pycache__' --exclude '*.pyc' \
    "$EXPORT/packages/kernel/atlas_kernel/" "$TARGET:$REMOTE_APP/packages/kernel/atlas_kernel/"
  N_KERNEL="$PLANNED"
  plan "the console" "$EXPORT/apps/control/src/" "$TARGET:$CONSOLE_DIR/"
  N_CONSOLE="$PLANNED"
  plan "infra" --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
    "$EXPORT/infra/" "$TARGET:$REMOTE_APP/infra/"
  N_INFRA="$PLANNED"
  N_UNITS=0
  for unit in "$EXPORT"/infra/qevik-*.service; do
    [ -f "$unit" ] || continue
    plan "$(basename "$unit")" "$unit" "$TARGET:$UNIT_DIR/"
    N_UNITS=$((N_UNITS + PLANNED))
  done

  # Read-only, and each command answers rather than failing, so a host that has
  # never been deployed to by this script still rehearses to the end.
  echo "==> host facts"
  ssh_ "cat $REMOTE_APP/DEPLOYED_SHA 2>/dev/null || echo 'provenance: none recorded'"
  ssh_ "systemctl is-active $SERVICE $WORKERS || true"
  ssh_ "command -v sha256sum || echo 'sha256sum: absent'"

  echo
  echo "REHEARSED sha=$SHA kernel=$N_KERNEL console=$N_CONSOLE infra=$N_INFRA units=$N_UNITS; nothing was written"
  exit 0
fi

echo "==> keeping the current tree, so a bad deploy can be undone"
STAMP="$(date -u +%Y%m%d%H%M%S)"
ssh_ "rm -rf $ROLLBACK_DIR ${ROLLBACK_DIR}-infra && cp -a $REMOTE_APP/packages/kernel/atlas_kernel $ROLLBACK_DIR && cp -a $REMOTE_APP/infra ${ROLLBACK_DIR}-infra 2>/dev/null; echo kept $STAMP"

echo "==> copying the kernel"
rsync_ --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$EXPORT/packages/kernel/atlas_kernel/" "$TARGET:$REMOTE_APP/packages/kernel/atlas_kernel/"

echo "==> copying the console"
rsync_ \
  "$EXPORT/apps/control/src/" "$TARGET:$CONSOLE_DIR/"

# The worker binary lives in infra/ and nothing has ever shipped it. A deploy
# reported success having sent none of it, and the host's own git checkout is
# 181 commits behind and does not track the file at all. Shipping it here rather
# than in a second script: one mechanism, one answer to "how does code reach
# production".
#
# No --delete: infra/ on the host may hold operational files this repository
# does not carry, and a deploy is not the place to discover that.
echo "==> copying infra (the mission worker lives here)"
rsync_ \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
  "$EXPORT/infra/" "$TARGET:$REMOTE_APP/infra/"

# Explicitly, and before anything restarts. `init_db` is idempotent -- every
# statement in it is IF NOT EXISTS -- and it is the only place this repository
# describes its schema, so running it here adds no second mechanism.
#
# It has to be a step of its own. `init_db` is reached only through
# `composition_root`, which this deploy does not restart, so a schema change
# would otherwise be applied whenever `qevik-api` next happened to restart. A
# worker that registers before its column exists fails to register at all.
echo "==> applying the schema"
ssh_ "cd $REMOTE_APP && set -a && . $ENV_FILE && set +a && PYTHONPATH=$REMOTE_APP/packages/kernel $REMOTE_APP/.venv/bin/python -c 'from atlas_kernel.db import init_db; init_db(); print(\"schema applied\")'" || {
  echo "FAILED: the schema could not be applied; nothing was restarted"
  exit 1
}

echo "==> restarting $SERVICE"
ssh_ "chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel $CONSOLE_DIR 2>/dev/null; systemctl restart $SERVICE qevik-api.service"

echo "==> waiting for it to answer"
# Polls rather than sleeping a fixed number: a fixed sleep is either too short
# on a slow boot or wasted on a fast one, and the failure mode of too-short is
# a deploy that reports failure on a service that was about to be fine. The
# patience is stated here rather than borrowed from `ssh_`, which no longer
# retries a `curl` that answers "not up yet" (exit 7).
for attempt in $(seq 1 60); do
  CODE="$(ssh_ "curl -s -o /dev/null -w '%{http_code}' $HEALTH" || echo 000)"
  # 401 is a *pass*: the service is up and refusing an unauthenticated caller,
  # which is what it should do. Treating it as failure would roll back a
  # perfectly good deploy.
  case "$CODE" in
    200|401|403) echo "    up after $((attempt * 2))s (HTTP $CODE)"; break ;;
  esac
  [ "$attempt" = 60 ] && {
    echo "FAILED: $SERVICE did not answer after 120s (last HTTP $CODE)"
    echo "==> putting the previous kernel back"
    ssh_ "rm -rf $REMOTE_APP/packages/kernel/atlas_kernel && cp -a $ROLLBACK_DIR $REMOTE_APP/packages/kernel/atlas_kernel && chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel && systemctl restart $SERVICE"
    ssh_ "journalctl -u $SERVICE -n 30 --no-pager" || true
    exit 1
  }
  sleep 2
done

# What makes "deployed" checkable. The worker reports the sha256 of its own
# source as its registry `version`; if the restarted processes do not report the
# fingerprint of the file just sent, the code running is not the code shipped --
# which is exactly the failure that went unnoticed before, when the deploy
# succeeded and shipped nothing.
FINGERPRINT="$(shasum -a 256 "$EXPORT/infra/mission_worker.py" | cut -c1-12)"
echo "==> restarting the mission workers (expecting fingerprint $FINGERPRINT)"
# Units this repository ships, installed before anything is restarted. A unit
# named in $WORKERS but absent from $UNIT_DIR makes `systemctl restart` return
# non-zero for the whole list -- and `ssh_` then retried it, which stopped and
# started the four healthy workers twelve times and tripped StartLimitBurst on
# all of them. Four dead workers from one missing file.
for unit in "$EXPORT"/infra/qevik-*.service; do
  [ -f "$unit" ] || continue
  rsync_ "$unit" "$TARGET:$UNIT_DIR/" >/dev/null
done
ssh_ "systemctl daemon-reload"

# Not through `ssh_`. Restarting is not something to retry blindly: a failing
# unit answers non-zero every time, and each attempt stops the healthy ones
# again. One attempt per unit, `reset-failed` first so a unit already at its
# start limit can come back, and the fingerprint check below is what decides
# whether the deploy worked.
ssh_ "chown qevik:qevik $REMOTE_APP/infra/mission_worker.py 2>/dev/null; true"
for unit in $WORKERS; do
  ssh "${SSH_OPTS[@]}" -i "$KEY" "$TARGET" \
    "systemctl reset-failed $unit 2>/dev/null; systemctl restart $unit" \
    || echo "    WARNING: $unit did not restart; the fingerprint check follows"
done

# 180s, stated here for the same reason as the health poll above: a worker that
# has not re-registered yet is an answer, not a dropped link, so `ssh_` returns
# it at once instead of retrying it into the patience this loop needs.
#
# Both reads are guarded for that same reason. An unguarded `VAR="$(ssh_ …)"` is
# a simple command under `set -e`, so a single non-zero answer ends the run right
# here -- after the kernel, the console, the infra tree and the units have all
# been written and the workers restarted, and *before* the rollback below can
# run. `ssh_` used to absorb that by retrying every non-zero status twelve times;
# now that it retries only a dropped link, one transient `psql` error arrives
# here as a status. So a registry that will not answer is treated as what it is
# -- an answer that is not the fingerprint, and a reason to keep polling. What
# decides the deploy is still the fingerprint at the end of the patience, and a
# read that never answered says so rather than being reported as absent workers.
REPORTED=""
UNREADABLE=""
for attempt in $(seq 1 60); do
  UNREADABLE=""
  REPORTED="$(ssh_ "sudo -u postgres psql -d qevik -Atc \"SELECT DISTINCT version FROM atlas_workers WHERE id LIKE '%:%' AND version <> '0.0.0'\"" 2>/dev/null | tr -d '\r')" \
    || { REPORTED=""; UNREADABLE=yes; }
  COUNT="$(ssh_ "sudo -u postgres psql -d qevik -Atc \"SELECT count(*) FROM atlas_workers WHERE id LIKE '%:%' AND version = '$FINGERPRINT'\"" 2>/dev/null | tr -d '\r')" \
    || { COUNT=""; UNREADABLE=yes; }
  [ "$REPORTED" = "$FINGERPRINT" ] && [ "${COUNT:-0}" -ge 1 ] && {
    echo "    all $COUNT worker(s) report $FINGERPRINT after $((attempt * 3))s"; break; }
  [ "$attempt" = 60 ] && {
    echo "FAILED: after 180s workers report '${REPORTED:-nothing}', expected '$FINGERPRINT'"
    [ -n "$UNREADABLE" ] && echo "        the worker registry did not answer on the last attempt;"
    [ -n "$UNREADABLE" ] && echo "        'nothing' above may be an unread registry, not idle workers."
    echo "        the code running is not the code that was shipped."
    echo "==> putting the previous kernel and infra back"
    ssh_ "rm -rf $REMOTE_APP/packages/kernel/atlas_kernel && cp -a $ROLLBACK_DIR $REMOTE_APP/packages/kernel/atlas_kernel && chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel"
    ssh_ "[ -d ${ROLLBACK_DIR}-infra ] && rm -rf $REMOTE_APP/infra && cp -a ${ROLLBACK_DIR}-infra $REMOTE_APP/infra"
    ssh_ "systemctl restart $SERVICE $WORKERS" || true
    exit 1
  }
  sleep 3
done

echo "==> what the service now reports"
ssh_ "curl -s $HEALTH -o /dev/null -w 'health: %{http_code}\n'" || true
ssh_ "systemctl is-active $SERVICE"

echo
echo "deployed $SHA. The service answered; that is not the same as the change"
echo "being correct — verify the specific behaviour you deployed for."
