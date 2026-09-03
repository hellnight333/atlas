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
# 1 a preflight refusal or a deploy that failed and was rolled back, 2 an
# argument or sha refusal, 3 the export did not match the commit, 4 the rollback
# could not put everything back, 5 a rehearsal found the host not ready.
# Nothing is written to the host before the access check.
#
# After a deploy the host says what it holds: $REMOTE_APP/DEPLOYED_SHA is the
# provenance marker and $REMOTE_APP/DEPLOYED_MANIFEST is the per-file sha256
# manifest the host itself checked. Only `state=installed` means "the host holds
# this sha"; every other state is an admission.
#
# QEVIK_REMOTE_APP, QEVIK_CONSOLE_DIR, QEVIK_UNIT_DIR, QEVIK_ENV_FILE,
# QEVIK_HEALTH_URL and QEVIK_ROLLBACK_DIR exist so the tests in
# packages/kernel/tests/test_deploy_control.py can point a whole deploy at a
# fake host. Production never sets them: they are accepted only all six
# together and only under QEVIK_TEST_HOST=1, because a seam left behind in an
# operator's shell must never redirect part of a real deploy.
set -euo pipefail

USAGE="usage: QEVIK_DEPLOY_SHA=<commit> $0 [--rehearse] --target <name>|user@host"

REHEARSE=0
TARGET_SPEC=""
POSITIONAL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --rehearse) REHEARSE=1 ;;
    --target)
      shift
      [ $# -gt 0 ] || { echo "REFUSED: --target needs a name." >&2; echo "  $USAGE" >&2; exit 2; }
      TARGET_SPEC="$1" ;;
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
      TARGET_SPEC="$1" ;;
  esac
  shift
done

# Where this deploy is allowed to go, and with which key: one reviewed registry
# (infra/deploy_targets.conf), no built-in production default, no fallback on a
# typo. What stood here was the old production IP and the shared operator key,
# hard-coded — a host and an identity that a second production host makes
# actively dangerous, since the second host must never accept that key.
. "$(cd "$(dirname "$0")" && pwd)/deploy_target.sh"
qevik_resolve_target "$TARGET_SPEC"
TARGET="$QEVIK_TARGET_HOST"
KEY="$QEVIK_TARGET_KEY"
echo "target: $QEVIK_TARGET_NAME -> $TARGET (identity ${KEY:-ssh_config})"
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
#: The service account the units run as, and therefore the identity the schema
#: step runs as: same user, same environment, same view of the database.
APP_USER="${QEVIK_APP_USER:-qevik}"

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
          -o ServerAliveInterval=10 -o ServerAliveCountMax=6 -o IdentitiesOnly=yes)
# `ConnectionAttempts` retries the TCP connect, which is not where this link
# fails: it fails *after* connecting, during the banner exchange. So each call
# is retried here instead. Every command this script sends is idempotent — copy
# a rollback, apply the schema, chown, restart, read a status — so repeating one
# that may have half-run costs nothing. Only exit 255 is retried: that is ssh's
# own status for every connection-level failure, and any other status is the
# remote command's own answer, which retrying twelve times would turn into 165 s
# of waiting for a result the first attempt already gave.
# Empty when the registry entry defers to ~/.ssh/config; a pinned identity
# otherwise. Expanded unquoted on purpose: it is either two words or none.
KEY_ARGS=""
[ -n "$KEY" ] && KEY_ARGS="-i $KEY"

ssh_() {
  local try rc
  for try in 1 2 3 4 5 6 7 8 9 10 11 12; do
    rc=0
    # shellcheck disable=SC2086
    ssh "${SSH_OPTS[@]}" $KEY_ARGS "$TARGET" "$@" || rc=$?
    if [ "$rc" = 0 ]; then return 0; fi
    if [ "$rc" != 255 ]; then return "$rc"; fi
    if [ "$try" = 12 ]; then return 255; fi
    echo "    (link dropped; retry $try)" >&2
    sleep $(( try < 6 ? try * 3 : 20 ))
  done
}
#: rsync resumes rather than restarting when a transfer is cut mid-file.
RSYNC_SSH="ssh ${SSH_OPTS[*]} $KEY_ARGS"

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

