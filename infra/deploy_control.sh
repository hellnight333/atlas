#!/usr/bin/env bash
# Put the kernel and the console on the host that serves app.qevik.ai.
#
#   QEVIK_DEPLOY_SHA=<commit landed on main> \
#     ./infra/deploy_control.sh [--rehearse] [user@host]
#
# The console has no build step and the kernel is pure Python, so a deploy is a
# file copy and a restart. What this adds over `rsync && systemctl restart` is
# the part that keeps it honest:
#
#   * it ships **one immutable commit**: the payload is extracted from the git
#     object store for $QEVIK_DEPLOY_SHA and verified against that commit's own
#     tree, so a checkout or an edit while a copy is in flight cannot change
#     what lands on the host,
#   * it refuses rather than half-deploying,
#   * it **verifies afterwards** instead of reporting success because rsync
#     exited zero, and
#   * it puts the previous tree back if the service does not come up.
#
# A deploy that reports success on a dead service is worse than one that fails,
# because the next person debugs the application instead of the deploy.
#
# Exit codes, which the loop and a person both read: 0 deployed (or rehearsed),
# 1 a preflight refusal or a deploy that failed, 2 an argument or sha refusal,
# 3 the export did not match the commit. Nothing is written to the host before
# the access check.
#
# QEVIK_REMOTE_APP, QEVIK_CONSOLE_DIR, QEVIK_UNIT_DIR, QEVIK_ENV_FILE,
# QEVIK_HEALTH_URL and QEVIK_ROLLBACK_DIR exist so the tests in
# packages/kernel/tests/test_deploy_control.py can point a whole deploy at a
# fake host. Production never sets them: they are accepted only all six
# together and only under QEVIK_TEST_HOST=1, because a seam left behind in an
# operator's shell must never redirect part of a real deploy.
set -euo pipefail

USAGE="usage: QEVIK_DEPLOY_SHA=<commit> $0 [--rehearse] [user@host]"

REHEARSE=0
TARGET=""
POSITIONAL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --rehearse) REHEARSE=1 ;;
    --*)
      echo "REFUSED: unknown option '$1'." >&2
      echo "  $USAGE" >&2
      exit 2 ;;
    *)
      POSITIONAL=$((POSITIONAL + 1))
      if [ "$POSITIONAL" -gt 1 ]; then
        echo "REFUSED: at most one ssh target; the commit is taken from" >&2
        echo "  QEVIK_DEPLOY_SHA, never from an argument." >&2
        echo "  $USAGE" >&2
        exit 2
      fi
      TARGET="$1" ;;
  esac
  shift
done

TARGET="${TARGET:-root@2.28.62.83}"
KEY="$HOME/.ssh/naml_hetzner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE="qevik-control.service"
WORKERS="qevik-worker.service qevik-worker-research.service qevik-worker-delivery.service qevik-worker-publish.service qevik-worker-healthcheck.service"

# The host layout. The defaults are production; the overrides are the test
# seams described in the header.
REMOTE_APP="${QEVIK_REMOTE_APP:-/opt/qevik/atlas}"
CONSOLE_DIR="${QEVIK_CONSOLE_DIR:-/srv/qevik-control}"
UNIT_DIR="${QEVIK_UNIT_DIR:-/etc/systemd/system}"
ENV_FILE="${QEVIK_ENV_FILE:-/opt/qevik/atlas.env}"
HEALTH="${QEVIK_HEALTH_URL:-http://127.0.0.1:8081/api/health}"
ROLLBACK_DIR="${QEVIK_ROLLBACK_DIR:-/opt/qevik/rollback}"

SEAMS=0
for seam in "${QEVIK_REMOTE_APP:-}" "${QEVIK_CONSOLE_DIR:-}" "${QEVIK_UNIT_DIR:-}" \
            "${QEVIK_ENV_FILE:-}" "${QEVIK_HEALTH_URL:-}" "${QEVIK_ROLLBACK_DIR:-}"; do
  if [ -n "$seam" ]; then SEAMS=$((SEAMS + 1)); fi
done
# Fail closed in both directions: a seam without the flag, and the flag without
# all six seams. Half a redirection is the dangerous state — part of the deploy
# would go to a fake host and the rest to production.
if [ "${QEVIK_TEST_HOST:-}" = 1 ] || [ "$SEAMS" -gt 0 ]; then
  if [ "${QEVIK_TEST_HOST:-}" != 1 ] || [ "$SEAMS" -ne 6 ]; then
    echo "REFUSED: the test seams are partially set ($SEAMS of 6 host paths," >&2
    echo "  QEVIK_TEST_HOST='${QEVIK_TEST_HOST:-}')." >&2
    echo "  QEVIK_REMOTE_APP, QEVIK_CONSOLE_DIR, QEVIK_UNIT_DIR, QEVIK_ENV_FILE," >&2
    echo "  QEVIK_HEALTH_URL and QEVIK_ROLLBACK_DIR are accepted only all six" >&2
    echo "  together and only with QEVIK_TEST_HOST=1. Unset them all to deploy." >&2
    exit 2
  fi
