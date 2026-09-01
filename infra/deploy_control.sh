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
WORKERS="qevik-worker.service qevik-worker-research.service qevik-worker-delivery.service qevik-worker-publish.service qevik-worker-healthcheck.service"
HEALTH="http://127.0.0.1:8081/api/health"

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
# that may have half-run costs nothing.
ssh_() {
  local try
  for try in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if ssh "${SSH_OPTS[@]}" -i "$KEY" "$TARGET" "$@"; then return 0; fi
    [ "$try" = 12 ] && return 1
    echo "    (link dropped; retry $try)" >&2
    sleep $(( try < 6 ? try * 3 : 20 ))
  done
}
#: rsync resumes rather than restarting when a transfer is cut mid-file.
RSYNC_SSH="ssh ${SSH_OPTS[*]} -i $KEY"

# Same reason as `ssh_`, and safe for the same reason: rsync is idempotent by
# construction, and `--partial` means a retry continues the file it was cut in
# rather than starting the tree again.
rsync_() {
  local try
  for try in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if rsync -a --partial --timeout=120 -e "$RSYNC_SSH" "$@"; then return 0; fi
    [ "$try" = 12 ] && return 1
    echo "    (transfer cut; retry $try)" >&2
    sleep $(( try < 6 ? try * 3 : 20 ))
  done
}

[ -f "$ROOT/packages/kernel/atlas_kernel/qevik/app.py" ] || {
  echo "REFUSED: no kernel at $ROOT"; exit 1; }

# Refuse rather than half-deploy. `infra/` went unshipped for the whole life of
# this script and nobody noticed, because a deploy that sends less than it
# should still exits zero. This asks the opposite question: is anything that
# changed *not* covered by what we send?
#
# Tracked, modified, runtime files only -- tests and documents do not run in
# production. Committed work is covered too: the comparison is against what the
# host has, not against the last commit.
# `apps/public/` joined the list with the `deploy_public.sh` step near the end,
# which builds that tree and sends the output to `/srv/qevik-public`. It belongs
# here now and did not before, and the difference matters in both directions: an
# unlisted prefix that is shipped refuses every deploy the moment the builder is
# edited, and a listed prefix that is not shipped is this guard lying.
#
# That prefix is a whole directory, and it is only true because every file git
# can see under it is an input to that build: `build.py`, the `copy_ar` module
# it imports, and `assets/`, which it copies by name. It stopped being true
# once: `apps/public/index.html` was the hand-written homepage from before the
# builder existed, nothing read it, and while it sat there this guard called an
# edit to it shipped and the deploy reported success having changed nothing on
# qevik.ai. It is gone, and a test keeps the directory to build inputs.
SHIPPED_PREFIXES="packages/kernel/atlas_kernel/ infra/ apps/control/src/ apps/public/"
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
# This script copies the working tree. The development loop builds on a
# `devloop/<task>` branch and only merges to `main` after a clean review, so a
# deploy run while a task branch is checked out would put unreviewed work —
# possibly work a reviewer has already objected to — on the live host. The loop
# deploys from `_ship`, on `main`, after the full suite.
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

echo "==> checking access to $TARGET"
ssh_ true || { echo "REFUSED: no SSH access to $TARGET"; exit 1; }

echo "==> keeping the current tree, so a bad deploy can be undone"
STAMP="$(date -u +%Y%m%d%H%M%S)"
ssh_ "rm -rf /opt/qevik/rollback /opt/qevik/rollback-infra && cp -a $REMOTE_APP/packages/kernel/atlas_kernel /opt/qevik/rollback && cp -a $REMOTE_APP/infra /opt/qevik/rollback-infra 2>/dev/null; echo kept $STAMP"

echo "==> copying the kernel"
rsync_ --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$ROOT/packages/kernel/atlas_kernel/" "$TARGET:$REMOTE_APP/packages/kernel/atlas_kernel/"

echo "==> copying the console"
rsync_ \
  "$ROOT/apps/control/src/" "$TARGET:/srv/qevik-control/"

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
  "$ROOT/infra/" "$TARGET:$REMOTE_APP/infra/"

