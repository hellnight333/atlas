#!/usr/bin/env bash
# Publish qevik.ai: the pages, and the config that decides how they resolve.
#
#   bash infra/deploy_public.sh [user@host]  build, ship, install, verify
#   bash infra/deploy_public.sh --check DIR  verify a built directory against the
#                                            Caddyfile and exit; touches no host
#   bash infra/deploy_public.sh --check-config FILE
#                                            say what the Caddyfile in FILE
#                                            serves that this repository's does
#                                            not, and exit non-zero if there is
#                                            anything; touches no host
#   bash infra/deploy_public.sh --restore-config [user@host]
#                                            put the config this script kept
#                                            back and restart Caddy on it; ships
#                                            nothing. For the one check this
#                                            script cannot make — see below.
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

# --- and what installing this config would stop the host serving -------------
#
# `/etc/caddy/Caddyfile` is replaced wholesale further down, and that file is
# the whole web server: four hostnames, one of them the operator's console and
# one of them every customer site. Anything the host serves that is not also in
# this repository's copy is gone at the restart — silently, with a zero exit,
# and invisible to every check below, all of which ask about qevik.ai.
#
# Two ways that is not hypothetical, both of them written down in this
# directory: `infra/enable_domain.sh` puts a customer domain in
# `/etc/caddy/sites.d/` and relies on an `import` in the live config to pull it
# in, and `infra/secure_8443.sh` rewrites the `:8443` block's address in place
# to take that port off the public internet. Neither is in
# `infra/qevik-production.Caddyfile`; a deploy that does not look would revert
# the second and drop the first.
#
# Refused rather than reported, which is the opposite of what the same question
# about the document root does further down — and the difference is the point.
# A host-only *file* under the document root 404s one URL and might have been
# left there by anybody; a host-only *site block* takes a whole hostname off the
# air, and every site block on a server is deliberate. There is nothing to guess
# about, so there is nothing to weigh: the config in this repository is either
# the whole config or it is not safe to install.