# --- provenance, and the one rollback ----------------------------------------
#
# One rule governs everything below. No deployment or rollback path may leave
# DEPLOYED_SHA stale, inconsistent with the installed bytes, or report an
# outcome on the strength of a marker write nobody checked. So there is exactly
# one writer of the marker, it verifies its own write, and no outcome — not
# `deployed`, not `ROLLED BACK`, not `ROLLBACK INCOMPLETE` — is printed or given
# an exit code before that writer has returned zero for the marker that outcome
# claims.

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# The only place in this script that writes $REMOTE_APP/DEPLOYED_SHA. It writes
# atomically (tmp + mv), then reads the marker back off the host and compares its
# `state=` and `sha=` with what was sent; anything else returns non-zero and the
# caller downgrades what it reports.
#
#   provenance_write <state> <field>...         write state= plus these fields
#   provenance_write --from-copy <state> <sha>  put the saved marker back verbatim
provenance_write() {
  local from_copy=0 state want_sha field args rc got got_state got_sha
  if [ "$1" = "--from-copy" ]; then from_copy=1; shift; fi
  state="$1"; shift
  want_sha=""
  rc=0
  if [ "$from_copy" = 1 ]; then
    want_sha="$1"; shift
    ssh_ "set -e; cp ${ROLLBACK_DIR}-provenance/DEPLOYED_SHA $REMOTE_APP/DEPLOYED_SHA.tmp; mv $REMOTE_APP/DEPLOYED_SHA.tmp $REMOTE_APP/DEPLOYED_SHA" || rc=$?
  else
    args="'state=$state'"
    for field in "$@"; do
      case "$field" in sha=*) want_sha="${field#sha=}" ;; esac
      args="$args '$field'"
    done
    ssh_ "set -e; printf '%s\\n' $args > $REMOTE_APP/DEPLOYED_SHA.tmp; mv $REMOTE_APP/DEPLOYED_SHA.tmp $REMOTE_APP/DEPLOYED_SHA" || rc=$?
  fi
  if [ "$rc" != 0 ]; then
    echo "provenance: the marker write for state=$state failed (rc=$rc)" >&2
    return 1
  fi
  got=""
  got="$(ssh_ "cat $REMOTE_APP/DEPLOYED_SHA")" || got=""
  got_state="$(printf '%s\n' "$got" | sed -n 's/^state=//p' | head -1 || true)"
  got_sha="$(printf '%s\n' "$got" | sed -n 's/^sha=//p' | head -1 || true)"
  if [ "$got_state" != "$state" ] || [ "$got_sha" != "$want_sha" ]; then
    echo "provenance: the marker does not read back as it was written." >&2
    echo "  wanted state=$state sha=${want_sha:-<none>};" >&2
    echo "  host says state=${got_state:-<none>} sha=${got_sha:-<none>}." >&2
    return 1
  fi
  return 0
}

RESTORED=""
NOT_RESTORED=""
RESTART_FAILED=""

note_restored() { RESTORED="${RESTORED:+$RESTORED,}$1"; }
note_not_restored() {
  local kept="" name
  case ",$NOT_RESTORED," in *",$1,"*) return 0 ;; esac
  NOT_RESTORED="${NOT_RESTORED:+$NOT_RESTORED,}$1"
  # Nothing is both restored and not restored: the measurement below can
  # withdraw a target the copy thought it had put back.
  for name in $(printf '%s\n' "$RESTORED" | tr ',' ' '); do
    if [ "$name" != "$1" ]; then kept="${kept:+$kept,}$name"; fi
  done
  RESTORED="$kept"
  return 0
}

# A target is restored only from its own snapshot. `exit 3` is the host saying
# the target did not exist before this deploy: there is nothing to put back, so
# nothing is removed and the target is reported as NOT restored rather than
# replaced with whatever directory happens to be lying at the snapshot path.
restore_target() {  # name, snapshot, live path
  local name="$1" copy="$2" live="$3" rc=0
  ssh_ "set -e; if [ -e ${ROLLBACK_DIR}-absent/$name ]; then exit 3; fi; [ -d $copy ]; rm -rf $live; cp -a $copy $live" || rc=$?
  if [ "$rc" = 0 ]; then
    echo "    restored: $name"
    note_restored "$name"
    return 0
  fi
  if [ "$rc" = 3 ]; then
    echo "    NOT restored: $name was absent before this deploy; nothing was removed"
  else
    echo "    NOT restored: $name (rc=$rc)"
  fi
  note_not_restored "$name"
}

