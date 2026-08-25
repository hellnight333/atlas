#!/usr/bin/env bash
# Put the kernel and the console on the host that serves app.qevik.ai.
#
#   ./infra/deploy_control.sh [user@host]
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
set -euo pipefail

TARGET="${1:-root@2.28.62.83}"
KEY="$HOME/.ssh/naml_hetzner"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_APP="/opt/qevik/atlas"
SERVICE="qevik-control.service"
HEALTH="http://127.0.0.1:8081/api/health"

ssh_() { ssh -o BatchMode=yes -o ConnectTimeout=15 -i "$KEY" "$TARGET" "$@"; }

[ -f "$ROOT/packages/kernel/atlas_kernel/qevik/app.py" ] || {
  echo "REFUSED: no kernel at $ROOT"; exit 1; }

echo "==> checking access to $TARGET"
ssh_ true || { echo "REFUSED: no SSH access to $TARGET"; exit 1; }

echo "==> keeping the current tree, so a bad deploy can be undone"
STAMP="$(date -u +%Y%m%d%H%M%S)"
ssh_ "rm -rf /opt/qevik/rollback && cp -a $REMOTE_APP/packages/kernel/atlas_kernel /opt/qevik/rollback && echo kept $STAMP"

echo "==> copying the kernel"
rsync -a --delete -e "ssh -o BatchMode=yes -i $KEY" \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$ROOT/packages/kernel/atlas_kernel/" "$TARGET:$REMOTE_APP/packages/kernel/atlas_kernel/"

echo "==> copying the console"
rsync -a -e "ssh -o BatchMode=yes -i $KEY" \
  "$ROOT/apps/control/src/" "$TARGET:/srv/qevik-control/"

echo "==> restarting $SERVICE"
ssh_ "chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel /srv/qevik-control 2>/dev/null; systemctl restart $SERVICE"

echo "==> waiting for it to answer"
# Polls rather than sleeping a fixed number: a fixed sleep is either too short
# on a slow boot or wasted on a fast one, and the failure mode of too-short is
# a deploy that reports failure on a service that was about to be fine.
for attempt in $(seq 1 30); do
  CODE="$(ssh_ "curl -s -o /dev/null -w '%{http_code}' $HEALTH" || echo 000)"
  # 401 is a *pass*: the service is up and refusing an unauthenticated caller,
  # which is what it should do. Treating it as failure would roll back a
  # perfectly good deploy.
  case "$CODE" in
    200|401|403) echo "    up after ${attempt}s (HTTP $CODE)"; break ;;
  esac
  [ "$attempt" = 30 ] && {
    echo "FAILED: $SERVICE did not answer after 30s (last HTTP $CODE)"
    echo "==> putting the previous kernel back"
    ssh_ "rm -rf $REMOTE_APP/packages/kernel/atlas_kernel && cp -a /opt/qevik/rollback $REMOTE_APP/packages/kernel/atlas_kernel && chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel && systemctl restart $SERVICE"
    ssh_ "journalctl -u $SERVICE -n 30 --no-pager" || true
    exit 1
  }
  sleep 1
done

echo "==> what the service now reports"
ssh_ "curl -s $HEALTH -o /dev/null -w 'health: %{http_code}\n'" || true
ssh_ "systemctl is-active $SERVICE"

echo
echo "deployed. The service answered; that is not the same as the change being"
echo "correct — verify the specific behaviour you deployed for."
