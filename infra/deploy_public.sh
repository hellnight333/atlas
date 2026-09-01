#!/usr/bin/env bash
# Publish qevik.ai: the pages, and the config that decides how they resolve.
#
#   bash infra/deploy_public.sh [user@host]  build, ship, install, verify
#   bash infra/deploy_public.sh --check DIR  verify a built directory against the
#                                            Caddyfile and exit; touches no host
#
# This script exists because the web server config and the files it serves were
# deployed by two different mechanisms, and only one of them was in this
# repository. `infra/qevik-production.Caddyfile` names `/404.html` and
# `/ar/404.html` inside `/srv/qevik-public`; nothing here had ever put a file in
# that directory. Installing the config alone would have answered every unknown
# URL with a bare file-server error — the config would be correct, the site
# would not be, and the deploy would have exited zero.
#
# So the two travel together, in one script, in one run: the pages land, then
# `/etc/caddy/Caddyfile` is replaced with the config that serves them, then this
# asks the origin whether `/services/` serves its own page and whether an
# unknown URL answers 404 — and exits non-zero if it does not.
#
# They were in *two* scripts for one day, and that day is the reason they are in
# one now. The content half lived here and the config half lived in
# `infra/deploy_console.sh`; the development loop's deploy gate runs
# `infra/deploy_control.sh`, which called neither. The fix was committed,
# reviewed, marked done and production-verified while every URL on qevik.ai
# still served the homepage. A fix that no deploy applies is not a fix, and the
# way to stop that recurring is to leave nothing for a second script to forget.
#
# The document root and the error-page paths are **read out of the Caddyfile**
# rather than written down a second time. A rewrite target added there without a
# page behind it fails here, on the operator's machine, instead of on qevik.ai.
#
# Note: `apps/public/assets/` is covered by the blanket `assets/` rule in
# .gitignore, so the artwork is not in the repository and this must be run from
# a working tree that has it. The build refuses by name for anything missing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
#: Overridable so the tests can point the same checks at a fixture config.
CADDYFILE="${QEVIK_CADDYFILE:-$ROOT/infra/qevik-production.Caddyfile}"
KEY="$HOME/.ssh/naml_hetzner"

# --- what the web server expects to find, asked of the config that expects it

# Read by brace depth. The site blocks nest — `handle_errors` inside the site,
# `handle` inside that — so a line-based match stops at the first closing brace
# and silently returns a fragment, which would drop the `rewrite` lines that are
# the whole point of reading this file.
site_block() {
  awk -v name="qevik.ai" '
    !inblock && $0 == name " {" { inblock = 1 }
    inblock {
      print
      # Bracket expressions, not `\{`. A brace is an interval operator in POSIX
      # ERE, and gawk warns on `\{` as an unknown escape — a warning on stderr
      # from a script whose whole job is to refuse loudly is noise in exactly
      # the place it must not be.
      depth += gsub(/[{]/, "{")
      depth -= gsub(/[}]/, "}")
      if (depth == 0) exit
    }
  ' "$CADDYFILE"
}

BLOCK="$(site_block)"
DOCROOT="$(printf '%s\n' "$BLOCK" | awk '$1 == "root" && $2 == "*" { print $3; exit }')"
#: Every path `handle_errors` rewrites to. These are files the server names, so
#: they must exist at exactly that path — a directory called `404.html` would
#: 404 the 404.
REWRITES="$(printf '%s\n' "$BLOCK" | awk '$1 == "rewrite" && $2 == "*" { print $3 }')"

[ -n "$DOCROOT" ] || {
  echo "REFUSED: no 'root *' in the qevik.ai block of $CADDYFILE." >&2
  echo "  Nothing here knows where the site is served from, so nothing is shipped." >&2
  exit 1
}

# --- the check both modes run

