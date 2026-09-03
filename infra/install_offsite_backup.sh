#!/usr/bin/env bash
#
# Install (or re-install) the off-host backup on a Qevik host. Idempotent; run
# as root on the target after every deploy that touches infra/qevik_offsite.sh
# or the qevik-offsite / qevik-backup-failed units:
#
#   sudo /opt/qevik/atlas/infra/install_offsite_backup.sh
#
# What it does, and what it deliberately leaves to the owner:
#   1. apt-installs restic (client-side encryption, dedup, retention, check).
#   2. Generates /root/.ssh/storagebox_ed25519 if absent — the identity this host
#      presents to the Storage Box. The private half never leaves the host; the
#      public half is printed at the end for the owner to install (ssh-copy-id
#      typed by the owner, or pasted in the Hetzner console). Never done here:
#      that needs the sub-account password, which the agent must not hold.
#   3. Pins the Storage Box host key in /root/.ssh/known_hosts after checking
#      its ED25519 fingerprint against the one recorded in the migration
#      evidence (evidence/phase-2/firewall-and-console.txt) — a keyscan is only
#      trust-on-first-use; the recorded fingerprint makes it a verification.
#   4. Writes the `Host storagebox` block in /root/.ssh/config (port 23,
#      sub-account user, this key only) that restic's sftp backend uses.
#   5. Installs the script to /usr/local/sbin (root-owned, outside the deploy
#      tree so a mid-deploy or rolled-back /opt/qevik/atlas cannot break the
#      backup) and the units + timer into /etc/systemd/system, then enables
#      the timer.
#   6. Initialises the restic repository if — and only if — the owner has
#      already written /opt/qevik/backup.env with qevik-backup-set-password.
#
set -euo pipefail

SB_HOST="${STORAGEBOX_HOST:-u662608.your-storagebox.de}"
SB_PORT="${STORAGEBOX_PORT:-23}"
SB_USER="${STORAGEBOX_USER:-u662608-sub1}"
# ED25519 host key of u662608.your-storagebox.de:23 as observed from
# qevik-prod-01 on 2026-09-03 (evidence/phase-2/firewall-and-console.txt).
SB_ED25519_FPR="${STORAGEBOX_ED25519_FPR:-SHA256:XqONwb1S0zuj5A1CDxpOSuD2hnAArV1A3wKY7Z3sdgM}"
KEY=/root/.ssh/storagebox_ed25519
HERE="$(cd "$(dirname "$0")" && pwd)"
UNIT_DIR=/etc/systemd/system

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
say() { printf '\n== %s\n' "$*"; }

say "1/6 restic"
if ! command -v restic >/dev/null; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q restic >/dev/null
fi
restic version

say "2/6 host identity for the Storage Box"
install -d -m 700 /root/.ssh
if [ ! -f "$KEY" ]; then
  # No passphrase: the unit runs unattended and the file is root 0600 on a host
  # whose only other secret files are protected the same way.
  ssh-keygen -q -t ed25519 -N '' -C "qevik-prod-01 storagebox $(date -u +%Y-%m-%d)" -f "$KEY"
  echo "generated $KEY"
fi
chmod 600 "$KEY"; chmod 644 "$KEY.pub"
ls -l "$KEY" "$KEY.pub"

say "3/6 pin Storage Box host key (verify against recorded fingerprint)"
SCAN="$(ssh-keyscan -p "$SB_PORT" -t ed25519 "$SB_HOST" 2>/dev/null)"
[ -n "$SCAN" ] || { echo "keyscan of $SB_HOST:$SB_PORT returned nothing" >&2; exit 1; }
GOT="$(printf '%s\n' "$SCAN" | ssh-keygen -lf - | awk '{print $2}')"
if [ "$GOT" != "$SB_ED25519_FPR" ]; then
  echo "HOST KEY MISMATCH: scanned $GOT, expected $SB_ED25519_FPR — refusing to pin" >&2
  exit 1
fi
touch /root/.ssh/known_hosts; chmod 600 /root/.ssh/known_hosts
ssh-keygen -q -R "[$SB_HOST]:$SB_PORT" -f /root/.ssh/known_hosts >/dev/null 2>&1 || true
printf '%s\n' "$SCAN" >> /root/.ssh/known_hosts
echo "pinned ED25519 $GOT for [$SB_HOST]:$SB_PORT"

say "4/6 ssh config block"
CFG=/root/.ssh/config
touch "$CFG"; chmod 600 "$CFG"
if ! grep -q '^Host storagebox$' "$CFG"; then
  cat >> "$CFG" <<EOC

# Hetzner Storage Box for the off-host backup (restic sftp backend). Installed
# by infra/install_offsite_backup.sh; the key is host-local, see OFFSITE_BACKUP.md.
Host storagebox
    HostName $SB_HOST
    Port $SB_PORT
    User $SB_USER
    IdentityFile $KEY
    IdentitiesOnly yes
    StrictHostKeyChecking yes
    ServerAliveInterval 30
    ConnectTimeout 20
EOC
  echo "added Host storagebox to $CFG"
else
  echo "Host storagebox already present in $CFG"
fi

say "5/6 script, units, timer"
install -m 0755 -o root -g root "$HERE/qevik_offsite.sh" /usr/local/sbin/qevik_offsite.sh
install -m 0755 -o root -g root "$HERE/qevik-backup-set-password" /usr/local/sbin/qevik-backup-set-password
install -m 0644 -o root -g root "$HERE/qevik-offsite.service" "$HERE/qevik-offsite.timer" \
  "$HERE/qevik-backup-failed@.service" "$UNIT_DIR/"
install -d -m 755 /var/lib/qevik/backup /var/cache/restic /opt/qevik/backups
systemctl daemon-reload
systemctl enable --now qevik-offsite.timer >/dev/null
systemctl list-timers qevik-offsite.timer --no-pager | head -2

say "6/6 repository"
if [ -f /opt/qevik/backup.env ] && grep -q '^RESTIC_PASSWORD=.' /opt/qevik/backup.env; then
  # Read, don't source: the value may contain shell metacharacters. systemd's
  # EnvironmentFile= parser takes the raw line; this must see the same bytes.
  RESTIC_PASSWORD="$(sed -n 's/^RESTIC_PASSWORD=//p' /opt/qevik/backup.env | head -1)"
  export RESTIC_PASSWORD
  export RESTIC_REPOSITORY=sftp:storagebox:restic RESTIC_CACHE_DIR=/var/cache/restic
  if restic cat config >/dev/null 2>&1; then
    echo "repository exists: $(restic cat config | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"][:12])')"
  elif restic init 2>&1 | tail -1; then
    echo "repository initialised"
  else
    echo "restic init failed — is the public key installed on the sub-account yet?" >&2
  fi
  unset RESTIC_PASSWORD
else
  echo "no /opt/qevik/backup.env yet — repository not initialised."
  echo "owner: run  qevik-backup-set-password  on this host, then re-run this installer."
fi

cat <<EOM

== owner steps (once) ==
1. Install this host's public key on the Storage Box sub-account, from your Mac
   (you will be asked for the sub-account password; the agent never sees it):
     ssh -t qevik-prod-01 'ssh-copy-id -p $SB_PORT -s -i $KEY.pub $SB_USER@$SB_HOST'
   or paste this line in Hetzner console → Storage Box → sub-account → SSH keys:
     $(cat "$KEY.pub")
2. Set the repository password (keep a copy in your password manager):
     ssh -t qevik-prod-01 qevik-backup-set-password
3. Re-run this installer, then:  qevik_offsite.sh --selftest
EOM