fi

echo "targets: app=$REMOTE_APP console=$CONSOLE_DIR units=$UNIT_DIR rollback=$ROLLBACK_DIR"

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
# that may have half-run costs nothing. Only exit 255 is retried: that is ssh's
# own status for every connection-level failure, and any other status is the
# remote command's own answer, which retrying twelve times would turn into 165 s
# of waiting for a result the first attempt already gave.
ssh_() {
  local try rc
  for try in 1 2 3 4 5 6 7 8 9 10 11 12; do
    rc=0
    ssh "${SSH_OPTS[@]}" -i "$KEY" "$TARGET" "$@" || rc=$?
    if [ "$rc" = 0 ]; then return 0; fi
    if [ "$rc" != 255 ]; then return "$rc"; fi
    if [ "$try" = 12 ]; then return 255; fi
    echo "    (link dropped; retry $try)" >&2
    sleep $(( try < 6 ? try * 3 : 20 ))
  done
}
#: rsync resumes rather than restarting when a transfer is cut mid-file.
RSYNC_SSH="ssh ${SSH_OPTS[*]} -i $KEY"

# Same reason as `ssh_`, and safe for the same reason: rsync is idempotent by
# construction, and `--partial` means a retry continues the file it was cut in
# rather than starting the tree again. Unlike ssh, rsync reports a cut transport
# as its own status (12 and 30 among them), so every non-zero exit stays retried.
rsync_() {
  local try
  for try in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if rsync -a --partial --timeout=120 -e "$RSYNC_SSH" "$@"; then return 0; fi
    [ "$try" = 12 ] && return 1
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
# host has, not against the last commit. This reads the operator's tree on
# purpose: it is a fail-safe about the machine the deploy is run from, not a
# source of anything that ships.
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
# The payload comes from a commit, but the tree still has to be the reviewed
# one: a deploy run from a `devloop/<task>` branch, or with work in progress
# lying around, is a deploy nobody has finished looking at. The loop deploys
# from `_ship`, on `main`, after the full suite.
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

# The sha contract. The commit is named by the caller and nothing else: $1 is
# still the ssh target, and reading HEAD would put us back to trusting whatever
# the tree happens to be at this instant.
if [ -z "${QEVIK_DEPLOY_SHA:-}" ]; then
  echo "REFUSED: QEVIK_DEPLOY_SHA is unset; there is no commit to deploy." >&2
  echo "  $USAGE" >&2
  exit 2
fi
SHA="$(git -C "$ROOT" rev-parse --verify --quiet "${QEVIK_DEPLOY_SHA}^{commit}" || true)"
if [ -z "$SHA" ]; then
  echo "REFUSED: '$QEVIK_DEPLOY_SHA' is not a commit in this repository." >&2
  exit 2
fi
# An older commit is allowed on purpose: redeploying the previous state is
# `QEVIK_DEPLOY_SHA=<the older commit>`. What is refused is a commit that never
# passed review, which is exactly a commit that is not on `main`.
if ! git -C "$ROOT" merge-base --is-ancestor "$SHA" main; then
  echo "REFUSED: $SHA is not landed on main." >&2
  echo "  Only reviewed work reaches production." >&2
  exit 2
fi
echo "==> deploying $SHA"

# The payload. Extracted from the object store, so the working tree can be
# checked out, edited or rebuilt for the rest of this run without changing a
# byte of what ships.
EXPORT="$(mktemp -d)"
trap 'rm -rf "$EXPORT"' EXIT
if ! git -C "$ROOT" archive --format=tar "$SHA" \
     -- packages/kernel/atlas_kernel infra apps/control/src | tar -x -C "$EXPORT"; then
  echo "REFUSED: $SHA could not be exported." >&2
  exit 3
fi

# Verify the export against the commit before anything reads it. `git archive`
# honours attributes (export-ignore above all), so "the tar unpacked" is not
# the same as "this is the commit": every blob the commit lists must be present
# with that blob's id, and the export must hold nothing else.
#
# Symlinks are listed as blobs of mode 120000 whose content is the link text,
# and `find -type f` does not see them, so both the hash and the count treat
# them as their own kind. A tracked link under a shipped prefix would otherwise
# fail every deploy. `core.quotepath=false` likewise keeps a UTF-8 filename
# listed as itself; a path git still has to quote is not found under the export
# and counts as a mismatch, which is the safe way for this check to be wrong.
TAB="$(printf '\t')"
EXPECTED=0
MISMATCHES=0
while IFS= read -r line; do
  [ -n "$line" ] || continue
  mode="${line%% *}"
  rest="${line#* }"
  kind="${rest%% *}"
  rest="${rest#* }"
  want="${rest%%"$TAB"*}"
  path="${rest#*"$TAB"}"
  [ "$kind" = blob ] || continue
  EXPECTED=$((EXPECTED + 1))
  got=""
  if [ "$mode" = 120000 ]; then
    if [ -L "$EXPORT/$path" ]; then
      got="$(printf '%s' "$(readlink "$EXPORT/$path")" | git -C "$ROOT" hash-object --stdin)"
    fi
  else
    if [ -f "$EXPORT/$path" ] && [ ! -L "$EXPORT/$path" ]; then
      got="$(git -C "$ROOT" hash-object "$EXPORT/$path")"
    fi
  fi
  if [ "$got" != "$want" ]; then
    echo "export mismatch ($mode): $path" >&2
    MISMATCHES=$((MISMATCHES + 1))
  fi
done <<< "$(git -C "$ROOT" -c core.quotepath=false ls-tree -r "$SHA" \
             -- packages/kernel/atlas_kernel infra apps/control/src)"

FOUND="$(find "$EXPORT" \( -type f -o -type l \) -print | wc -l | tr -d ' ')"
if [ "$MISMATCHES" != 0 ] || [ "$FOUND" != "$EXPECTED" ]; then
  echo "REFUSED: the export does not match $SHA" >&2
  echo "  $FOUND file(s) exported, $EXPECTED in the commit, $MISMATCHES mismatch(es)." >&2
  exit 3
fi
echo "export verified: $EXPECTED files from $SHA"

# What the commit has to carry to be deployable at all, asked while the host is
# still untouched. The kernel entrypoint is one. `infra/mission_worker.py` is
# the other, and the fingerprint is taken here rather than after the copies on
# purpose: an older landed commit -- which this script accepts deliberately, so
# that redeploying the previous state is one variable -- may predate that file
# or remove it, and `shasum` on a missing path is a failed pipeline that under
# `set -o pipefail` aborts the script where it stands. After the copies and the
# restarts, "where it stands" is production written and the rollback below
# never reached. Before them, it is a refusal that costs nothing.
[ -f "$EXPORT/packages/kernel/atlas_kernel/qevik/app.py" ] || {
  echo "REFUSED: $SHA carries no kernel"; exit 1; }
[ -f "$EXPORT/infra/mission_worker.py" ] || {
  echo "REFUSED: $SHA carries no infra/mission_worker.py, so there is nothing to"
  echo "  fingerprint and no way to tell whether the workers run what was sent."
  exit 1; }
FINGERPRINT="$(shasum -a 256 "$EXPORT/infra/mission_worker.py" | cut -c1-12)"

echo "==> checking access to $TARGET"
ssh_ true || { echo "REFUSED: no SSH access to $TARGET"; exit 1; }

# A rehearsal plans every transfer a real run would make and reads a few facts
# off the host. It is the only way to exercise a changed deploy path against
# this host before the change is production: there is no staging twin.
if [ "$REHEARSE" = 1 ]; then
  PLANNED=0
  plan_rsync() {  # heading, then exactly the arguments the real transfer uses
    local heading="$1"; shift
    local out
    echo "==> [rehearse] $heading"
    out="$(rsync_ -n -i "$@")" || {
      echo "FAILED: that transfer could not be planned"; exit 1; }
    PLANNED=0
    if [ -n "$out" ]; then
      printf '%s\n' "$out" | sed 's/^/    /'
      PLANNED="$(printf '%s\n' "$out" | wc -l | tr -d ' ')"
    fi
    echo "    $PLANNED change(s)"
  }

  plan_rsync "the kernel" --delete \
    --exclude '__pycache__' --exclude '*.pyc' \
    "$EXPORT/packages/kernel/atlas_kernel/" "$TARGET:$REMOTE_APP/packages/kernel/atlas_kernel/"
  N_KERNEL="$PLANNED"
  plan_rsync "the console" \
    "$EXPORT/apps/control/src/" "$TARGET:$CONSOLE_DIR/"
  N_CONSOLE="$PLANNED"
  plan_rsync "infra" \
    --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
    "$EXPORT/infra/" "$TARGET:$REMOTE_APP/infra/"
  N_INFRA="$PLANNED"
  N_UNITS=0
  for unit in "$EXPORT"/infra/qevik-*.service; do
    [ -f "$unit" ] || continue
    plan_rsync "unit $(basename "$unit")" "$unit" "$TARGET:$UNIT_DIR/"
    N_UNITS=$((N_UNITS + PLANNED))
  done

  # Read-only, and each command answers rather than failing: "absent" is a fact
  # about the host, not an error in the rehearsal.
  echo "==> [rehearse] host facts"
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
# a deploy that reports failure on a service that was about to be fine.
#
# The patience is stated here rather than borrowed from `ssh_`: curl exits 7
# while the service is still booting, and that is now the remote command's own
# answer, returned at once instead of retried.
for attempt in $(seq 1 60); do
  CODE="$(ssh_ "curl -s -o /dev/null -w '%{http_code}' $HEALTH" || echo 000)"
  # 401 is a *pass*: the service is up and refusing an unauthenticated caller,
  # which is what it should do. Treating it as failure would roll back a
  # perfectly good deploy.
  case "$CODE" in
    200|401|403) echo "    up after ${attempt} attempt(s) (HTTP $CODE)"; break ;;
  esac
  if [ "$attempt" = 60 ]; then
    echo "FAILED: $SERVICE did not answer in 120s (last HTTP $CODE)"
    echo "==> putting the previous kernel back"
    ssh_ "rm -rf $REMOTE_APP/packages/kernel/atlas_kernel && cp -a $ROLLBACK_DIR $REMOTE_APP/packages/kernel/atlas_kernel && chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel && systemctl restart $SERVICE"
    ssh_ "journalctl -u $SERVICE -n 30 --no-pager" || true
    exit 1
  fi
  sleep 2
