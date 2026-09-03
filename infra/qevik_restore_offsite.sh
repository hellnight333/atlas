#!/usr/bin/env bash
#
# Bring Qevik's data back from the Storage Box onto a machine that has nothing.
#
#   qevik_restore_offsite.sh [--snapshot ID] [--target /]
#
# The scenario this is written for: the production server, its disk and its
# Hetzner image backups are gone. You have a fresh Ubuntu host, the two things
# only the owner holds — the Storage Box login and the restic repository
# password — and this script (it is in git; `curl` it from GitHub if the repo
# is not on the box yet). Everything else is either in the repository or
# regenerable from git + apt.
#
# Two secrets are asked for interactively and never written anywhere by this
# script: the sub-account password (only if no SSH key is installed yet) and
# RESTIC_PASSWORD. Read OFFSITE_BACKUP.md §"Restore after total loss" first.
#
set -euo pipefail
SB_HOST="${STORAGEBOX_HOST:-u662608.your-storagebox.de}"
SB_PORT="${STORAGEBOX_PORT:-23}"
SB_USER="${STORAGEBOX_USER:-u662608-sub1}"
SNAP=latest; TARGET=/
while [ $# -gt 0 ]; do case "$1" in
  --snapshot) SNAP="$2"; shift 2 ;;
  --target) TARGET="$2"; shift 2 ;;
  *) echo "usage: $0 [--snapshot ID] [--target DIR]" >&2; exit 1 ;;
esac; done
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
command -v restic >/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -y -q restic >/dev/null

export RESTIC_REPOSITORY="sftp:${SB_USER}@${SB_HOST}:restic"
export RESTIC_CACHE_DIR=/var/cache/restic
# restic's sftp backend needs the port passed explicitly when no ssh config
# alias exists on a fresh host.
R() { restic -o "sftp.args=-p ${SB_PORT}" "$@"; }
if [ -z "${RESTIC_PASSWORD:-}" ]; then
  read -r -s -p "restic repository password: " RESTIC_PASSWORD; echo; export RESTIC_PASSWORD
fi

echo "== repository"
R snapshots --compact
echo "== restoring snapshot ${SNAP} under ${TARGET}"
R restore "$SNAP" --target "$TARGET" --verify
echo
echo "== restored (paths that exist now)"
for p in /opt/qevik/backups /var/lib/qevik /srv/sites /srv/qevik-public /etc/caddy /var/lib/caddy; do
  [ -e "${TARGET%/}$p" ] && du -sh "${TARGET%/}$p" || true
done
NEWEST="$(ls -1t "${TARGET%/}"/opt/qevik/backups/qevik-*.dump 2>/dev/null | head -1 || true)"
cat <<EOM

== next steps (see OFFSITE_BACKUP.md)
1. Recreate the secret files listed by name in ${TARGET%/}/var/lib/qevik/backup/env-names.txt
   (values from your password manager; they were never backed up).
2. Deploy the application tree: infra/deploy_control.sh (git + venv + Playwright are regenerable).
3. Database: install postgresql, create role + db, then
     ${NEWEST:+pg_restore --no-owner -d qevik $NEWEST}${NEWEST:-"(no dump found in this snapshot)"}
   and prove it first with:  infra/qevik_backup.sh --verify-only <dump>
4. Re-run infra/install_offsite_backup.sh so the new host backs itself up again.
EOM
