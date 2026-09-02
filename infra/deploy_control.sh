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
# could not put something back, 5 a rehearsal found the host not ready. Nothing
# is written to the host before the access check.
#
# After a deploy the host says what it holds rather than being assumed to hold
# it: $REMOTE_APP/DEPLOYED_MANIFEST is one sha256 per shipped file, checked by
# the host itself, and $REMOTE_APP/DEPLOYED_SHA records the sha, the time and
# the manifest digest. Only `state=installed` in that marker means "the host
# holds this commit"; the marker describes bytes on disk and never health.
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

# --- provenance, the manifest, and the rollback ------------------------------

# The marker is written atomically, so a deploy killed mid-write leaves a whole
# file rather than half a line. Nothing from $ENV_FILE or this shell's
# environment is ever written into it: it carries shas, times and target names.
write_marker() {  # each argument is one key=value line
  local body
  body="$(printf '%s\\n' "$@")"
  ssh_ "printf '%b' '$body' > '$REMOTE_APP/DEPLOYED_SHA.tmp' && mv '$REMOTE_APP/DEPLOYED_SHA.tmp' '$REMOTE_APP/DEPLOYED_SHA'"
}

# What the host is asked to measure itself against: one `<sha256>  <absolute
# host path>` line per regular file the deploy sends, which is the format
# `sha256sum --check` reads. rsync's exit code says a transfer ran, not that the
# right bytes arrived, and this is the difference.
manifest_lines() {  # export subtree, absolute host prefix ending in /
  local dir="$1" prefix="$2" rel
  [ -d "$dir" ] || return 0
  ( cd "$dir" && find . -type f -print ) | while IFS= read -r rel; do
    rel="${rel#./}"
    # The same things the transfers exclude; a file that is never sent must not
    # be listed, or every deploy would fail its own check.
    case "$rel" in *__pycache__/*|*.pyc|*.pytest_cache/*) continue ;; esac
    printf '%s  %s%s\n' "$(shasum -a 256 "$dir/$rel" | cut -d' ' -f1)" "$prefix" "$rel"
  done
}

# What a rollback put back, and what it could not. A rollback that cannot
# restore a target says so and exits 4; it is never reported as success.
RESTORED_TARGETS=""
NOT_RESTORED=""

mark_restored() {
  RESTORED_TARGETS="${RESTORED_TARGETS:+$RESTORED_TARGETS,}$1"
}

mark_not_restored() {
  local label="$1" out="" t
  case ",$NOT_RESTORED," in *",$label,"*) return 0 ;; esac
  NOT_RESTORED="${NOT_RESTORED:+$NOT_RESTORED,}$label"
  local IFS=,
  for t in $RESTORED_TARGETS; do
    if [ "$t" != "$label" ]; then out="${out:+$out,}$t"; fi
  done
  RESTORED_TARGETS="$out"
}

account() {  # exit status of a restore, target label
  if [ "$1" = 0 ]; then
    mark_restored "$2"
  elif [ "$1" = 3 ]; then
    echo "    not restored: $2 (it did not exist before this deploy)"
    mark_not_restored "$2"
  else
    echo "    restore failed: $2"
    mark_not_restored "$2"
  fi
}

# `rm -rf` of a live target runs only when the copy that would replace it is
# there. Exit 3 is "the target was absent before this deploy", which is not a
# failure to remove anything -- it is a target this rollback cannot restore.
restore_target() {  # label, rollback copy, live path
  local rc=0
  ssh_ "if [ -d '$2' ]; then set -e; rm -rf '$3'; cp -a '$2' '$3'; else exit 3; fi" || rc=$?
  account "$rc" "$1"
}

# The saved set replaces the installed set, so a unit this deploy added that the
# saved set did not contain is removed by the restore. That is deliberate: the
# host goes back to the units it had.
restore_units() {
  local rc=0
  ssh_ "if [ -d '${ROLLBACK_DIR}-units' ]; then
set -e
rm -f '$UNIT_DIR'/qevik-*.service
for f in '${ROLLBACK_DIR}-units'/qevik-*.service; do
  if [ -e \"\$f\" ]; then cp -a \"\$f\" '$UNIT_DIR/'; fi
done
systemctl daemon-reload
else
exit 3
fi" || rc=$?
  account "$rc" units
}

# Every failure after the rollback copies exist comes here. It restores, then
# *measures* what it restored, then writes the marker, then restarts -- in that
# order, because the marker describes bytes on disk and the bytes are settled
# once the restore has been measured. A script killed during the restarts
# therefore leaves a marker that is already true.
rollback_and_report() {
  # Nothing from here on may abort the script: a rollback that dies half way
  # would leave the host in a state no marker describes.
  set +e
  local prov="${ROLLBACK_DIR}-provenance" now restart_failed=0 unit
  echo "==> putting the previous tree back"
  ssh_ "rm -f '$REMOTE_APP/DEPLOYED_MANIFEST.new'" >/dev/null 2>&1

  restore_target kernel "$ROLLBACK_DIR" "$REMOTE_APP/packages/kernel/atlas_kernel"
  restore_target infra "${ROLLBACK_DIR}-infra" "$REMOTE_APP/infra"
  restore_target console "${ROLLBACK_DIR}-console" "$CONSOLE_DIR"
  restore_units

  # Measured, not assumed. The previous manifest is the only record of what the
  # host held, so the restored bytes are checked against it with the same check
  # a deploy uses; a check that fails marks the targets it covers not restored.
  if ssh_ "[ -f '$prov/DEPLOYED_MANIFEST' ]"; then
    if ssh_ "set -e
cp -a '$prov/DEPLOYED_MANIFEST' '$REMOTE_APP/DEPLOYED_MANIFEST'
sha256sum --check --quiet --strict '$REMOTE_APP/DEPLOYED_MANIFEST'"; then
      echo "    the restored bytes match the previous manifest"
    else
      echo "    the restored bytes do not match the previous manifest"
      mark_not_restored kernel
      mark_not_restored infra
      mark_not_restored console
      mark_not_restored units
    fi
  else
    # Nothing recorded what was here, so nothing can be measured -- and the
    # attempted sha's manifest must not outlive the bytes it described.
    ssh_ "rm -f '$REMOTE_APP/DEPLOYED_MANIFEST'" >/dev/null 2>&1
  fi

  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ -z "$NOT_RESTORED" ]; then
    if ssh_ "[ -f '$prov/DEPLOYED_SHA' ]"; then
      ssh_ "set -e
cp -a '$prov/DEPLOYED_SHA' '$REMOTE_APP/DEPLOYED_SHA.tmp'
mv '$REMOTE_APP/DEPLOYED_SHA.tmp' '$REMOTE_APP/DEPLOYED_SHA'" || {
        echo "    the previous marker could not be put back"
        mark_not_restored provenance; }
    else
      # A marker that could not be written is a restore that did not happen, the
      # same as the copy above failing. Without this the host keeps whatever
      # DEPLOYED_SHA it had -- `state=installing`, or nothing at all -- while
      # this function goes on to say `ROLLED BACK` and exit 1. `provenance` in
      # `not_restored=` is what turns that into exit 4.
      write_marker "sha=unknown" "state=rolled-back" "attempted_sha=$SHA" \
        "rolled_back_at=$now" \
        "note=no provenance was recorded before this deploy" \
        || { echo "    the marker could not be written"
             mark_not_restored provenance; }
    fi
  fi
  if [ -n "$NOT_RESTORED" ]; then
    write_marker "state=rollback-incomplete" "attempted_sha=$SHA" \
      "restored=$RESTORED_TARGETS" "not_restored=$NOT_RESTORED" \
      "rolled_back_at=$now" || echo "    the marker could not be written"
  fi

  # Exactly the restarts a deploy makes: control and api together through
  # `ssh_`, then the workers one at a time through bare ssh with `reset-failed`
  # first, for the reason the comment above the deploy's own loop gives.
  echo "==> restarting the services"
  ssh_ "chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel $CONSOLE_DIR 2>/dev/null; systemctl restart $SERVICE qevik-api.service" \
    || { echo "restart failed: $SERVICE qevik-api.service"; restart_failed=1; }
  for unit in $WORKERS; do
    ssh "${SSH_OPTS[@]}" -i "$KEY" "$TARGET" \
      "systemctl reset-failed $unit 2>/dev/null; systemctl restart $unit" \
      || { echo "restart failed: $unit"; restart_failed=1; }
  done

  echo
  if [ -n "$NOT_RESTORED" ] || [ "$restart_failed" = 1 ]; then
    echo "ROLLBACK INCOMPLETE: ${NOT_RESTORED:-the services did not restart}"
    echo "  A person has to look. $REMOTE_APP/DEPLOYED_SHA on the host says what"
    echo "  is on disk; a failed restart does not change what that says."
    exit 4
  fi
  echo "ROLLED BACK: $RESTORED_TARGETS"
  exit 1
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
WORK="$(mktemp -d)"
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

# The manifest, built from the export while the host is still untouched, so that
# what the host is measured against comes from the commit and not from anything
# read back off the host. The unit files are listed twice on purpose: they are
# shipped into infra/ and installed into $UNIT_DIR, and both copies have to be
# the commit's bytes.
MANIFEST="$WORK/DEPLOYED_MANIFEST"
{
  manifest_lines "$EXPORT/packages/kernel/atlas_kernel" "$REMOTE_APP/packages/kernel/atlas_kernel/"
  manifest_lines "$EXPORT/infra" "$REMOTE_APP/infra/"
  manifest_lines "$EXPORT/apps/control/src" "$CONSOLE_DIR/"
  for unit in "$EXPORT"/infra/qevik-*.service; do
    [ -f "$unit" ] || continue
    printf '%s  %s\n' "$(shasum -a 256 "$unit" | cut -d' ' -f1)" "$UNIT_DIR/$(basename "$unit")"
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
  echo "manifest: $MANIFEST_FILES files, sha256 $MANIFEST_SHA"

  # The whole deploy fails closed on this one command, so a rehearsal proves it
  # works on an input whose answer is known -- the sha256 of an empty file
  # against /dev/null -- rather than assuming the host's tool and flags. The
  # remote command answers instead of failing, so the rehearsal stays read-only.
  CHECK="$(ssh_ "printf 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  /dev/null\n' | sha256sum --check --quiet --strict - >/dev/null 2>&1 && echo works || echo broken" || echo broken)"
  case "$CHECK" in
    *works*) echo "host sha256sum --check: works" ;;
    *)
      echo "host sha256sum --check: DOES NOT WORK"
      echo
      echo "NOT READY: a real deploy would refuse at the host check"
      exit 5 ;;
  esac

  echo
  echo "REHEARSED sha=$SHA kernel=$N_KERNEL console=$N_CONSOLE infra=$N_INFRA units=$N_UNITS; nothing was written"
  exit 0
fi

# Every target this script writes is saved first, because a rollback can only
# put back what was kept. A copy that fails is a refusal rather than an
# `echo kept`: the old line hid a failed `cp` behind `2>/dev/null` and then said
# the tree had been kept. A target that is absent on the host is said to be
# absent -- that is a fact about the host, and the rollback treats it as one.
#
# The previous run's copy is removed *before* the target is tested, so the saved
# set is only ever this deploy's pre-state. Keeping it only on the `-e` branch
# left an earlier deploy's snapshot in place for a target that is absent now,
# and the rollback -- which asks nothing but "is there a copy?" -- would then
# restore months-old bytes into a path that held nothing, and report `ROLLED
# BACK`. Absence is recorded by the *absence of a copy*, which is exactly what
# `restore_target` reads as "it did not exist before this deploy": exit 3, the
# target named in `not_restored=`, and exit 4. The units and provenance copies
# below are already cleared unconditionally for the same reason.
echo "==> keeping the current tree, so a bad deploy can be undone"
ssh_ "set -e
keep() {
  rm -rf \"\$2\"
  if [ -e \"\$1\" ]; then cp -a \"\$1\" \"\$2\"; else echo \"absent: \$1\"; fi
}
keep '$REMOTE_APP/packages/kernel/atlas_kernel' '$ROLLBACK_DIR'
keep '$REMOTE_APP/infra' '${ROLLBACK_DIR}-infra'
keep '$CONSOLE_DIR' '${ROLLBACK_DIR}-console'
rm -rf '${ROLLBACK_DIR}-units' '${ROLLBACK_DIR}-provenance'
mkdir -p '${ROLLBACK_DIR}-units' '${ROLLBACK_DIR}-provenance'
units=0
for f in '$UNIT_DIR'/qevik-*.service; do
  if [ -e \"\$f\" ]; then cp -a \"\$f\" '${ROLLBACK_DIR}-units/'; units=\$((units + 1)); fi
done
if [ \"\$units\" = 0 ]; then echo 'absent: $UNIT_DIR/qevik-*.service'; fi
for f in '$REMOTE_APP/DEPLOYED_SHA' '$REMOTE_APP/DEPLOYED_MANIFEST'; do
  if [ -e \"\$f\" ]; then cp -a \"\$f\" '${ROLLBACK_DIR}-provenance/'; else echo \"absent: \$f\"; fi
done
rm -f '$REMOTE_APP/DEPLOYED_MANIFEST.new'" || {
  echo "REFUSED: could not keep the current tree, so a bad deploy could not be"
  echo "  undone. Nothing has been copied to the host."
  exit 1
}

# From here the disk is about to hold a mixture, and the marker says so. A
# deploy killed mid-copy leaves this behind, which is the truth: only
# `state=installed` ever means the host holds $SHA.
PREV_SHA="$(ssh_ "sed -n 's/^sha=//p' '$REMOTE_APP/DEPLOYED_SHA' 2>/dev/null | head -1" 2>/dev/null | tr -d '\r')" || PREV_SHA=""
[ -n "$PREV_SHA" ] || PREV_SHA=unknown
write_marker "state=installing" "attempted_sha=$SHA" "previous_sha=$PREV_SHA" \
  "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" || {
  echo "FAILED: the provenance marker could not be written, so this deploy could"
  echo "        not say what the host holds while it copies."
  rollback_and_report
}

echo "==> copying the kernel"
rsync_ --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
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
rsync_ \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
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
echo "==> applying the schema"
ssh_ "cd $REMOTE_APP && set -a && . $ENV_FILE && set +a && PYTHONPATH=$REMOTE_APP/packages/kernel $REMOTE_APP/.venv/bin/python -c 'from atlas_kernel.db import init_db; init_db(); print(\"schema applied\")'" || {
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
    ssh_ "journalctl -u $SERVICE -n 30 --no-pager" || true
    rollback_and_report
  fi
  sleep 2
done

# Units this repository ships, installed before anything is restarted. A unit
# named in $WORKERS but absent from $UNIT_DIR makes `systemctl restart` return
# non-zero for the whole list -- and `ssh_` then retried it, which stopped and
# started the four healthy workers twelve times and tripped StartLimitBurst on
# all of them. Four dead workers from one missing file.
echo "==> installing the unit files"
for unit in "$EXPORT"/infra/qevik-*.service; do
  [ -f "$unit" ] || continue
  rsync_ "$unit" "$TARGET:$UNIT_DIR/" >/dev/null || {
    echo "FAILED: $(basename "$unit") could not be installed"; rollback_and_report; }
done
ssh_ "systemctl daemon-reload" || {
  echo "FAILED: systemctl daemon-reload"; rollback_and_report; }

# The last copy has landed, so now the host is asked what it actually holds.
# A check that cannot run -- a missing tool, an unsupported flag, a file that
# never arrived -- is a refusal, never a pass, because the whole point is that
# "rsync exited zero" is not evidence.
echo "==> asking the host to measure what it now holds"
rsync_ "$MANIFEST" "$TARGET:$REMOTE_APP/DEPLOYED_MANIFEST.new" >/dev/null || {
  echo "FAILED: the manifest could not be sent to the host"; rollback_and_report; }
if ! ssh_ "sha256sum --check --quiet --strict '$REMOTE_APP/DEPLOYED_MANIFEST.new'"; then
  echo "FAILED: the bytes on the host do not match $SHA"
  rollback_and_report
fi
ssh_ "if [ -f '$REMOTE_APP/DEPLOYED_MANIFEST.new' ]; then mv '$REMOTE_APP/DEPLOYED_MANIFEST.new' '$REMOTE_APP/DEPLOYED_MANIFEST'; fi; [ -f '$REMOTE_APP/DEPLOYED_MANIFEST' ]" || {
  echo "FAILED: the verified manifest could not be kept on the host"; rollback_and_report; }
echo "host verified: $MANIFEST_FILES files match $SHA"

# The bytes are on disk and measured, which is exactly what the marker claims --
# nothing about health. A later health or fingerprint failure does not make this
# wrong; the rollback rewrites it when it puts the previous bytes back.
write_marker "sha=$SHA" "installed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "manifest_sha256=$MANIFEST_SHA" "state=installed" || {
  echo "FAILED: the provenance marker could not be written"; rollback_and_report; }

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
echo "deployed sha=$SHA"
echo "  The host measured its own bytes and the workers report the shipped"
echo "  fingerprint; that is not the same as the change being correct — verify"
echo "  the specific behaviour you deployed for."