# Explicitly, and before anything restarts. `init_db` is idempotent -- every
# statement in it is IF NOT EXISTS -- and it is the only place this repository
# describes its schema, so running it here adds no second mechanism.
#
# It has to be a step of its own. `init_db` is reached only through
# `composition_root`, which this deploy does not restart, so a schema change
# would otherwise be applied whenever `qevik-api` next happened to restart. A
# worker that registers before its column exists fails to register at all.
echo "==> applying the schema"
ssh_ "cd $REMOTE_APP && set -a && . /opt/qevik/atlas.env && set +a && PYTHONPATH=$REMOTE_APP/packages/kernel $REMOTE_APP/.venv/bin/python -c 'from atlas_kernel.db import init_db; init_db(); print(\"schema applied\")'" || {
  echo "FAILED: the schema could not be applied; nothing was restarted"
  exit 1
}

echo "==> restarting $SERVICE"
ssh_ "chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel /srv/qevik-control 2>/dev/null; systemctl restart $SERVICE qevik-api.service"

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

# What makes "deployed" checkable. The worker reports the sha256 of its own
# source as its registry `version`; if the restarted processes do not report the
# fingerprint of the file just sent, the code running is not the code shipped --
# which is exactly the failure that went unnoticed before, when the deploy
# succeeded and shipped nothing.
FINGERPRINT="$(shasum -a 256 "$ROOT/infra/mission_worker.py" | cut -c1-12)"
echo "==> restarting the mission workers (expecting fingerprint $FINGERPRINT)"
# Units this repository ships, installed before anything is restarted. A unit
# named in $WORKERS but absent from /etc/systemd/system makes `systemctl
# restart` return non-zero for the whole list -- and `ssh_` then retried it,
# which stopped and started the four healthy workers twelve times and tripped
# StartLimitBurst on all of them. Four dead workers from one missing file.
for unit in "$ROOT"/infra/qevik-*.service; do
  [ -f "$unit" ] || continue
  rsync_ "$unit" "$TARGET:/etc/systemd/system/" >/dev/null
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

REPORTED=""
for attempt in $(seq 1 40); do
  REPORTED="$(ssh_ "sudo -u postgres psql -d qevik -Atc \"SELECT DISTINCT version FROM atlas_workers WHERE id LIKE '%:%' AND version <> '0.0.0'\"" 2>/dev/null | tr -d '\r')"
  COUNT="$(ssh_ "sudo -u postgres psql -d qevik -Atc \"SELECT count(*) FROM atlas_workers WHERE id LIKE '%:%' AND version = '$FINGERPRINT'\"" 2>/dev/null | tr -d '\r')"
  [ "$REPORTED" = "$FINGERPRINT" ] && [ "${COUNT:-0}" -ge 1 ] && {
    echo "    all $COUNT worker(s) report $FINGERPRINT after ${attempt}s"; break; }
  [ "$attempt" = 40 ] && {
    echo "FAILED: workers report '${REPORTED:-nothing}', expected '$FINGERPRINT'"
    echo "        the code running is not the code that was shipped."
    echo "==> putting the previous kernel and infra back"
    ssh_ "rm -rf $REMOTE_APP/packages/kernel/atlas_kernel && cp -a /opt/qevik/rollback $REMOTE_APP/packages/kernel/atlas_kernel && chown -R qevik:qevik $REMOTE_APP/packages/kernel/atlas_kernel"
    ssh_ "[ -d /opt/qevik/rollback-infra ] && rm -rf $REMOTE_APP/infra && cp -a /opt/qevik/rollback-infra $REMOTE_APP/infra"
    ssh_ "systemctl restart $SERVICE $WORKERS" || true
    exit 1
  }
  sleep 2
done

echo "==> what the service now reports"
ssh_ "curl -s $HEALTH -o /dev/null -w 'health: %{http_code}\n'" || true
ssh_ "systemctl is-active $SERVICE"