#: What a Caddyfile answers for: each site address it declares, and each
#: top-level `import`, which is a hostname this file cannot see.
#:
#: By brace depth, for the same reason `site_block` above is: a site address is
#: a line ending in `{` at depth zero, and every `handle`, `log` and
#: `file_server` block inside one ends in `{` too. Comments are stripped first
#: so a brace inside prose — this file's own header quotes `try_files {path}` —
#: is not counted as structure. Snippet definitions `(name) {` are declarations
#: rather than addresses and are skipped.
#:
#: Sorted under `LC_ALL=C`, and that matters. `comm` compares bytes, while
#: `sort` in a UTF-8 locale collates and ignores punctuation at the primary
#: level — so `site :80` and `site app.qevik.ai` can come out in an order `comm`
#: considers unsorted, and an unsorted input to `comm` does not error, it
#: answers wrongly. Both have to mean the same thing by "in order".
serves() {
  awk '
    { line = $0; sub(/(^|[ \t])#.*/, "", line) }
    depth == 0 && line ~ /^[ \t]*import[ \t]/ {
      n = split(line, w, /[ \t]+/)
      for (i = 1; i <= n; i++) if (w[i] == "import") { print "import " w[i + 1]; break }
    }
    # Bracket expressions throughout, never `\{`: a brace is an interval
    # operator in POSIX ERE and gawk warns on `\{` as an unknown escape. See
    # the longer note in `site_block`.
    depth == 0 && line ~ /[{][ \t]*$/ {
      head = line
      sub(/[ \t]*[{][ \t]*$/, "", head)
      # One block may be addressed by several names, comma-separated.
      gsub(/,/, " ", head)
      n = split(head, w, /[ \t]+/)
      for (i = 1; i <= n; i++)
        if (w[i] != "" && substr(w[i], 1, 1) != "(") print "site " w[i]
    }
    { depth += gsub(/[{]/, "{", line); depth -= gsub(/[}]/, "}", line) }
  ' "$1" | LC_ALL=C sort -u
}

#: `$1` is the config the host is running now. Non-zero if installing
#: `$CADDYFILE` over it would stop something being served.
check_config_against_live() {
  local live="$1" now new dropped added
  now="$(serves "$live")"
  new="$(serves "$CADDYFILE")"

  # The reader, checked against something already known. `site_block` above
  # found a `qevik.ai {` block in this same file — that is how `$DOCROOT` was
  # read — so `serves` must see it too. If it does not, the answer below is
  # about this function and not about the host, and a refusal that names the
  # wrong culprit is worse than no refusal: this deploy is the only thing that
  # applies the fix, and it must not be blocked by a misread it does not admit
  # to.
  #
  # Matched on the whole string rather than through `grep -q`: with `pipefail`
  # on, `grep -q` closing the pipe early can make `printf` fail with EPIPE and
  # the pipeline report non-zero on a line it did find.
  case $'\n'"$new"$'\n' in
    *$'\n'"site qevik.ai"$'\n'*) ;;
    *)
      echo "REFUSED: this script cannot read its own $(basename "$CADDYFILE") —" >&2
      echo "  no 'qevik.ai' among the addresses it found, though the block is" >&2
      echo "  there. That is a defect in serves(), not a change on the host." >&2
      echo "  Nothing was deployed." >&2
      return 1 ;;
  esac

  # A read that produced no site at all is not a host with no sites; it is a
  # file this could not parse, or a transfer that was cut. Either way what the
  # install would drop is unknown, and unknown is not a pass.
  [ -n "$now" ] || {
    echo "REFUSED: no site address could be read from the config now on the" >&2
    echo "  host ($live). What installing this one would stop serving is" >&2
    echo "  therefore unknown. Nothing was deployed." >&2
    return 1
  }

  echo "    the config to install serves:"
  printf '%s\n' "$new" | sed 's/^/        /'

  dropped="$(comm -23 <(printf '%s\n' "$now") <(printf '%s\n' "$new"))"
  added="$(comm -13 <(printf '%s\n' "$now") <(printf '%s\n' "$new"))"
  if [ -n "$added" ]; then
    echo "    and adds, which is the direction this deploy is for:"
    printf '%s\n' "$added" | sed 's/^/        /'
  fi

  if [ -n "$dropped" ]; then
    echo >&2
    echo "REFUSED: the host's /etc/caddy/Caddyfile serves this, and the config" >&2
    echo "  about to replace it does not:" >&2
    printf '%s\n' "$dropped" | sed 's/^/        /' >&2
    echo >&2
    echo "  Installing it would take those off the air at the next Caddy" >&2
    echo "  restart, and nothing in this deploy would notice — every check it" >&2
    echo "  makes afterwards asks about qevik.ai." >&2
    echo >&2
    echo "  Something was added on the host and never written down here. Copy" >&2
    echo "  the block into $(basename "$CADDYFILE") and run this again." >&2
    echo "  Nothing was deployed." >&2
    return 1
  fi
  echo "    nothing the host serves today would stop being served"
  return 0
}

if [ "${1:-}" = "--check-config" ]; then
  [ -n "${2:-}" ] || { echo "usage: $0 --check-config <live-caddyfile>" >&2; exit 64; }
  [ -f "${2}" ] || { echo "REFUSED: no such file: $2" >&2; exit 1; }
  check_config_against_live "$2" || exit 7
  exit 0
fi

# `--restore-config [user@host]`: put the kept config back and nothing else.
#
# `deploy_control.sh` calls this when the one check only it can make fails —
# whether `app.qevik.ai/api/*` still reaches the control plane through the Caddy
# this script just restarted. That failure is invisible from here: a config can
# serve every page of qevik.ai correctly and still stop routing the API, and
# every check below would pass while production had no API.
#
# The rollback lives in the script that took the backup rather than being
# written out a second time over there. One place knows where the backup is and
# one place knows Caddy must be `reset-failed` before it is restarted — the same
# reason the pages and the config that names them are shipped by one script.
#
# Config only. The new pages stay at the document root, which is safe in this
# direction and not the other: the previous config resolves them (it rewrote
# everything to the homepage regardless), so the marketing site degrades to what
# it was doing last week while the API comes back.
MODE=""
if [ "${1:-}" = "--restore-config" ]; then MODE=restore; shift; fi

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

# Fetch the config the host is running now, into `$LIVE_CONFIG`.
#
# Not through `ssh_`: that returns the first attempt that works, and a caller
# redirecting its stdout to a file would have the failed attempts' partial
# output in front of the good one. Each attempt here truncates the file itself,
# so what is left is one whole read or nothing.
#
# Three answers, and they are different: 0 the file was read, 3 the host has no
# such file, anything else the link failed. A partial read cannot masquerade as
# a small config — `cat` over ssh reports non-zero unless the remote command
# finished and the channel closed cleanly.
read_live_config() {
  local try status
  for try in 1 2 3; do
    if ssh "${SSH_OPTS[@]}" "$TARGET" \
         "[ -f /etc/caddy/Caddyfile ] || exit 3; cat /etc/caddy/Caddyfile" \
         > "$LIVE_CONFIG" 2>/dev/null
    then return 0
    else status=$?
    fi
    [ "$status" = 3 ] && return 3
    [ "$try" = 3 ] && return 1
    echo "    (link dropped; retry $try)" >&2
    sleep $(( try * 3 ))
  done
}

# --- the rollback ------------------------------------------------------------
#
# Defined here rather than beside the install below because `--restore-config`
# runs it and nothing else. Three callers, all of them a config that is live and
# should not be: one that would not move into place, one that would not start,
# and — from `deploy_control.sh` — one that started and stopped routing the API.
#
# Returns non-zero when the rollback itself failed, which is a different and
# much louder thing than the deploy failing: it means Caddy is holding a config
# nobody chose and no script here can take it back.
restore_config() {
  echo "==> putting the previous config back and restarting" >&2
  # Retried, and `cp` names the missing backup itself if there is none. The
  # existence check is deliberately not asked first as its own question: a
  # dropped link on that question would abandon a rollback that was going to
  # work, and this is not the path on which to be clever about which non-zero
  # means what.
  ssh_ "cp -a /etc/caddy/Caddyfile.previous /etc/caddy/Caddyfile" >&2 || {
    echo "  the previous config could NOT be put back. Caddy is holding whatever" >&2
    echo "  it was last given and /etc/caddy/Caddyfile needs a person." >&2
    return 1
  }
  # `reset-failed` first, and inside the retried command rather than beside it.
  # This runs when Caddy has just refused to start, so its start counter is
  # already ticking; without this a retried rollback can trip StartLimitBurst
  # and leave the unit dead with a config that would have worked. Four workers
  # were lost to exactly that once.
  ssh_ "systemctl reset-failed caddy 2>/dev/null; systemctl restart caddy" >&2 || true
  # A rollback that leaves the unit dead is not a rollback, and reporting it as
  # one is how the next person spends the outage reading application logs.
  # One attempt, like the same question on the deploy path: "the unit is not
  # active" is an answer about Caddy, not a dropped link.
  ssh "${SSH_OPTS[@]}" "$TARGET" "systemctl is-active --quiet caddy" || {
    echo "  the previous config is back on disk and Caddy did not start on it" >&2
    echo "  either. All four hostnames are down; this needs a person." >&2
    return 2
  }
  echo "    the previous config is back and Caddy is running on it" >&2
  return 0
}

if [ "$MODE" = restore ]; then
  restore_config || exit $?
  exit 0
fi

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

# Before anything on the host is touched, so a refusal here leaves it exactly as
# it was — including the pages, which are cheap to send again and not cheap to
# have half-swapped under a config this is about to decline to install. See the
# note on `check_config_against_live` for why this one refuses.
echo "==> what the host's config serves, against what this one would"
LIVE_CONFIG="$WORK/live.Caddyfile"
LIVE_STATUS=0
read_live_config || LIVE_STATUS=$?
case "$LIVE_STATUS" in
  0) check_config_against_live "$LIVE_CONFIG" || exit 7 ;;
  3) echo "    the host has no /etc/caddy/Caddyfile, so this drops nothing" ;;
  *) echo "REFUSED: the config now on the host could not be read, so what" >&2
     echo "  installing this one would stop serving is unknown. Nothing was" >&2
     echo "  deployed." >&2
     exit 8 ;;