# Every failure after the snapshots exist ends here, and this is the only place
# that puts anything back. Order matters: demote the marker first so
# `state=installed` cannot survive into a rollback under any ordering of the
# failures below; settle the bytes; write the marker that describes them; only
# then restart; only then choose a word and an exit code.
rollback_and_report() {
  local rc=0 unit
  echo "==> rolling back"
  RESTORED=""; NOT_RESTORED=""; RESTART_FAILED=""

  if ! provenance_write rolling-back "attempted_sha=$SHA" \
       "previous_sha=${PREV_SHA:-unknown}" "started_at=$(now_utc)"; then
    echo "    NOT restored: provenance (the marker could not be demoted)"
    note_not_restored provenance
  fi

  ssh_ "rm -f $REMOTE_APP/DEPLOYED_MANIFEST.new" \
    || echo "    warning: DEPLOYED_MANIFEST.new could not be removed"

  restore_target kernel "$ROLLBACK_DIR" "$REMOTE_APP/packages/kernel/atlas_kernel"
  restore_target infra "${ROLLBACK_DIR}-infra" "$REMOTE_APP/infra"
  restore_target console "${ROLLBACK_DIR}-console" "$CONSOLE_DIR"
  # The saved set replaces what is installed, so a unit this deploy added and
  # the saved set does not carry is removed with it.
  rc=0
  ssh_ "set -e; if [ -e ${ROLLBACK_DIR}-absent/units ]; then exit 3; fi; [ -d ${ROLLBACK_DIR}-units ]; rm -f $UNIT_DIR/qevik-*.service $UNIT_DIR/qevik-*.timer; cp -a ${ROLLBACK_DIR}-units/. $UNIT_DIR/; systemctl daemon-reload" || rc=$?
  if [ "$rc" = 0 ]; then
    echo "    restored: units"
    note_restored units
  elif [ "$rc" = 3 ]; then
    echo "    NOT restored: units were absent before this deploy; nothing was removed"
    note_not_restored units
  else
    echo "    NOT restored: units (rc=$rc)"
    note_not_restored units
  fi

  # Measure rather than assume: the previous manifest is the only description of
  # what the host held, so the restored bytes are checked against it.
  if [ "${PREV_MANIFEST_PRESENT:-0}" = 1 ]; then
    rc=0
    ssh_ "set -e; cp ${ROLLBACK_DIR}-provenance/DEPLOYED_MANIFEST $REMOTE_APP/DEPLOYED_MANIFEST; sha256sum --check --quiet $REMOTE_APP/DEPLOYED_MANIFEST" || rc=$?
    if [ "$rc" = 0 ]; then
      echo "    the restored bytes match the previous manifest"
    else
      echo "    the restored bytes do NOT match the previous manifest (rc=$rc)"
      note_not_restored kernel
      note_not_restored infra
      note_not_restored console
      note_not_restored units
    fi
  else
    # Nothing recorded what the host held, so the manifest for $SHA must go: it
    # would otherwise describe bytes that are no longer there. A removal that
    # fails is a provenance failure and not a warning — the alternative is a
    # host that gets the previous marker back (or `rolled-back sha=unknown`) and
    # reports `ROLLED BACK`, while DEPLOYED_MANIFEST next to it still lists the
    # files of the attempted sha. Two provenance files contradicting each other
    # is worse than either being missing, because each one looks authoritative.
    if ssh_ "rm -f $REMOTE_APP/DEPLOYED_MANIFEST"; then
      echo "    no previous manifest was recorded; the restored bytes were not measured"
    else
      echo "    NOT restored: provenance (the manifest for $SHA could not be removed,"
      echo "                  so it still describes bytes this rollback replaced)"
      note_not_restored provenance
    fi
  fi

  # The marker before the restarts: the bytes are settled now, so a restart that
  # hangs or a script killed during one leaves a marker that is already true.
  if [ -z "$NOT_RESTORED" ]; then
    if [ "${PREV_MARKER_PRESENT:-0}" = 1 ]; then
      provenance_write --from-copy "$PREV_STATE" "$PREV_SHA" || {
        echo "    NOT restored: provenance (the previous marker could not be put back)"
        note_not_restored provenance; }
    else
      provenance_write rolled-back "sha=unknown" "attempted_sha=$SHA" \
        "rolled_back_at=$(now_utc)" \
        "note=no provenance was recorded before this deploy" || {
        echo "    NOT restored: provenance (the rolled-back marker could not be written)"
        note_not_restored provenance; }
    fi
  fi
  if [ -n "$NOT_RESTORED" ]; then
    if ! provenance_write rollback-incomplete "attempted_sha=$SHA" \
         "restored=${RESTORED:-none}" "not_restored=$NOT_RESTORED" \
         "rolled_back_at=$(now_utc)"; then
      echo "provenance: marker write failed; host marker state unknown"
    fi
  fi

  echo "==> restarting, the way a deploy restarts"
  ssh_ "chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel $CONSOLE_DIR 2>/dev/null; systemctl restart $SERVICE qevik-api.service" || {
    echo "    restart failed: $SERVICE qevik-api.service"; RESTART_FAILED=1; }
  # Not through `ssh_`, for the reason the deploy gives: retrying a restart
  # stops the healthy units again.
  for unit in $WORKERS; do
    ssh "${SSH_OPTS[@]}" $KEY_ARGS "$TARGET" \
      "systemctl reset-failed $unit 2>/dev/null; systemctl restart $unit" \
      || { echo "    restart failed: $unit"; RESTART_FAILED=1; }
  done
  ssh_ "journalctl -u $SERVICE -n 30 --no-pager" || true

  if [ -z "$NOT_RESTORED" ] && [ -z "$RESTART_FAILED" ]; then
    echo "ROLLED BACK: ${RESTORED:-nothing had been changed}"
    exit 1
  fi
  if [ -n "$NOT_RESTORED" ]; then
    echo "ROLLBACK INCOMPLETE: $NOT_RESTORED"
  else
    echo "ROLLBACK INCOMPLETE: every target was restored but a service did not restart"
  fi
  echo "  A person has to look: $REMOTE_APP/DEPLOYED_SHA is what the host admits to."
  exit 4
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
WORK="$(mktemp -d)"   # the manifest is built here, outside the export
trap 'rm -rf "$EXPORT" "$WORK"' EXIT
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

# The host manifest verifies files by their content, and a symlink has none: it
# would be listed as its target's bytes or not at all, and either way the check
# would pass on a host where the link points somewhere else. So a commit that
# ships a link into a deployed subtree is refused here, before the host is
# touched, which is what makes the manifest's `-type f` exhaustive below.
for subtree in packages/kernel/atlas_kernel infra apps/control/src; do
  [ -d "$EXPORT/$subtree" ] || continue
  if [ -n "$(find "$EXPORT/$subtree" -type l -print 2>/dev/null | head -1)" ]; then
    echo "REFUSED: $SHA ships a symlink under $subtree; the manifest cannot verify links" >&2
    find "$EXPORT/$subtree" -type l -print | sed "s|^$EXPORT/|    |" >&2
    exit 2
  fi
done

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

# What each transfer leaves behind, named once.
#
# The manifest is only a guarantee if it lists every file the deploy places: a
# file that is sent but not listed is a deployed file nobody checked, and the
# host can then answer "everything matches" without ever having looked at it.
# The exclusions used to be written twice — as rsync flags on the transfers and
# as `find` predicates in the manifest — and the two lists disagreed: the
# console transfer excluded nothing while the manifest dropped `*.pyc`,
# `__pycache__` and `.pytest_cache` from it, and the kernel transfer did not
# exclude `.pytest_cache` while the manifest did. A commit that tracks such a
# path under a shipped prefix — git does not care what a file is named — would
# have been copied to the host and left out of the check.
#
# So each set is named once here and used twice from it: `rsync --exclude` for
# the transfer, `find` predicates for the manifest. The console has no
# exclusions, which is why it has no set: everything the commit carries under
# apps/control/src ships and is verified.
KERNEL_EXCLUDE=(__pycache__ '*.pyc')
INFRA_EXCLUDE=(__pycache__ '*.pyc' .pytest_cache)
KERNEL_RSYNC_EXCLUDE=()
for name in "${KERNEL_EXCLUDE[@]}"; do KERNEL_RSYNC_EXCLUDE+=(--exclude "$name"); done
INFRA_RSYNC_EXCLUDE=()
for name in "${INFRA_EXCLUDE[@]}"; do INFRA_RSYNC_EXCLUDE+=(--exclude "$name"); done

# The manifest: one line per regular file this deploy will place, in the
# `sha256sum --check` format — `<sha256>  <absolute host path>` — computed from
# the export, so it describes the commit and not the host. The refusal above
# means no deployed subtree holds a symlink, so `-type f` is exhaustive.
MANIFEST="$WORK/DEPLOYED_MANIFEST"
manifest_lines() {  # export subtree, host prefix (trailing slash), then exactly
                    # the names that subtree's transfer excludes
  local src="$1" dest="$2" f rel name args
  shift 2
  [ -d "$src" ] || return 0
  # `rsync --exclude NAME` drops any file or directory of that name anywhere in
  # the transfer, and everything below such a directory; these two predicates
  # are that rule. The array starts non-empty so `set -u` is satisfied on the
  # bash 3.2 this also has to run under.
  args=("$src" -type f)
  for name in "$@"; do
    args+=(! -name "$name" ! -path "*/$name/*")
  done
  find "${args[@]}" -print | while IFS= read -r f; do
    rel="${f#"$src/"}"
    printf '%s  %s%s\n' "$(shasum -a 256 "$f" | cut -d' ' -f1)" "$dest" "$rel"
  done
}
{
  manifest_lines "$EXPORT/packages/kernel/atlas_kernel" \
    "$REMOTE_APP/packages/kernel/atlas_kernel/" "${KERNEL_EXCLUDE[@]}"
  manifest_lines "$EXPORT/infra" "$REMOTE_APP/infra/" "${INFRA_EXCLUDE[@]}"
  manifest_lines "$EXPORT/apps/control/src" "$CONSOLE_DIR/"
  # A shipped unit lands twice: in infra/ and, installed, in $UNIT_DIR.
  for unit in "$EXPORT"/infra/qevik-*.service "$EXPORT"/infra/qevik-*.timer; do
    [ -e "$unit" ] || continue
    printf '%s  %s/%s\n' "$(shasum -a 256 "$unit" | cut -d' ' -f1)" \
      "$UNIT_DIR" "$(basename "$unit")"
  done
} | LC_ALL=C sort > "$MANIFEST"
MANIFEST_FILES="$(wc -l < "$MANIFEST" | tr -d ' ')"
MANIFEST_SHA="$(shasum -a 256 "$MANIFEST" | cut -d' ' -f1)"

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

  plan_rsync "the kernel" --delete "${KERNEL_RSYNC_EXCLUDE[@]}" \
    "$EXPORT/packages/kernel/atlas_kernel/" "$TARGET:$REMOTE_APP/packages/kernel/atlas_kernel/"
  N_KERNEL="$PLANNED"
  plan_rsync "the console" \
    "$EXPORT/apps/control/src/" "$TARGET:$CONSOLE_DIR/"
  N_CONSOLE="$PLANNED"
  plan_rsync "infra" "${INFRA_RSYNC_EXCLUDE[@]}" \
    "$EXPORT/infra/" "$TARGET:$REMOTE_APP/infra/"
  N_INFRA="$PLANNED"
  N_UNITS=0
  for unit in "$EXPORT"/infra/qevik-*.service "$EXPORT"/infra/qevik-*.timer; do
    [ -f "$unit" ] || continue
    plan_rsync "unit $(basename "$unit")" "$unit" "$TARGET:$UNIT_DIR/"
    N_UNITS=$((N_UNITS + PLANNED))
  done
  # The manifest is a transfer like any other, and the only one whose
  # destination is the application root rather than a subtree below it. A
  # rehearsal that skipped it could report a host ready for a deploy that then
  # fails — and rolls back — at the last copy, because $REMOTE_APP itself is
  # missing or not writable while every subtree under it is fine.
  plan_rsync "the manifest" "$MANIFEST" "$TARGET:$REMOTE_APP/DEPLOYED_MANIFEST.new"
  N_MANIFEST="$PLANNED"

  # Read-only, and each command answers rather than failing: "absent" is a fact
  # about the host, not an error in the rehearsal.
  echo "==> [rehearse] host facts"
  echo "manifest: $MANIFEST_FILES file(s) for $SHA, digest $MANIFEST_SHA"
  ssh_ "cat $REMOTE_APP/DEPLOYED_SHA 2>/dev/null || echo 'provenance: none recorded'"
  ssh_ "systemctl is-active $SERVICE $WORKERS || true"
  ssh_ "command -v sha256sum || echo 'sha256sum: absent'"

  # The host-side check on a known input — the sha256 of the empty file against
  # /dev/null — because a real deploy refuses if this cannot run, and there is no
  # staging twin on which to discover that. The command answers rather than
  # failing, so a broken tool is a fact rather than an aborted rehearsal.
  EMPTY_SHA256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  CHECKS=""
  CHECKS="$(ssh_ "printf '%s  %s\\n' $EMPTY_SHA256 /dev/null | sha256sum --check --quiet - >/dev/null 2>&1 && echo works || echo broken")" || CHECKS=broken
  if [ "$CHECKS" = works ]; then
    echo "host sha256sum --check: works"
  else
    echo "host sha256sum --check: DOES NOT WORK"
    echo
    echo "NOT READY: a real deploy would refuse at the host check"
    exit 5
  fi

  echo
  echo "REHEARSED sha=$SHA kernel=$N_KERNEL console=$N_CONSOLE infra=$N_INFRA units=$N_UNITS manifest=$N_MANIFEST; nothing was written"
  exit 0
fi

echo "==> keeping the current tree, so a bad deploy can be undone"
# One command, under `set -e`, safe to re-run. Every prior snapshot is removed
# before the live target is tested, so an absent target leaves no snapshot that a
# later rollback could mistake for its own — it leaves a marker under
# ${ROLLBACK_DIR}-absent, which is what the rollback reads. A failed copy is a
# refusal here rather than an `echo kept` that masked it.
ssh_ "set -e; \
rm -rf $ROLLBACK_DIR ${ROLLBACK_DIR}-infra ${ROLLBACK_DIR}-console ${ROLLBACK_DIR}-units ${ROLLBACK_DIR}-provenance ${ROLLBACK_DIR}-absent; \
if [ -d $REMOTE_APP/packages/kernel/atlas_kernel ]; then cp -a $REMOTE_APP/packages/kernel/atlas_kernel $ROLLBACK_DIR; else echo 'absent: kernel'; mkdir -p ${ROLLBACK_DIR}-absent; : > ${ROLLBACK_DIR}-absent/kernel; fi; \
if [ -d $REMOTE_APP/infra ]; then cp -a $REMOTE_APP/infra ${ROLLBACK_DIR}-infra; else echo 'absent: infra'; mkdir -p ${ROLLBACK_DIR}-absent; : > ${ROLLBACK_DIR}-absent/infra; fi; \
if [ -d $CONSOLE_DIR ]; then cp -a $CONSOLE_DIR ${ROLLBACK_DIR}-console; else echo 'absent: console'; mkdir -p ${ROLLBACK_DIR}-absent; : > ${ROLLBACK_DIR}-absent/console; fi; \
for f in $UNIT_DIR/qevik-*.service $UNIT_DIR/qevik-*.timer; do [ -e \"\$f\" ] || continue; mkdir -p ${ROLLBACK_DIR}-units; cp -a \"\$f\" ${ROLLBACK_DIR}-units/; done; \
if [ ! -d ${ROLLBACK_DIR}-units ]; then echo 'absent: units'; mkdir -p ${ROLLBACK_DIR}-absent; : > ${ROLLBACK_DIR}-absent/units; fi; \
if [ -f $REMOTE_APP/DEPLOYED_SHA ]; then mkdir -p ${ROLLBACK_DIR}-provenance; cp $REMOTE_APP/DEPLOYED_SHA ${ROLLBACK_DIR}-provenance/; fi; \
if [ -f $REMOTE_APP/DEPLOYED_MANIFEST ]; then mkdir -p ${ROLLBACK_DIR}-provenance; cp $REMOTE_APP/DEPLOYED_MANIFEST ${ROLLBACK_DIR}-provenance/; fi" || {
  echo "REFUSED: could not keep the current tree; nothing has been transferred." >&2
  exit 1; }

# What the host said it held, read from the snapshot rather than from the live
# marker: the snapshot is the file the rollback puts back, so the sha reported
# here and the bytes restored later cannot disagree.
#
# One round trip, and its exit status is the only thing that decides whether the
# answer is trusted. Asking "is the snapshot there?" with `if ssh_ [ -f … ]`
# cannot tell absence from a link that went down: both are non-zero, and reading
# a dropped link as "nothing was recorded" is the expensive way to be wrong —
# the rollback would then overwrite a real previous marker with `sha=unknown`
# and *remove* the manifest it should have restored, having been told the
# snapshots it is looking at do not exist. So the host reports both facts in one
# line it always prints, and anything other than a clean exit and one of the
# four answers is a refusal, here, while the live tree is still untouched.
PREV_PROBE=""
PROBE_RC=0
PREV_PROBE="$(ssh_ "marker=0; manifest=0; \
if [ -f ${ROLLBACK_DIR}-provenance/DEPLOYED_SHA ]; then marker=1; fi; \
if [ -f ${ROLLBACK_DIR}-provenance/DEPLOYED_MANIFEST ]; then manifest=1; fi; \
printf 'saved marker=%s manifest=%s\\n' \"\$marker\" \"\$manifest\"; \
cat ${ROLLBACK_DIR}-provenance/DEPLOYED_SHA 2>/dev/null || true")" || PROBE_RC=$?
if [ "$PROBE_RC" != 0 ]; then
  echo "REFUSED: the host could not be asked what it had kept (rc=$PROBE_RC)." >&2
  echo "  The saved provenance is neither known present nor known absent, and a" >&2
  echo "  rollback that guessed absence would overwrite the previous marker with" >&2
  echo "  sha=unknown and remove the manifest instead of restoring it." >&2
  echo "  Nothing has been transferred." >&2
  exit 1