# A build that does not satisfy the config must never reach the host. Run before
# the transfer, and again on the host after it, because "the files were correct
# here" and "the files are correct there" are different claims.
check_build() {
  local dist="$1" missing=""
  [ -d "$dist" ] || { echo "REFUSED: no such directory: $dist" >&2; exit 1; }

  echo "    document root (from $(basename "$CADDYFILE")): $DOCROOT"
  for required in index.html sitemap.xml robots.txt; do
    [ -f "$dist/$required" ] || missing="$missing /$required"
  done
  for target in $REWRITES; do
    echo "    the config rewrites to: $target"
    [ -f "$dist/${target#/}" ] || missing="$missing $target"
  done

  if [ -n "$missing" ]; then
    echo >&2
    echo "REFUSED: the Caddyfile names files this build does not contain:" >&2
    for path in $missing; do echo "    $path" >&2; done
    echo >&2
    echo "  Shipping this would install a config that rewrites to a page that is" >&2
    echo "  not there, and every unknown URL would answer with a bare server" >&2
    echo "  error. Build them in apps/public/build.py, or take the rewrite out." >&2
    echo "  Nothing was deployed." >&2
    exit 1
  fi
  echo "    every path the config names is present"
}

if [ "${1:-}" = "--check" ]; then
  [ -n "${2:-}" ] || { echo "usage: $0 --check <built-directory>" >&2; exit 64; }
  check_build "$2"
  exit 0
fi

TARGET="${1:-root@2.28.62.83}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=20 -o ConnectionAttempts=4 \
          -o IdentitiesOnly=yes -i "$KEY")

# Connections to this host drop intermittently — roughly one attempt in five,
# after the TCP connect, during the banner exchange, so `ConnectionAttempts`
# does not cover it. `deploy_control.sh` learned this the same way and has the
# longer note. It matters more here now that this runs unattended inside the
# development loop's deploy gate: an unretried drop on any one of a dozen round
# trips would report the public site broken when the link was.
#
# Every command sent through it is idempotent by construction — copy, chmod,
# curl — and the one that is not, the directory swap, is written so that a
# second run of it is a no-op. Three calls deliberately stay on plain `ssh`:
# the transfer check and `caddy validate`, whose non-zero is a verdict rather
# than a dropped link, and the Caddy restart, which must not be retried.
# Three attempts, not a dozen: this runs inside a gate with a wall-clock budget,
# and every call that will never succeed — a stopped Caddy answering the curls
# below — pays the retries in full before the real failure is reported.
ssh_() {
  local try
  for try in 1 2 3; do
    if ssh "${SSH_OPTS[@]}" "$TARGET" "$@"; then return 0; fi
    [ "$try" = 3 ] && return 1
    echo "    (link dropped; retry $try)" >&2
    sleep $(( try * 3 ))
  done
}

# --- build

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
DIST="$WORK/dist"

echo "==> building the public site"
# stdout only. The builder's refusals — a missing asset, a page claiming
# something Qevik does not do — go to stderr and must stay visible, because the
# whole value of a build that refuses is the line naming what it refused over.
python3 "$ROOT/apps/public/build.py" --out "$DIST" >/dev/null || {
  echo "the build refused; nothing was deployed" >&2
  exit 1
}

echo "==> checking the build against $CADDYFILE"
check_build "$DIST"

# --- ship

echo "==> checking access to $TARGET"
ssh_ true 2>/dev/null || {
  echo "REFUSED: no SSH access to $TARGET. Nothing was deployed." >&2
  exit 2
}

echo "==> copying the site to $DOCROOT"
ssh_ "rm -rf '$DOCROOT.incoming' && mkdir -p '$DOCROOT.incoming'"
rsync -az --partial -e "ssh ${SSH_OPTS[*]}" "$DIST/" "$TARGET:$DOCROOT.incoming/"
# Caddy does not run as the user this copies as. A file it cannot read is a 403,
# which looks like an application fault and is a permission bit.
ssh_ "chmod -R a+rX '$DOCROOT.incoming'"

# Verify before swapping. A half-copied site that is live is worse than the
# previous one still being live, and this is the last moment it is cheap to
# stop.
REMOTE_REQUIRED="index.html sitemap.xml robots.txt"
for target in $REWRITES; do REMOTE_REQUIRED="$REMOTE_REQUIRED ${target#/}"; done
# Not through `ssh_`: a non-zero here is the host's verdict on the transfer, not
# a dropped link, and retrying it five times would report "link dropped" about a
# file that is genuinely absent.
ssh "${SSH_OPTS[@]}" "$TARGET" \
  "cd '$DOCROOT.incoming' && for f in $REMOTE_REQUIRED; do [ -f \"\$f\" ] || { echo \"missing on the host: /\$f\"; exit 1; }; done" || {
  echo "REFUSED: the transfer did not land intact; the live site was not touched." >&2
  exit 3
}