esac

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

echo "==> staging $(basename "$CADDYFILE") beside /etc/caddy/Caddyfile"
# Beside the live file, never onto it.
#
# `scp` opens the destination and truncates it before the first byte arrives,
# and this link drops roughly one attempt in five — so a copy straight to
# `/etc/caddy/Caddyfile` can leave a half-written config on disk while the
# transfer reports failure. Caddy goes on serving what it already has in memory,
# so the deploy would say "it is still serving its previous configuration" and
# be right, until the next restart or reboot. Then all four hostnames go.
#
# A truncated Caddyfile is worse than a broken one, because a cut that happens
# to land after a site block closes is still *valid*: Caddy starts clean and the
# hostnames past the cut have simply stopped existing.
#
# Staged inside /etc/caddy so the move below is a rename within one filesystem,
# and so a Caddyfile `import` of a relative path would resolve from the same
# directory it will resolve from once installed.
#
# Retried, unlike the copy this replaces: a dropped link onto a scratch path is
# a dropped link and nothing more, and leaving the one un-retried transfer in a
# script that documents a one-in-five drop rate inside an unattended gate means
# a working host reported broken.
scp_config() {
  local try
  for try in 1 2 3; do
    if scp "${SSH_OPTS[@]}" -q "$CADDYFILE" "$TARGET:/etc/caddy/Caddyfile.incoming"; then
      return 0
    fi
    [ "$try" = 3 ] && return 1
    echo "    (link dropped; retry $try)" >&2
    sleep $(( try * 3 ))
  done
}
scp_config || {
  echo "REFUSED: the Caddyfile could not be copied to the host. Nothing was" >&2
  echo "  installed — /etc/caddy/Caddyfile was never opened, so the host is" >&2
  echo "  still serving its previous configuration and still has it on disk." >&2
  echo "  The pages above did land." >&2
  ssh_ "rm -f /etc/caddy/Caddyfile.incoming" >&2 || true
  exit 6
}