fi
# The flags are the first line the host prints; everything after it is the saved
# marker verbatim, which is why the flags cannot be searched for anywhere else.
PREV_FLAGS="$(printf '%s\n' "$PREV_PROBE" | head -1)"
PREV_MARKER="$(printf '%s\n' "$PREV_PROBE" | tail -n +2)"
case "$PREV_FLAGS" in
  "saved marker=0 manifest=0") PREV_MARKER_PRESENT=0; PREV_MANIFEST_PRESENT=0 ;;
  "saved marker=0 manifest=1") PREV_MARKER_PRESENT=0; PREV_MANIFEST_PRESENT=1 ;;
  "saved marker=1 manifest=0") PREV_MARKER_PRESENT=1; PREV_MANIFEST_PRESENT=0 ;;
  "saved marker=1 manifest=1") PREV_MARKER_PRESENT=1; PREV_MANIFEST_PRESENT=1 ;;
  *)
    echo "REFUSED: the host's answer about the saved provenance was not one of" >&2
    echo "  the four it may give: '$PREV_FLAGS'." >&2
    echo "  Nothing has been transferred." >&2
    exit 1 ;;
esac
PREV_STATE="$(printf '%s\n' "$PREV_MARKER" | sed -n 's/^state=//p' | head -1 || true)"
PREV_SHA="$(printf '%s\n' "$PREV_MARKER" | sed -n 's/^sha=//p' | head -1 || true)"
echo "    previous: sha=${PREV_SHA:-unknown} state=${PREV_STATE:-none} manifest=$PREV_MANIFEST_PRESENT"