done

# What makes "deployed" checkable. The worker reports the sha256 of its own
# source as its registry `version`; if the restarted processes do not report the
# fingerprint of the file just sent, the code running is not the code shipped --
# which is exactly the failure that went unnoticed before, when the deploy
# succeeded and shipped nothing. $FINGERPRINT was taken from the export back in
# the preflight, so it fingerprints the commit rather than the tree, and this
# far in there is nothing left that could fail to produce it.
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

# Both reads are guarded. A registry that answers non-zero is now an answer
# rather than a retry, and an unguarded `$(ssh_ …)` under `set -e` would abort
# the script here -- after production has been fully written and before the
# rollback below. "Could not read the registry" and "the workers report the
# wrong thing" are different failures and say so.
REPORTED=""
COUNT=""
READ_OK=""
for attempt in $(seq 1 60); do
  READ_OK=yes
  REPORTED="$(ssh_ "sudo -u postgres psql -d qevik -Atc \"SELECT DISTINCT version FROM atlas_workers WHERE id LIKE '%:%' AND version <> '0.0.0'\"" 2>/dev/null | tr -d '\r')" || READ_OK=""
  if [ -n "$READ_OK" ]; then
    COUNT="$(ssh_ "sudo -u postgres psql -d qevik -Atc \"SELECT count(*) FROM atlas_workers WHERE id LIKE '%:%' AND version = '$FINGERPRINT'\"" 2>/dev/null | tr -d '\r')" || READ_OK=""
  fi
  case "$COUNT" in ''|*[!0-9]*) COUNT_N=0 ;; *) COUNT_N="$COUNT" ;; esac
  if [ -n "$READ_OK" ] && [ "$REPORTED" = "$FINGERPRINT" ] && [ "$COUNT_N" -ge 1 ]; then
    echo "    all $COUNT worker(s) report $FINGERPRINT after ${attempt} attempt(s)"; break
  fi
  if [ "$attempt" = 60 ]; then
    if [ -z "$READ_OK" ]; then
      echo "FAILED: the worker registry could not be read in 180s, so what the"
      echo "        workers run is unknown and this deploy is not verified."
    else
      echo "FAILED: after 180s workers report '${REPORTED:-nothing}', expected '$FINGERPRINT'"
      echo "        the code running is not the code that was shipped."
    fi
    echo "==> putting the previous kernel and infra back"
    ssh_ "rm -rf $REMOTE_APP/packages/kernel/atlas_kernel && cp -a $ROLLBACK_DIR $REMOTE_APP/packages/kernel/atlas_kernel && chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel"
    ssh_ "[ -d ${ROLLBACK_DIR}-infra ] && rm -rf $REMOTE_APP/infra && cp -a ${ROLLBACK_DIR}-infra $REMOTE_APP/infra"
    ssh_ "systemctl restart $SERVICE $WORKERS" || true
    exit 1
  fi
  sleep 3
done

echo "==> what the service now reports"
ssh_ "curl -s $HEALTH -o /dev/null -w 'health: %{http_code}\n'" || true
ssh_ "systemctl is-active $SERVICE"

echo
echo "deployed $SHA. The service answered; that is not the same as the change"
echo "being correct — verify the specific behaviour you deployed for."