# Validate the copy that is about to be installed, before it is installed, with
# the host's own binary. A config that parses here and not there — an
# `expression` matcher an older Caddy rejects, say — takes down all four
# hostnames, not just this one.
#
# `--adapter caddyfile` because Caddy infers the adapter from the file name and
# this file is not called `Caddyfile` yet; without it the staged copy is read as
# JSON and every valid config fails to validate.
ssh "${SSH_OPTS[@]}" "$TARGET" \
  "caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile.incoming" || {
  echo "REFUSED: the Caddyfile did not validate on the host. It was not" >&2
  echo "  installed and nothing was restarted; the live config is untouched." >&2
  ssh_ "rm -f /etc/caddy/Caddyfile.incoming" >&2 || true
  exit 4
}

# Now, and only now. A rename within /etc/caddy, so /etc/caddy/Caddyfile is
# either the whole previous config or the whole new one and never a fragment of
# either — and the new one has already been validated by the binary that is
# about to read it.
#
# `chmod` first because the installed file inherits the staged file's mode, and
# the mode of the copy in this repository is not something the host should
# depend on.
echo "==> installing it as /etc/caddy/Caddyfile"
ssh_ "chmod 644 /etc/caddy/Caddyfile.incoming && \
  mv /etc/caddy/Caddyfile.incoming /etc/caddy/Caddyfile" || {
  echo "REFUSED: the validated config could not be moved into place." >&2
  # The rename either happened or it did not, but a link dropped after it
  # happened looks identical from here — and that state is a new config on disk
  # under an old config in memory, which is the exact thing this staging exists
  # to prevent. Put the previous one back so disk and memory agree either way.
  restore_config || true
  exit 6
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
  restore_config || true
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
# And a failure below is not the same kind of failure as the ones above, which
# is where that stops being a remark and becomes a rollback.
#
# Everything that refuses earlier leaves the host either untouched or already
# put back: a build missing a page, a transfer that did not land, a config that
# would not validate, a Caddy that would not start. From this line on the host
# is *running* the config out of this repository, so a wrong answer to any
# question below is proof that this config is the wrong one — and exiting on
# that proof, and doing nothing else with it, hands the caller a red gate while
# leaving production serving the configuration the deploy has just disproved.
# The caller sees a failed deploy; a visitor sees the failure. A red gate is not
# a restored service.
#
# So every give-up below goes through here rather than through `exit`. It
# belongs in this script and not in its caller: `deploy_control.sh` runs this
# unattended inside the development loop's deploy gate and can only act on an
# exit code, and a caller that restored on any non-zero would restore on the
# failures that installed nothing — where `/etc/caddy/Caddyfile.previous` is
# whatever the *last* deploy left there, and putting that back over a live
# config is a fresh outage caused by a build refusing. This script does not have
# to guess. It took the backup itself, and it knows it got past it.
#
# "The origin answered nothing" is included on purpose. Caddy answered
# `is-active` a moment ago, so a server that then serves nothing for qevik.ai is
# a config that serves nothing; and if it is the link that died rather than the
# site, the rollback needs that same link and will say so loudly. An unverified
# config is not one to leave in production, for the same reason an unreadable
# live config is not consent to install over it.
#
# The exit code stays whichever the check chose. *Which* question was answered
# wrongly is what the next person needs; that it was rolled back is the line
# above it.
restore_and_exit() {
  echo "        that config is live, and it is the one that answered. Putting" >&2
  echo "        the previous one back." >&2
  restore_config || {
    echo "        AND the rollback failed. Caddy is holding a config nobody" >&2
    echo "        chose; /etc/caddy/Caddyfile on the host needs a person." >&2
  }
  exit "$1"
}

echo "==> what the origin answers now"
# `${2:-}` because `set -u` is on and most calls pass one argument; unquoted
# because the caller's extra curl flags have to reach the remote shell as
# separate words.
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
  restore_and_exit 13
}
# The measured defect: every URL served the homepage. Its own title is the
# cheapest proof that /services/ is now serving its own page.
printf '%s' "$services" | grep -q '<title>Services' || {
  echo "FAILED: qevik.ai/services/ is not serving its own page — the site is" >&2
  echo "        still being served as a single-page application." >&2
  restore_and_exit 9
}
[ "$miss_code" = "404" ] || {
  echo "FAILED: an unknown URL answered $miss_code, not 404." >&2
  restore_and_exit 10
}
# Not just the status. A rewrite to a page that is not on the host answers with
# a bare file-server error, which is also a 404 — the exact failure that ships
# if the config is installed without the site.
printf '%s' "$miss_body" | grep -q 'That page is not here' || {
  echo "FAILED: the 404 status is right but the page is not the one this" >&2
  echo "        repository builds — /404.html is missing from the document root." >&2
  restore_and_exit 11
}
# The Arabic site is a second site, not a translation layer, and being dropped
# into an English error page is where an Arabic visitor concludes otherwise.
# Spelled as an `if` rather than `A && B || C`: that idiom runs C when B fails
# too, which is wanted here and is exactly why it gets misread later.
if [ "$ar_code" != "404" ] || ! printf '%s' "$ar_body" | grep -q 'dir="rtl"'; then
  echo "FAILED: a wrong URL under /ar/ is not answered in Arabic ($ar_code)." >&2
  restore_and_exit 12
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
