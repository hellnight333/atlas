#!/usr/bin/env bash
#
# Ship the Qevik backups off the server, and prove they came back.
#
#   qevik_offsite.sh                 # backup → forget/prune → check → restore-verify → status
#   qevik_offsite.sh --selftest      # round-trip a random file through the repository
#   qevik_offsite.sh --status        # print the last result and the failure marker, if any
#   qevik_offsite.sh --snapshots     # list what the repository holds
#   qevik_offsite.sh --restore-dump DIR   # restore the newest database dump into DIR
#
# qevik_backup.sh proves a dump restores; it says nothing about what happens when
# the disk that holds both the database and the dumps is gone. That is the gap
# F-6 in the migration risk register names, and it is closed here: every verified
# dump and every piece of non-database state goes to a Hetzner Storage Box through
# restic, encrypted before it leaves the host, kept under a retention policy, and
# read back after every run. "Copy succeeded" is never evidence; a restore is.
#
# Runs as root under qevik-offsite.service on its own timer, 45 minutes after
# qevik-backup.timer, so a failed dump still ships everything else and the
# previous verified dump. The only secret it needs is RESTIC_PASSWORD, delivered
# from /opt/qevik/backup.env (root 0600) exactly the way atlas.env reaches the
# other units. Nothing below prints it, and restic never writes it anywhere.
#
set -euo pipefail

BASE="${QEVIK_BASE:-/opt/qevik}"
DUMPS="${QEVIK_BACKUP_DIR:-${BASE}/backups}"
STATE_DIR="${QEVIK_OFFSITE_STATE:-/var/lib/qevik/backup}"
STATUS="${STATE_DIR}/status.json"
FAILED="${STATE_DIR}/FAILED"
KEEP_DAILY="${QEVIK_OFFSITE_KEEP_DAILY:-30}"
KEEP_WEEKLY="${QEVIK_OFFSITE_KEEP_WEEKLY:-8}"
KEEP_MONTHLY="${QEVIK_OFFSITE_KEEP_MONTHLY:-6}"
CHECK_SUBSET="${QEVIK_OFFSITE_CHECK_SUBSET:-5%}"
export RESTIC_CACHE_DIR="${RESTIC_CACHE_DIR:-/var/cache/restic}"
HOST_TAG="$(hostname -s)"
T0=$(date +%s)

# What leaves the host. Every path is optional: on a freshly built target most
# of them do not exist yet and appear as the phases land. Secrets never appear
# here — /opt/qevik/*.env are listed by NAME only, below.
STATE_PATHS=(
  "$DUMPS"
  /var/lib/qevik/control
  /var/lib/qevik/evidence
  /var/lib/qevik/jobs
  /var/lib/qevik/prospects
  /var/lib/qevik/outreach
  /var/lib/qevik/audits
  /var/lib/qevik/briefs
  /var/lib/qevik/workspaces
  /srv/sites
  /srv/qevik-public
  /etc/caddy
  /var/lib/caddy
)

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "FAILED: $*" >&2; exit 1; }

# --status needs neither root nor the repository: it is what a health probe calls.
if [ "${1:-}" = "--status" ]; then
  [ -f "$STATUS" ] && cat "$STATUS" || echo '{"result":"never-run"}'
  [ -f "$FAILED" ] && { echo "FAILED marker present:"; cat "$FAILED"; exit 2; }
  exit 0
fi

[ "$(id -u)" -eq 0 ] || die "must run as root (the Storage Box key lives in /root/.ssh)"
[ -n "${RESTIC_REPOSITORY:-}" ] || die "RESTIC_REPOSITORY is not set"
[ -n "${RESTIC_PASSWORD:-}" ] || die "RESTIC_PASSWORD is not set — run qevik-backup-set-password"
command -v restic >/dev/null || die "restic is not installed"
mkdir -p "$STATE_DIR" "$RESTIC_CACHE_DIR"
chmod 755 "$STATE_DIR"