# Say what the swap drops before it drops it.
#
# This document root has never had a writer in this repository, so it may hold
# something no builder here produces — a search-engine verification file, an
# ads.txt, a hand-placed redirect. Replacing the tree wholesale would remove it
# silently. Top level only: `assets/` is content-hashed, so every filename in it
# changes on every build and listing that would bury the one line that matters.
#
# Reported, not refused, and `|| true`: the previous tree is kept at
# `$DOCROOT.previous`, so nothing here is unrecoverable, and a deploy is not the
# place to start guessing which host-only file was deliberate.
echo "==> what the live site has that this build does not"
ssh "${SSH_OPTS[@]}" "$TARGET" "
  [ -d $DOCROOT ] || exit 0
  cd $DOCROOT || exit 0
  for f in * .well-known; do
    [ -e \"\$f\" ] || continue
    [ -e $DOCROOT.incoming/\"\$f\" ] || echo \"    only on the live site: /\$f\"
  done
" || true

# Swap, rather than overwrite in place. Same reason the console deploy does.
#
# Guarded on `.incoming` still existing so that running it twice is a no-op —
# `ssh_` retries a dropped link, and the naive form, retried after the swap had
# already happened, would move the *new* tree to `.previous` and then fail with
# nothing at the document root at all.
ssh_ "if [ -d '$DOCROOT.incoming' ]; then \
    rm -rf '$DOCROOT.previous'; \
    [ -d '$DOCROOT' ] && mv '$DOCROOT' '$DOCROOT.previous'; \
    mv '$DOCROOT.incoming' '$DOCROOT'; \
  fi"

# --- the config that decides how those files resolve -------------------------
#
# After the pages, never before. The new files are inert under the old config,
# which rewrote everything to the homepage regardless, so content-first is free;
# the reverse order leaves a window in which `handle_errors` rewrites to a page
# the host does not have and every unknown URL answers with a bare file-server
# error.
#
# Replaced wholesale from the file in this repository rather than edited in
# place. `/etc/caddy/Caddyfile` is an operational file and hand-editing it is
# what took this server down once already; a whole file that `caddy validate`
# has accepted has no half-applied state. The one it replaces is kept beside it.
echo "==> keeping the config now in place, so a bad one can be undone"
ssh_ "[ -f /etc/caddy/Caddyfile ] && cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.previous || true"

restore_config() {
  echo "==> putting the previous config back and restarting" >&2
  # `reset-failed` first. This runs when Caddy has just refused to start, so its
  # start counter is already ticking; without this a retried rollback can trip
  # StartLimitBurst and leave the unit dead with a config that would have
  # worked. Four workers were lost to exactly that once.
  ssh_ "if [ -f /etc/caddy/Caddyfile.previous ]; then \
      cp -a /etc/caddy/Caddyfile.previous /etc/caddy/Caddyfile; \
      systemctl reset-failed caddy 2>/dev/null; \
      systemctl restart caddy; \
    else echo 'no previous config to restore' >&2; fi" >&2 || true
}

echo "==> installing $(basename "$CADDYFILE") as /etc/caddy/Caddyfile"
scp "${SSH_OPTS[@]}" -q "$CADDYFILE" "$TARGET:/etc/caddy/Caddyfile" || {
  echo "REFUSED: the Caddyfile could not be copied to the host; it is still" >&2
  echo "  serving its previous configuration. The pages above did land." >&2
  exit 6
}

# Validate on the host, with the host's binary. A config that parses here and
# not there — an `expression` matcher an older Caddy rejects, say — takes down
# all four hostnames, not just this one.
ssh "${SSH_OPTS[@]}" "$TARGET" "caddy validate --config /etc/caddy/Caddyfile" || {
  echo "REFUSED: the Caddyfile did not validate on the host; nothing was restarted." >&2
  restore_config
  exit 4
}

# `restart`, not `reload`. Caddy's admin API on :2019 is disabled on this host,
# so `reload` validates the config and then fails to apply it with `connection
# refused` — reporting the file valid while changing nothing, which is the exact
# shape of the incident this deploy path exists to stop repeating.
#
# Caddy here is a systemd unit, not a container: `infra/secure_8443.sh` and
# `docs/qevik-docs/autonomous/DEPLOY_APP_QEVIK_AI.md` both restart it that way,
# and `infra/docker/docker-compose.yml` declares Postgres and nothing else.
echo "==> restarting Caddy"
# One attempt, not `ssh_`. Restarting is not something to retry blindly: a unit
# that fails to start answers non-zero every time, and five restarts in a row
# trip StartLimitBurst and leave it dead — the same way retrying a failing
# `systemctl restart` once killed four healthy workers on this host. A dropped
# link here is not silent either: the checks below ask the origin what it
# serves, and a config that was never applied still serves the homepage.
ssh "${SSH_OPTS[@]}" "$TARGET" "systemctl restart caddy" || true
# Asked separately, and also once: "the unit is not active" is an answer about
# Caddy, and retrying it would restart nothing and only delay the rollback.
ssh "${SSH_OPTS[@]}" "$TARGET" "systemctl is-active --quiet caddy" || {
  echo "FAILED: Caddy did not come up with the new config." >&2
  ssh "${SSH_OPTS[@]}" "$TARGET" "journalctl -u caddy -n 30 --no-pager" >&2 || true
  restore_config
  exit 5
}

# --- and then ask the server, rather than reporting that files were copied ----
#
# Asserted, not printed. Every page of qevik.ai was unreachable in production
# for weeks while the deploy exited zero, because nothing here had ever asked
# the server a question about the public site.
#
# At the origin, not through Cloudflare. This deploy changed what the origin
# serves; an edge cache can still be answering for what it served before, and a
# check that cannot tell those apart proves nothing about the deploy.
#
# `${2:-}` because `set -u` is on and most calls pass one argument; unquoted
# because the caller's extra curl flags have to reach the remote shell as
# separate words.
echo "==> what the origin answers now"
origin() {
  ssh_ "curl -sS --max-time 15 --resolve qevik.ai:443:127.0.0.1 ${2:-} 'https://qevik.ai$1'" 2>/dev/null || true
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
  echo "FAILED: the origin did not answer for qevik.ai/services/ at all." >&2
  exit 13
}
# The measured defect: every URL served the homepage. Its own title is the
# cheapest proof that /services/ is now serving its own page.
printf '%s' "$services" | grep -q '<title>Services' || {
  echo "FAILED: qevik.ai/services/ is not serving its own page — the site is" >&2
  echo "        still being served as a single-page application." >&2
  exit 9
}
[ "$miss_code" = "404" ] || {
  echo "FAILED: an unknown URL answered $miss_code, not 404." >&2
  exit 10
}
# Not just the status. A rewrite to a page that is not on the host answers with
# a bare file-server error, which is also a 404 — the exact failure that ships
# if the config is installed without the site.
printf '%s' "$miss_body" | grep -q 'That page is not here' || {
  echo "FAILED: the 404 status is right but the page is not the one this" >&2
  echo "        repository builds — /404.html is missing from the document root." >&2
  exit 11
}
# The Arabic site is a second site, not a translation layer, and being dropped
# into an English error page is where an Arabic visitor concludes otherwise.
# Spelled as an `if` rather than `A && B || C`: that idiom runs C when B fails
# too, which is wanted here and is exactly why it gets misread later.
if [ "$ar_code" != "404" ] || ! printf '%s' "$ar_body" | grep -q 'dir="rtl"'; then
  echo "FAILED: a wrong URL under /ar/ is not answered in Arabic ($ar_code)." >&2
  exit 12
fi
echo "OK: qevik.ai serves a page per URL, and an unknown URL gets the 404 page."

# --- and what a visitor gets, which is a different question ------------------
#
# Everything above asked the origin, deliberately. A visitor asks Cloudflare.
# Reported and never asserted: Cloudflare does not cache HTML unless a rule says
# to, so these should agree — and if they ever do not, the deploy is not the
# thing that is wrong and must not be the thing that fails. Printed because the
# alternative is discovering the disagreement from a person looking at the site.
echo "==> and through Cloudflare, for comparison"
edge() {
  curl -sS --max-time 20 -o /dev/null -w '%{http_code}' "https://qevik.ai$1" 2>/dev/null || echo 000
}
echo "    GET qevik.ai/services/    -> $(edge /services/) (200 expected)"
echo "    GET qevik.ai$miss -> $(edge "$miss") (404 expected)"