# From here to the final line every failure runs `rollback_and_report`, and the
# marker says the disk holds a mixture — which, from the next command on, it
# does. A deploy killed mid-copy leaves this behind, and that is the truth.
if ! provenance_write installing "attempted_sha=$SHA" \
     "previous_sha=${PREV_SHA:-unknown}" "started_at=$(now_utc)"; then
  echo "FAILED: the host's provenance could not be set to installing; nothing"
  echo "        would say the disk was about to hold a mixture."
  rollback_and_report
fi

echo "==> copying the kernel"
rsync_ --delete "${KERNEL_RSYNC_EXCLUDE[@]}" \
  "$EXPORT/packages/kernel/atlas_kernel/" "$TARGET:$REMOTE_APP/packages/kernel/atlas_kernel/" || {
  echo "FAILED: the kernel could not be copied"; rollback_and_report; }

echo "==> copying the console"
rsync_ \
  "$EXPORT/apps/control/src/" "$TARGET:$CONSOLE_DIR/" || {
  echo "FAILED: the console could not be copied"; rollback_and_report; }

# The worker binary lives in infra/ and nothing has ever shipped it. A deploy
# reported success having sent none of it, and the host's own git checkout is
# 181 commits behind and does not track the file at all. Shipping it here rather
# than in a second script: one mechanism, one answer to "how does code reach
# production".
#
# No --delete: infra/ on the host may hold operational files this repository
# does not carry, and a deploy is not the place to discover that.
echo "==> copying infra (the mission worker lives here)"
rsync_ "${INFRA_RSYNC_EXCLUDE[@]}" \
  "$EXPORT/infra/" "$TARGET:$REMOTE_APP/infra/" || {
  echo "FAILED: infra could not be copied"; rollback_and_report; }

