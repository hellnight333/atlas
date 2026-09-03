#!/usr/bin/env bash
# Publish the public marketing site to the host that serves qevik.ai.
#
#   bash infra/deploy_public.sh --target <name>|user@host   build, ship, verify
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
# So the two travel together: `infra/deploy_console.sh` calls this before it
# installs the Caddyfile, and this refuses if the build does not contain every
# path that Caddyfile names.
#
# The document root and the error-page paths are **read out of the Caddyfile**
# rather than written down a second time. A rewrite target added there without a
# page behind it fails here, on the operator's machine, instead of on qevik.ai.
#
# `--check` answers three questions about a built directory, and it needs no
# host, no network and no credentials to answer any of them:
#
#   1. Does the config still resolve directories by their own index.html, or has
#      the single-page-application fallback come back? Under `try_files` every
#      URL serves the homepage and nothing 404s, so 2 and 3 would pass against a
#      site serving one page.
#   2. Is every file the config names — each `handle_errors` rewrite target —
#      in the build, at exactly that path?
#   3. Does every URL `sitemap.xml` advertises resolve to a page of its own,
#      under the same rule `file_server` uses?
#
# Note: `apps/public/assets/` is covered by the blanket `assets/` rule in
# .gitignore, so the artwork is not in the repository and this must be run from
# a working tree that has it. The build refuses by name for anything missing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
#: Overridable so the tests can point the same checks at a fixture config.
CADDYFILE="${QEVIK_CADDYFILE:-$ROOT/infra/qevik-production.Caddyfile}"

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

# The premise every check below rests on. `try_files {path} /index.html` is the
# single-page-application fallback and this site is not one: `build.py` writes a
# directory per page, `try_files` tests for a *file*, and `/services/` is a
# directory — so it misses and is rewritten to the homepage. Under that config
# every URL resolves, nothing 404s, and asking "is /404.html present" says
# nothing at all, because the rewrite that would reach it never fires. Refuse
# the config rather than pass a build against it.
if printf '%s\n' "$BLOCK" | grep -q '^[[:space:]]*try_files'; then
  echo "REFUSED: the qevik.ai block of $CADDYFILE carries try_files." >&2
  echo "  That is the single-page-application fallback, and this site is not a" >&2
  echo "  single-page application: apps/public/build.py writes a directory per" >&2
  echo "  page. Under it every directory URL serves the homepage with a 200 and" >&2
  echo "  no URL reaches the 404 page, so the checks below would pass against a" >&2
  echo "  site serving one page. file_server resolves a directory to its own" >&2
  echo "  index.html unaided. Nothing was deployed." >&2
  exit 1
fi

# Every URL a built sitemap advertises, as a path. One `<loc>` per line is what
# `build.py` writes; the host is dropped rather than matched, so a sitemap built
# for a staging hostname reads the same as one built for qevik.ai.
sitemap_urls() {
  sed -n 's|.*<loc>https\{0,1\}://[^/]*\([^<]*\)</loc>.*|\1|p' "$1"
}

# --- the check both modes run

# A build that does not satisfy the config must never reach the host. Run before
# the transfer, and again on the host after it, because "the files were correct
# here" and "the files are correct there" are different claims.
check_build() {
  local dist="$1" missing="" unreachable="" advertised="" candidate="" url="" count=0
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

  # And every URL the site advertises resolves under the rule the config serves
  # by. The two halves are different failures: the rewrite targets above are
  # files the *config* names, and these are pages the *sitemap* names. A build
  # that stops emitting services/index.html satisfies every check above and
  # still 404s a URL this site tells search engines is a page — the same defect
  # as the homepage-for-everything one, pointing the other way.
  #
  # Read out of the built sitemap rather than listed here, for the reason the
  # rewrite targets are: a second list drifts, and it drifts towards advertising
  # more than the build contains.
  advertised="$(sitemap_urls "$dist/sitemap.xml" || true)"
  [ -n "$advertised" ] || {
    echo >&2
    echo "REFUSED: $dist/sitemap.xml advertises no URLs at all." >&2
    echo "  Every check of the sitemap then passes by having nothing to check," >&2
    echo "  which is indistinguishable from a site that resolves. Nothing was" >&2
    echo "  deployed." >&2
    exit 1
  }

  for url in $advertised; do
    # Exactly what `root * <docroot>` + `file_server` does: a path ending in "/"
    # is a directory served by its own index.html, anything else is a file.
    case "$url" in
      */) candidate="${url#/}index.html" ;;
      *) candidate="${url#/}" ;;
    esac
    [ -f "$dist/$candidate" ] || unreachable="$unreachable $url"
    count=$((count + 1))
  done

  if [ -n "$unreachable" ]; then
    echo >&2
    echo "REFUSED: the sitemap advertises URLs this build cannot serve:" >&2
    for url in $unreachable; do echo "    $url" >&2; done
    echo >&2
    echo "  The config resolves a directory to its own index.html and answers a" >&2
    echo "  miss with the 404 page, so each of these would 404 on qevik.ai while" >&2
    echo "  sitemap.xml tells search engines it is a page. Nothing was deployed." >&2
    exit 1
  fi
  echo "    all $count URLs in the sitemap resolve to a page of their own"
}

