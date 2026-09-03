#!/usr/bin/env bash
# Put the control panel on the host that serves app.qevik.ai.
#
# Static files only. The console has no build step — that is the deployment
# decision it was written for: this script copies a directory and reloads a web
# server, and there is no toolchain between the repository and the browser that
# can be broken on the day the operator needs the console.
#
#   ./infra/deploy_console.sh --target <name>|user@host
#
# The console, the public site and the Caddyfile — not the kernel. Application
# code reaches a host through `deploy_control.sh` (ADR-0010) and nowhere else.
#
# It refuses rather than half-deploying, and it verifies afterwards rather than
# reporting success because `scp` exited zero.
#
# It also installs the Caddyfile, and that file serves four hostnames, not one.
# `qevik.ai` is the public marketing site out of `/srv/qevik-public` — a
# directory nothing in this repository used to write to. So this script
# publishes that site too, through `infra/deploy_public.sh`, and it does it
# *before* the config that names its files is installed.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

# Where this deploy is allowed to go, and with which key — one reviewed
# registry, no implicit production default (infra/deploy_targets.conf).
. "$HERE/deploy_target.sh"
TARGET_SPEC=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      shift
      [ $# -gt 0 ] || { echo "REFUSED: --target needs a name." >&2; exit 2; }
      TARGET_SPEC="$1" ;;
    -*) echo "REFUSED: unknown option '$1'." >&2; exit 2 ;;
    *) TARGET_SPEC="$1" ;;
  esac
  shift
done
qevik_resolve_target "$TARGET_SPEC"
TARGET="$QEVIK_TARGET_HOST"
SSH_ID=$(qevik_target_identity_args)
echo "target: $QEVIK_TARGET_NAME -> $TARGET (identity ${QEVIK_TARGET_KEY:-ssh_config})"
LOCAL="$(cd "$(dirname "$0")/.." && pwd)/apps/control/src"
REMOTE="/srv/qevik-control"
CADDYFILE="$HERE/qevik-production.Caddyfile"

[ -f "$LOCAL/index.html" ] || { echo "no console at $LOCAL"; exit 1; }

echo "==> checking access to $TARGET"
if ! ssh -o BatchMode=yes -o ConnectTimeout=10 $SSH_ID "$TARGET" true 2>/dev/null; then
  cat <<'MSG'
REFUSED: no SSH access to the host.

This is the exact human dependency, and nothing here can work around it:

  1. An SSH key or password for the host serving app.qevik.ai
     (the target named above).