# Explicitly, and before anything restarts. `init_db` is idempotent -- every
# statement in it is IF NOT EXISTS -- and it is the only place this repository
# describes its schema, so running it here adds no second mechanism.
#
# It has to be a step of its own. `init_db` is reached only through
# `composition_root`, which this deploy does not restart, so a schema change
# would otherwise be applied whenever `qevik-api` next happened to restart. A
# worker that registers before its column exists fails to register at all.
# The environment reaches this step the way it reaches every service: through
# systemd's own EnvironmentFile parser, given a *path*. What stood here sourced
# the environment file in a shell — so a database password containing `$`, a
# backtick, a quote, a space or a semicolon either broke the deploy or, worse,
# was silently mangled into a different value. The fix belongs here and not in the password: a credential's entropy is
# not something a deploy script gets to constrain.
#
# Using systemd rather than a parser of our own is the point. The services read
# this file through `EnvironmentFile=`; a hand-written reader that quoted one
# case differently would give the schema step a different value than the
# services get, and that difference would surface as a schema applied against
# the wrong database rather than as an error.
#
# `--wait` propagates the exit status, `--pipe` returns the output, `--collect`
# removes the transient unit afterwards, and the value never touches a command
# line, a log or this script.
echo "==> applying the schema"
SCHEMA_PY='from atlas_kernel.db import init_db; init_db(); print("schema applied")'
ssh_ "systemd-run --wait --collect --pipe --quiet \
  --property=EnvironmentFile=$ENV_FILE \
  --property=User=$APP_USER --property=Group=$APP_USER \
  --property=WorkingDirectory=$REMOTE_APP \
  --setenv=PYTHONPATH=$REMOTE_APP/packages/kernel \
  $REMOTE_APP/.venv/bin/python -c '$SCHEMA_PY'" || {
  echo "FAILED: the schema could not be applied; nothing was restarted"
  rollback_and_report
}