if [ "${1:-}" = "--check" ]; then
  [ -n "${2:-}" ] || { echo "usage: $0 --check <built-directory>" >&2; exit 64; }
  check_build "$2"
  exit 0
fi

# Where this deploy is allowed to go, and with which key — one reviewed
# registry, no implicit production default. `deploy_console.sh` calls this
# script after resolving; the exported target is reused rather than re-derived,
# so the two halves of one deploy cannot land on different hosts.
. "$ROOT/infra/deploy_target.sh"
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
echo "target: $QEVIK_TARGET_NAME -> $TARGET (identity ${QEVIK_TARGET_KEY:-ssh_config})"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=20 -o ConnectionAttempts=4 \
          -o IdentitiesOnly=yes)
[ -n "$QEVIK_TARGET_KEY" ] && SSH_OPTS+=(-i "$QEVIK_TARGET_KEY")

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
ssh "${SSH_OPTS[@]}" "$TARGET" true 2>/dev/null || {
  echo "REFUSED: no SSH access to $TARGET. Nothing was deployed." >&2
  exit 2
}

echo "==> copying the site to $DOCROOT"
ssh "${SSH_OPTS[@]}" "$TARGET" "rm -rf '$DOCROOT.incoming' && mkdir -p '$DOCROOT.incoming'"
rsync -az --partial -e "ssh ${SSH_OPTS[*]}" "$DIST/" "$TARGET:$DOCROOT.incoming/"
# Caddy does not run as the user this copies as. A file it cannot read is a 403,
# which looks like an application fault and is a permission bit.
ssh "${SSH_OPTS[@]}" "$TARGET" "chmod -R a+rX '$DOCROOT.incoming'"

# Verify before swapping. A half-copied site that is live is worse than the
# previous one still being live, and this is the last moment it is cheap to
# stop.
REMOTE_REQUIRED="index.html sitemap.xml robots.txt"
for target in $REWRITES; do REMOTE_REQUIRED="$REMOTE_REQUIRED ${target#/}"; done
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
ssh "${SSH_OPTS[@]}" "$TARGET" "rm -rf '$DOCROOT.previous' && \
  { [ -d '$DOCROOT' ] && mv '$DOCROOT' '$DOCROOT.previous' || true; } && \
  mv '$DOCROOT.incoming' '$DOCROOT'"

echo "==> what the origin answers now"
# At the origin, not through Cloudflare: this deploy changed what the origin
# serves, and an edge cache would answer for the previous one.
#
# Reported, not asserted. What a URL resolves to is decided by
# /etc/caddy/Caddyfile, which this script does not install — `deploy_console.sh`
# does, and it asserts on these same URLs once it has. Failing here would blame
# the content deploy for a config that has not been rolled out yet.
probe() {
  ssh "${SSH_OPTS[@]}" "$TARGET" \
    "curl -sS --max-time 15 --resolve qevik.ai:443:127.0.0.1 -o /dev/null -w '%{http_code}' 'https://qevik.ai$1'" 2>/dev/null || echo 000
}
echo "    GET /                     -> $(probe /)"
echo "    GET /services/            -> $(probe /services/)"
echo "    GET /nope-$$/             -> $(probe "/nope-$$/")"
echo
echo "published. How these URLs resolve is decided by /etc/caddy/Caddyfile;"
echo "infra/deploy_console.sh installs it and verifies the result."