# --- and the public site, which this is the only deploy that runs ------------
#
# This is the script the development loop's `deployed` gate executes
# (`infra/devloop/gates.py`), and for a while it was the *only* deploy anything
# ran. So a fix to how qevik.ai is served — committed, reviewed, tested, and
# correct in this repository — never reached the host at all: it lived in
# `infra/deploy_console.sh`, which the loop does not call, and the task was
# marked done and production-verified while every URL on qevik.ai still served
# the homepage.
#
# Last, and deliberately. It restarts Caddy, so it runs only once the kernel,
# the console and the workers are up and verified; a web server restarted in
# front of a control plane that did not come back is two failures reported as
# one.
#
# Hard failure, not a warning. A deploy that exits zero having left the public
# site on last week's pages is the failure this whole path exists to stop, and
# the steps above have already been verified individually — what is lost by
# failing here is a green tick, not the control plane that was shipped above it.
#
# No `--restore-config` in the handler below, and that is not the same as not
# rolling back. Every way that script can fail *after* it has installed the
# config now puts the previous one back before it returns — including each of
# the origin assertions, which are the checks that can prove the new config
# wrong while Caddy is happily running on it.
#
# Restoring from here instead would mean deciding, from an exit code, whether a
# config was ever installed on this run. Most of those failures install nothing:
# a build that refused, a transfer that did not land, a config that did not
# validate. On those, `/etc/caddy/Caddyfile.previous` still holds whatever the
# *last* deploy left there, and putting it back over a live config would restart
# Caddy onto a stale config because a page failed to build. The script that took
# the backup is the one that knows; this is not a second place to keep that
# knowledge, for the same reason the pages and the config that names them are
# shipped by one script and not two.
#
# The API check below is the exception and stays one: that failure is invisible
# from inside `deploy_public.sh`, so the rollback for it has to be asked for.
echo "==> publishing qevik.ai and the config that serves it"
bash "$ROOT/infra/deploy_public.sh" "$TARGET" || {
  echo "FAILED: qevik.ai was not published, or the origin did not serve a page"
  echo "        per URL afterwards. If a config had been installed, that script"
  echo "        put the previous one back before it returned — see its output"
  echo "        above for whether it had to. The kernel, the console and the"
  echo "        workers are deployed and verified — that part of this run stands."
  exit 1
}

# Caddy has just been restarted with a config out of this repository, and it
# fronts the control plane as well as the marketing site. Ask it, at the origin
# rather than through Cloudflare, whether app.qevik.ai still answers as itself:
# a config that serves qevik.ai perfectly and 404s the API is not a good deploy.
echo "==> checking the control plane still answers through the restarted Caddy"
console_type() {
  ssh_ "curl -sS --max-time 15 --resolve app.qevik.ai:443:127.0.0.1 -o /dev/null -w '%{content_type}' https://app.qevik.ai/api/health" || echo none
}
CONSOLE_TYPE="$(console_type)"
echo "    GET app.qevik.ai/api/health -> $CONSOLE_TYPE"
case "$CONSOLE_TYPE" in
  application/json*) ;;
  *) echo "FAILED: app.qevik.ai/api/* no longer reaches the control plane"
     echo "        after the Caddy restart (content-type: $CONSOLE_TYPE)."
     # Put the config back rather than exiting on a known-broken one.
     #
     # Every other rollback in this file restores what it replaced; this branch
     # used to be the exception, and it is the branch that catches the one
     # failure nothing else can see. The config validated, Caddy started, and
     # every check `deploy_public.sh` makes passed — so nothing there rolled
     # anything back, and returning non-zero from here left production with a
     # config that serves the marketing site and no API. A red gate is not a
     # restored service.
     #
     # Through `deploy_public.sh --restore-config`, because that is the script
     # that took the backup: the path to it and the `reset-failed` a restart on
     # this host needs are written down once, over there.
     echo "==> putting the previous Caddy config back"
     if ! bash "$ROOT/infra/deploy_public.sh" --restore-config "$TARGET"; then
       echo "        AND the rollback failed. Caddy is serving a config nobody"
       echo "        chose; /etc/caddy/Caddyfile on the host needs a person."
       exit 1
     fi
     # Ask again, because "we rolled back" and "the API answers" are different
     # claims and only the second one is the one anybody cares about. It also
     # separates the two causes: if it still does not answer, the Caddyfile was
     # never what broke it and the next person should not go reading configs.
     RESTORED="$(console_type)"
     echo "    GET app.qevik.ai/api/health -> $RESTORED (on the previous config)"
     case "$RESTORED" in
       application/json*)
         echo "        the API answers again; the new Caddyfile was the cause." ;;
       *) echo "        the API still does not answer on the previous config, so"
          echo "        the Caddyfile is not what broke it." ;;
     esac
     exit 1 ;;
esac

echo
echo "deployed. The service answered; that is not the same as the change being"
echo "correct — verify the specific behaviour you deployed for."