echo "==> restarting $SERVICE"
ssh_ "chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel $CONSOLE_DIR 2>/dev/null; systemctl restart $SERVICE qevik-api.service" || {
  echo "FAILED: $SERVICE could not be restarted"; rollback_and_report; }

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
    rollback_and_report
  fi
  sleep 2
done

# Units this repository ships, installed before anything is restarted. A unit
# named in $WORKERS but absent from $UNIT_DIR makes `systemctl restart` return
# non-zero for the whole list -- and `ssh_` then retried it, which stopped and
# started the four healthy workers twelve times and tripped StartLimitBurst on
# all of them. Four dead workers from one missing file.
# Services *and* timers. A `.timer` matched nothing here until now, so the
# schedule on a host was whatever had been installed by hand, and no deploy could
# correct it. Shipping a timer file does not start anything — a timer is inert
# until `systemctl enable`, which no deploy does — so the repository becomes the
# source of truth for the schedule without a deploy ever activating one. The
# snapshot and the rollback cover the same glob, or a rollback would delete a
# timer it never saved.
echo "==> installing the unit files"
for unit in "$EXPORT"/infra/qevik-*.service "$EXPORT"/infra/qevik-*.timer; do
  [ -f "$unit" ] || continue
  rsync_ "$unit" "$TARGET:$UNIT_DIR/" >/dev/null || {
    echo "FAILED: $(basename "$unit") could not be installed"; rollback_and_report; }
done
ssh_ "systemctl daemon-reload" || {
  echo "FAILED: systemctl daemon-reload"; rollback_and_report; }

# Now every file this deploy places is on the host, so ask the host what it
# holds rather than believing rsync's exit code. A check that cannot run -- a
# missing file, a missing tool, a flag this build does not take -- is a refusal,
# never a pass. (`--strict` is deliberately not passed: the manifest is machine
# generated and well formed, and the flag is one more thing the host's uutils
# build would have to accept before a real deploy could succeed.)
echo "==> asking the host what it holds"
rsync_ "$MANIFEST" "$TARGET:$REMOTE_APP/DEPLOYED_MANIFEST.new" || {
  echo "FAILED: the manifest could not be transferred"; rollback_and_report; }