Everything else is ready. The console is built, the Caddyfile carries the
/api/* route the control plane needs, and this script deploys and verifies in
one step once it can reach the host.

Nothing was deployed. No success is being reported.
MSG
  exit 2
fi

# The kernel is NOT copied here (D-S1). This script used to `rsync --delete` it
# into /opt/qevik/atlas/packages/kernel/atlas_kernel/ — the directory ADR-0010
# owns — without writing DEPLOYED_SHA or DEPLOYED_MANIFEST, so a console deploy
# could replace the running code while the host went on reporting a provenance
# it no longer had, and without any of deploy_control.sh's refusals (clean tree,
# ancestry, export verification). One way for code to reach a host, and this is
# not it: run `deploy_control.sh --target <name>` for the kernel.
echo "==> installing the control-plane service"
scp $SSH_ID -q "$(cd "$(dirname "$0")" && pwd)/qevik-control.service"   "$TARGET:/etc/systemd/system/qevik-control.service"
ssh $SSH_ID "$TARGET" "install -d -o qevik -g qevik /var/lib/qevik/control &&   systemctl daemon-reload && systemctl enable qevik-control && \
  systemctl restart qevik-control"
# `restart`, not `enable --now`. On an already-running unit `--now` is a no-op,
# so the freshly synced code stayed unloaded and the schema migration inside
# start-up never ran — the deployment reported success and changed nothing.
# Give it a moment, then insist it is actually up. A unit that failed to start
# and a unit that started are indistinguishable from `systemctl enable`.
sleep 3
ssh $SSH_ID "$TARGET" "systemctl is-active --quiet qevik-control" || {
  echo "the control plane did not start:"
  ssh $SSH_ID "$TARGET" "journalctl -u qevik-control -n 30 --no-pager"
  exit 6
}
ssh $SSH_ID "$TARGET" "curl -sS --max-time 8 -o /dev/null -w '    local :8081 /health -> %{http_code}\n' http://127.0.0.1:8081/health"

echo "==> copying the console to $REMOTE"
ssh $SSH_ID "$TARGET" "mkdir -p $REMOTE.incoming"
scp $SSH_ID -q -r "$LOCAL"/* "$TARGET:$REMOTE.incoming/"

# The floor ships inside the same staging directory, so it goes live in the one
# atomic swap below or not at all. It is not its own origin on purpose: it reads
# the session out of the console's sessionStorage and is allowed by the console's
# CSP, and a second origin would mean a second login for the same operator.
echo "==> copying the floor to $REMOTE/office"
ssh $SSH_ID "$TARGET" "mkdir -p $REMOTE.incoming/office"
scp $SSH_ID -q "$HERE/../apps/office/index.html" "$TARGET:$REMOTE.incoming/office/"

# Swap, rather than overwrite in place: a half-copied console is a broken
# console that is live, which is worse than the previous one still being live.
ssh $SSH_ID "$TARGET" "rm -rf $REMOTE.previous && \
  { [ -d $REMOTE ] && mv $REMOTE $REMOTE.previous || true; } && \
  mv $REMOTE.incoming $REMOTE"

# Before the Caddyfile, not after, and not separately.
#
# The `qevik.ai` block rewrites unknown URLs to `/404.html` and `/ar/404.html`
# inside `/srv/qevik-public`. Those are pages `apps/public/build.py` produces
# and nothing else does. Installing the config first would leave a window — or,
# if the site were never published at all, a permanent state — in which the
# server rewrites to a file that is not there and answers a bare file-server
# error instead of the page this repository designed.
#
# The reverse order is safe: the new files are inert under the old config, which
# rewrites everything to the homepage regardless. So the content lands first and
# the config that uses it lands second.
#
# Through `bash` rather than as `$HERE/deploy_public.sh`: git carries one mode
# bit and plenty of ways of moving a tree drop it, and "permission denied" here
# would stop a deploy that has already restarted the control plane.
echo "==> publishing the public site the Caddyfile serves"
bash "$HERE/deploy_public.sh" || {
  echo "FAILED: the public site was not published, so the Caddyfile that names"
  echo "        its 404 pages was not installed and Caddy was not restarted."
  echo "        The steps above did run: the kernel, the control-plane service"
  echo "        and the console are deployed. The web server is still serving"
  echo "        its previous configuration, which is the state before this run."
  exit 8
}

echo "==> installing the Caddyfile"
scp $SSH_ID -q "$CADDYFILE" "$TARGET:/etc/caddy/Caddyfile"
ssh $SSH_ID "$TARGET" "caddy validate --config /etc/caddy/Caddyfile" \
  || { echo "the Caddyfile did not validate; nothing was reloaded"; exit 3; }
# `restart`, not `reload`. Caddy's admin API on :2019 is disabled on this host,
# so `reload` validates the config and then fails to apply it with
# `connection refused` — reporting the file valid while changing nothing.
ssh $SSH_ID "$TARGET" "systemctl restart caddy"

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

# --- and the public site, which the same Caddyfile serves ---------------------
#
# Asserted rather than reported. Every page of qevik.ai was unreachable in
# production for weeks while the deploy exited zero, because nothing here had
# ever asked the server a question about the public site.
#
# At the origin, not through Cloudflare. This deploy changed what the origin
# serves; an edge cache can still be answering for what it served before, and a
# check that cannot tell those apart proves nothing about the deploy.
#
# `${2:-}` because `set -u` is on and most calls pass one argument; unquoted
# because the caller's extra curl flags have to reach the remote shell as
# separate words.
origin() {
  ssh $SSH_ID "$TARGET" \
    "curl -sS --max-time 15 --resolve qevik.ai:443:127.0.0.1 ${2:-} 'https://qevik.ai$1'" 2>/dev/null || true
}
# A path nothing has ever requested, so no cache anywhere holds the 200 the old
# config used to answer with.
miss="/deploy-check-$$-does-not-exist/"

services=$(origin /services/)
miss_code=$(origin "$miss" "-o /dev/null -w '%{http_code}'")
miss_body=$(origin "$miss")
ar_code=$(origin "/ar$miss" "-o /dev/null -w '%{http_code}'")
ar_body=$(origin "/ar$miss")

echo "    GET qevik.ai/services/    -> $(printf '%s' "$services" | grep -o '<title>[^<]*' | head -1)"
echo "    GET qevik.ai$miss -> $miss_code (404 expected)"
echo "    GET qevik.ai/ar$miss -> $ar_code (404 expected)"

# `origin` swallows a failed ssh so one dropped link does not read as a verdict
# on the site. Separated here, so "the origin said nothing" is not reported as
# "the origin served the wrong page".
[ -n "$services" ] || {
  echo "FAILED: the origin did not answer for qevik.ai/services/ at all."
  exit 13
}
# The measured defect: every URL served the homepage. Its own title is the
# cheapest proof that /services/ is now serving its own page.
printf '%s' "$services" | grep -q '<title>Services' || {
  echo "FAILED: qevik.ai/services/ is not serving its own page — the site is"
  echo "        still being served as a single-page application."
  exit 9
}
[ "$miss_code" = "404" ] || {
  echo "FAILED: an unknown URL answered $miss_code, not 404."
  exit 10
}
# Not just the status. A rewrite to a page that is not on the host answers with
# a bare file-server error, which is also a 404 — the exact failure that ships
# if the config is installed without the site.
printf '%s' "$miss_body" | grep -q 'That page is not here' || {
  echo "FAILED: the 404 status is right but the page is not the one this"
  echo "        repository builds — /404.html is missing from the document root."
  exit 11
}
# The Arabic site is a second site, not a translation layer, and being dropped
# into an English error page is where an Arabic visitor concludes otherwise.
# Spelled as an `if` rather than `A && B || C`: that idiom runs C when B fails
# too, which is wanted here and is exactly why it gets misread later.
if [ "$ar_code" != "404" ] || ! printf '%s' "$ar_body" | grep -q 'dir="rtl"'; then
  echo "FAILED: a wrong URL under /ar/ is not answered in Arabic ($ar_code)."
  exit 12
fi
echo "OK: qevik.ai serves a page per URL, and an unknown URL gets the 404 page."