write_status() {
  # One small JSON file, world-readable, no secrets: what /api/health and a human
  # on the phone need to answer "is the off-host copy fresh and proven".
  local result="$1" snapshot="${2:-}" restore="${3:-}" check="${4:-}" note="${5:-}"
  local tmp="${STATUS}.tmp"
  printf '{"unit":"qevik-offsite","host":"%s","last_run_utc":"%s","result":"%s","snapshot":"%s","restore_verified":"%s","check":"%s","repository":"%s","keep":"daily=%s,weekly=%s,monthly=%s","duration_s":%s,"note":"%s"}\n' \
    "$HOST_TAG" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$result" "$snapshot" "$restore" "$check" \
    "${RESTIC_REPOSITORY%%:*}:…" "$KEEP_DAILY" "$KEEP_WEEKLY" "$KEEP_MONTHLY" "$(( $(date +%s) - T0 ))" "$note" > "$tmp"
  chmod 644 "$tmp"; mv "$tmp" "$STATUS"
}

env_names() {
  # The names tell a rebuild which files to recreate; the values never leave the
  # host. Same rule as the migration plan's evidence: `cut -d= -f1`, nothing else.
  local out="${STATE_DIR}/env-names.txt" f
  : > "$out"
  for f in "$BASE"/*.env; do
    [ -f "$f" ] || continue
    printf '# %s (%s)\n' "$f" "$(stat -c '%U:%G %a' "$f")" >> "$out"
    grep -v '^\s*#' "$f" | grep '=' | cut -d= -f1 | sed 's/^/  /' >> "$out"
  done
  # Unit files are configuration, not secrets; they are what a rebuild replays.
  ls -1 /etc/systemd/system/qevik-* 2>/dev/null > "${STATE_DIR}/units.txt" || true
  chmod 644 "$out" "${STATE_DIR}/units.txt" 2>/dev/null || true
}

newest_dump() { ls -1t "$DUMPS"/qevik-*.dump 2>/dev/null | head -1 || true; }

restore_verify() {
  # Restore the newest dump from the repository — not the local file — into a
  # private directory and compare bytes. The local dump was already proven by
  # pg_restore; this proves the off-host copy is the same bytes.
  local dump; dump="$(newest_dump)"
  if [ -z "$dump" ]; then echo "skipped (no dump on this host yet)"; return 0; fi
  local tmp; tmp="$(mktemp -d)"
  restic restore latest --quiet --include "$dump" --target "$tmp" >/dev/null
  local a b
  a="$(sha256sum "$dump" | cut -d' ' -f1)"
  b="$(sha256sum "${tmp}${dump}" 2>/dev/null | cut -d' ' -f1 || true)"
  rm -rf "$tmp"
  [ -n "$b" ] && [ "$a" = "$b" ] && { echo "$(basename "$dump") sha256 match"; return 0; }
  echo "MISMATCH for $(basename "$dump")"; return 1
}

case "${1:-run}" in
  --snapshots)
    exec restic snapshots --compact ;;
  --restore-dump)
    [ -n "${2:-}" ] || die "--restore-dump needs a target directory"
    mkdir -p "$2"
    restic restore latest --include "${DUMPS}/qevik-*.dump" --target "$2" | tail -3
    log "dumps restored under $2${DUMPS} — newest: $(ls -1t "$2${DUMPS}"/qevik-*.dump | head -1)"
    log "next: qevik_backup.sh --verify-only <that file>, then pg_restore --no-owner -d qevik <that file>"
    exit 0 ;;
  --selftest)
    # A round trip with bytes we made up: back up a random file, restore it from
    # the repository, compare, remove every trace. This is the proof available on
    # a host that has no database yet, and a cheap proof on one that does.
    mkdir -p "${DUMPS}/selftest"
    f="${DUMPS}/selftest/roundtrip-$(date -u +%Y%m%dT%H%M%SZ).bin"
    head -c 4194304 /dev/urandom > "$f"; chmod 600 "$f"
    want="$(sha256sum "$f" | cut -d' ' -f1)"
    log "selftest: backing up $(basename "$f") (4 MiB random)"
    restic backup --quiet --tag selftest --host "$HOST_TAG" "$f"
    snap="$(restic snapshots --tag selftest --latest 1 --json | python3 -c 'import json,sys; s=json.load(sys.stdin); print(s[-1]["short_id"] if s else "")')"
    tmp="$(mktemp -d)"
    restic restore "$snap" --quiet --target "$tmp" >/dev/null
    got="$(sha256sum "${tmp}${f}" | cut -d' ' -f1)"
    rm -rf "$tmp" "$f"
    restic forget --quiet --prune "$snap" >/dev/null
    rmdir "${DUMPS}/selftest" 2>/dev/null || true
    [ "$want" = "$got" ] || die "selftest: restored bytes differ"
    log "selftest: PASS — snapshot ${snap} restored byte-identical, then forgotten and pruned"
    exit 0 ;;
  run) ;;
  *) die "unknown argument: $1" ;;
esac

# ---- run ------------------------------------------------------------------
env_names
PRESENT=()
for p in "${STATE_PATHS[@]}" "$STATE_DIR"; do [ -e "$p" ] && PRESENT+=("$p"); done
[ "${#PRESENT[@]}" -gt 0 ] || die "nothing to back up"
log "backup: ${#PRESENT[@]} path(s) → ${RESTIC_REPOSITORY%%:*} repository"

# Unverified dumps stay local for inspection; they are evidence, not backups.
# scratch/ and worktrees/ are per-mission clones and are regenerated, not kept.
if ! out="$(restic backup --host "$HOST_TAG" --tag daily \
      --exclude '*.UNVERIFIED' --exclude "${DUMPS}/selftest" \
      --exclude /var/lib/qevik/scratch --exclude /var/lib/qevik/worktrees \
      --exclude-caches --one-file-system --json "${PRESENT[@]}" 2>&1 | tail -1)"; then
  write_status failed "" "" "" "restic backup exited non-zero"
  die "restic backup: ${out}"
fi
SNAP="$(printf '%s' "$out" | python3 -c 'import json,sys
try:
    d=json.loads(sys.stdin.read()); print(d.get("snapshot_id","")[:8], d.get("files_new",0), d.get("files_changed",0), d.get("data_added",0))
except Exception: print("? ? ? ?")')"
read -r SNAP_ID FILES_NEW FILES_CHANGED DATA_ADDED <<<"$SNAP"
log "backup: snapshot ${SNAP_ID} — ${FILES_NEW} new, ${FILES_CHANGED} changed files, $((DATA_ADDED/1024/1024)) MiB added"

log "retention: keep daily=${KEEP_DAILY} weekly=${KEEP_WEEKLY} monthly=${KEEP_MONTHLY}"
restic forget --quiet --tag daily --host "$HOST_TAG" \
  --keep-daily "$KEEP_DAILY" --keep-weekly "$KEEP_WEEKLY" --keep-monthly "$KEEP_MONTHLY" --prune

# Structural check every run plus a sample of the actual data blobs: enough to
# catch a corrupt or truncated pack on a Storage Box without reading 100 % daily.
if restic check --quiet --read-data-subset="$CHECK_SUBSET" >/dev/null 2>&1; then
  CHECK="ok(${CHECK_SUBSET})"; log "check: repository consistent, ${CHECK_SUBSET} of data read back"
else
  write_status failed "$SNAP_ID" "" "FAILED" "restic check failed"
  die "restic check failed"
fi

if RV="$(restore_verify)"; then
  log "restore-verify: ${RV}"
else
  write_status failed "$SNAP_ID" "MISMATCH" "$CHECK" "restore-verify failed"
  die "restore-verify: ${RV}"
fi

write_status ok "$SNAP_ID" "$RV" "$CHECK" ""
rm -f "$FAILED"
log "OK in $(( $(date +%s) - T0 ))s — $(restic snapshots --tag daily --host "$HOST_TAG" --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))') daily snapshot(s) retained off-host"