ssh_ "sha256sum --check --quiet $REMOTE_APP/DEPLOYED_MANIFEST.new" || {
  echo "FAILED: the bytes on the host do not match $SHA"
  rollback_and_report; }
# Promotion under `set -e`, so a failed `mv` is a failed deploy rather than
# something the trailing test forgives; the test is there to make a re-run of an
# already-promoted manifest succeed, not to excuse the `mv`.
ssh_ "set -e; if [ -f $REMOTE_APP/DEPLOYED_MANIFEST.new ]; then mv $REMOTE_APP/DEPLOYED_MANIFEST.new $REMOTE_APP/DEPLOYED_MANIFEST; fi; [ -f $REMOTE_APP/DEPLOYED_MANIFEST ]" || {
  echo "FAILED: the manifest could not be promoted"; rollback_and_report; }
# The digest recorded in the marker is of the file the host now holds, read back
# from the host, not of the local copy that was sent.
HOST_MANIFEST_SHA=""
HOST_MANIFEST_SHA="$(ssh_ "sha256sum $REMOTE_APP/DEPLOYED_MANIFEST" | cut -d' ' -f1)" \
  || HOST_MANIFEST_SHA=""
if [ -z "$HOST_MANIFEST_SHA" ]; then
  echo "FAILED: the promoted manifest could not be read back from the host"
  rollback_and_report
fi
echo "host verified: $MANIFEST_FILES files match $SHA"

# Only now: the bytes are on disk and the host measured them. An install nobody
# could record is not an install, so a failed marker write rolls back.
if ! provenance_write installed "sha=$SHA" "installed_at=$(now_utc)" \
     "manifest_sha256=$HOST_MANIFEST_SHA"; then
  echo "FAILED: the host holds $SHA but its provenance could not be recorded"
  rollback_and_report
fi

# What makes "deployed" checkable. The worker reports the sha256 of its own
# source as its registry `version`; if the restarted processes do not report the
# fingerprint of the file just sent, the code running is not the code shipped --
# which is exactly the failure that went unnoticed before, when the deploy
# succeeded and shipped nothing. $FINGERPRINT was taken from the export back in
# the preflight, so it fingerprints the commit rather than the tree, and this
# far in there is nothing left that could fail to produce it.
echo "==> restarting the mission workers (expecting fingerprint $FINGERPRINT)"
# Not through `ssh_`. Restarting is not something to retry blindly: a failing
# unit answers non-zero every time, and each attempt stops the healthy ones
# again. One attempt per unit, `reset-failed` first so a unit already at its
# start limit can come back, and the fingerprint check below is what decides
# whether the deploy worked.
ssh_ "chown qevik:qevik $REMOTE_APP/infra/mission_worker.py 2>/dev/null; true" || {
  echo "FAILED: the worker source could not be chowned"; rollback_and_report; }
for unit in $WORKERS; do
  ssh "${SSH_OPTS[@]}" $KEY_ARGS "$TARGET" \
    "systemctl reset-failed $unit 2>/dev/null; systemctl restart $unit" \
    || echo "    WARNING: $unit did not restart; the fingerprint check follows"
done

# Both reads are guarded, each setting its own variable empty on failure. A
# registry that answers non-zero is an answer rather than a retry, and an
# unguarded `$(ssh_ …)` under `set -e` would abort the script here -- after
# production has been fully written, silently, with the rollback below never
# reached and the host left in whatever state it was in. "Could not read the
# registry" and "the workers report the wrong thing" are different failures and
# say so.
REPORTED=""
COUNT=""
READ_OK=""
for attempt in $(seq 1 60); do
  READ_OK=yes
  REPORTED="$(ssh_ "sudo -u postgres psql -d qevik -Atc \"SELECT DISTINCT version FROM atlas_workers WHERE id LIKE '%:%' AND version <> '0.0.0'\"" 2>/dev/null | tr -d '\r')" || { REPORTED=""; READ_OK=""; }
  if [ -n "$READ_OK" ]; then
    COUNT="$(ssh_ "sudo -u postgres psql -d qevik -Atc \"SELECT count(*) FROM atlas_workers WHERE id LIKE '%:%' AND version = '$FINGERPRINT'\"" 2>/dev/null | tr -d '\r')" || { COUNT=""; READ_OK=""; }
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
    rollback_and_report
  fi
  sleep 3
done

echo "==> what the service now reports"
ssh_ "curl -s $HEALTH -o /dev/null -w 'health: %{http_code}\n'" || true
ssh_ "systemctl is-active $SERVICE"

echo
echo "provenance: $REMOTE_APP/DEPLOYED_SHA says state=installed sha=$SHA"
echo "            manifest_sha256=$HOST_MANIFEST_SHA over $MANIFEST_FILES files"
echo "deployed $SHA. The service answered; that is not the same as the change"
echo "being correct — verify the specific behaviour you deployed for."
