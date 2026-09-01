#!/usr/bin/env bash
# Put the control panel on the host that serves app.qevik.ai.
#
# Static files only. The console has no build step — that is the deployment
# decision it was written for: this script copies a directory and reloads a web
# server, and there is no toolchain between the repository and the browser that
# can be broken on the day the operator needs the console.
#
#   ./infra/deploy_console.sh [user@host]
#
# It refuses rather than half-deploying, and it verifies afterwards rather than
# reporting success because `scp` exited zero.
#
# The web server config it runs behind serves four hostnames, not one, and
# `qevik.ai` is the public marketing site out of `/srv/qevik-public`. That site
# and the config that resolves it are published by `infra/deploy_public.sh`,
# which this calls — one script owns both halves, because they were split across
# two and a correct fix sat unapplied for a day as a result.
set -euo pipefail

TARGET="${1:-root@2.28.62.83}"
HERE="$(cd "$(dirname "$0")" && pwd)"
LOCAL="$(cd "$(dirname "$0")/.." && pwd)/apps/control/src"
REMOTE="/srv/qevik-control"

[ -f "$LOCAL/index.html" ] || { echo "no console at $LOCAL"; exit 1; }

echo "==> checking access to $TARGET"
if ! ssh -o BatchMode=yes -o ConnectTimeout=10 -i "$HOME/.ssh/naml_hetzner" -o IdentitiesOnly=yes "$TARGET" true 2>/dev/null; then
  cat <<'MSG'
REFUSED: no SSH access to the host.

This is the exact human dependency, and nothing here can work around it:

  1. An SSH key or password for the host serving app.qevik.ai
     (qevik-core-01 / 2.28.62.83).

Everything else is ready. The console is built, the Caddyfile carries the
/api/* route the control plane needs, and this script deploys and verifies in
one step once it can reach the host.

Nothing was deployed. No success is being reported.
MSG
  exit 2
fi

echo "==> syncing the kernel"
rsync -az -e "ssh -i $HOME/.ssh/naml_hetzner -o IdentitiesOnly=yes" --delete   --exclude '__pycache__' --exclude '.pytest_cache' --exclude '*.pyc'   "$(cd "$(dirname "$0")/.." && pwd)/packages/kernel/atlas_kernel/"   "$TARGET:/opt/qevik/atlas/packages/kernel/atlas_kernel/"

echo "==> installing the control-plane service"
scp -i "$HOME/.ssh/naml_hetzner" -o IdentitiesOnly=yes -q "$(cd "$(dirname "$0")" && pwd)/qevik-control.service"   "$TARGET:/etc/systemd/system/qevik-control.service"
ssh -i "$HOME/.ssh/naml_hetzner" -o IdentitiesOnly=yes "$TARGET" "install -d -o qevik -g qevik /var/lib/qevik/control &&   systemctl daemon-reload && systemctl enable qevik-control && \
  systemctl restart qevik-control"
# `restart`, not `enable --now`. On an already-running unit `--now` is a no-op,
# so the freshly synced code stayed unloaded and the schema migration inside
# start-up never ran — the deployment reported success and changed nothing.
# Give it a moment, then insist it is actually up. A unit that failed to start
# and a unit that started are indistinguishable from `systemctl enable`.
sleep 3
ssh -i "$HOME/.ssh/naml_hetzner" -o IdentitiesOnly=yes "$TARGET" "systemctl is-active --quiet qevik-control" || {
  echo "the control plane did not start:"
  ssh "$TARGET" "journalctl -u qevik-control -n 30 --no-pager"
  exit 6
}
ssh -i "$HOME/.ssh/naml_hetzner" -o IdentitiesOnly=yes "$TARGET" "curl -sS --max-time 8 -o /dev/null -w '    local :8081 /health -> %{http_code}\n' http://127.0.0.1:8081/health"

echo "==> copying the console to $REMOTE"
ssh -i "$HOME/.ssh/naml_hetzner" -o IdentitiesOnly=yes "$TARGET" "mkdir -p $REMOTE.incoming"
scp -i "$HOME/.ssh/naml_hetzner" -o IdentitiesOnly=yes -q -r "$LOCAL"/* "$TARGET:$REMOTE.incoming/"
# Swap, rather than overwrite in place: a half-copied console is a broken
# console that is live, which is worse than the previous one still being live.
ssh -i "$HOME/.ssh/naml_hetzner" -o IdentitiesOnly=yes "$TARGET" "rm -rf $REMOTE.previous && \
  { [ -d $REMOTE ] && mv $REMOTE $REMOTE.previous || true; } && \
  mv $REMOTE.incoming $REMOTE"

# The public site and the Caddyfile, in one step, because they are one change.
#
# The `qevik.ai` block rewrites unknown URLs to `/404.html` and `/ar/404.html`
# inside `/srv/qevik-public`. Those are pages `apps/public/build.py` produces
# and nothing else does. Installing the config without them points
# `handle_errors` at files the host does not have, and every unknown URL answers
# with a bare file-server error instead of the page this repository designed.
#
# This script used to publish the site here and install the config twenty lines
# below, and that split is exactly how a correct fix went a day without reaching
# production: the development loop's deploy gate runs `infra/deploy_control.sh`,
# which called neither half. `deploy_public.sh` now does both — it ships the
# pages, replaces `/etc/caddy/Caddyfile`, validates, restarts Caddy, puts the
# previous config back if Caddy does not come up, and asserts at the origin that
# `/services/` serves its own page and an unknown URL answers 404.
#
# Through `bash` rather than as `$HERE/deploy_public.sh`: git carries one mode
# bit and plenty of ways of moving a tree drop it, and "permission denied" here
# would stop a deploy that has already restarted the control plane.
echo "==> publishing qevik.ai and the config that serves it"
bash "$HERE/deploy_public.sh" "$TARGET" || {
  echo "FAILED: qevik.ai was not published. Whether the web server was"
  echo "        restarted is printed above; that script puts the previous"
  echo "        config back if Caddy did not come up with the new one."
  echo "        The steps above did run: the kernel, the control-plane service"
  echo "        and the console are deployed."
  exit 8
}

echo "==> verifying"
code=$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' https://app.qevik.ai/ || echo 000)
type=$(curl -sS --max-time 20 -o /dev/null -w '%{content_type}' https://app.qevik.ai/api/health || echo none)
api=$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' https://app.qevik.ai/api/missions || echo 000)
sales=$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' https://app.qevik.ai/control/sales/summary || echo 000)
echo "    GET /                     -> $code"
echo "    GET /api/health           -> $type"
echo "    GET /api/missions         -> $api   (401 expected: JSON, never HTML)"
echo "    GET /control/sales/summary-> $sales (401 expected: sales still served)"
[ "$api" = "401" ] || { echo "FAILED: /api/missions answered $api, not 401"; exit 6; }
[ "$sales" = "401" ] || { echo "FAILED: the sales console lost its API ($sales)"; exit 7; }
if [ "$code" != "200" ]; then echo "FAILED: the console did not answer"; exit 4; fi
case "$type" in
  application/json*) echo "OK: the console is live and the control plane is reachable." ;;
  *) echo "FAILED: /api/* is still falling through to the static handler."; exit 5 ;;
esac

# qevik.ai is not re-checked here. `deploy_public.sh` above installed the config
# that serves it and asserted at the origin that it does; asserting the same
# three URLs a second time from this script is how the two copies drifted apart
# the first time.
