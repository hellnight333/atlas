#!/usr/bin/env bash
#
# Install a Caddy that can actually run this repository's configuration.
#
#   ./infra/install_caddy.sh                 # install and gate
#   ./infra/install_caddy.sh --check-only    # gate what is already installed
#
# Ubuntu 26.04 ships Caddy **2.6.2**. `infra/qevik-production.Caddyfile` answers
# a missing page with `handle_errors` + `file_server { status 404 }`, which needs
# **Caddy >= 2.7**: on 2.6.2 the config does not validate, and a config that does
# not validate is a web server that does not start. Production runs 2.11.4 from
# Caddy's own apt repository, so that is what the target gets — parity with the
# host being replaced, and the same packaged unit, `caddy` user and
# `/var/lib/caddy` layout that the certificate decision (D-E) assumes.
#
# Two gates, both refusals rather than warnings:
#   1. the installed version is >= the floor the configuration needs;
#   2. `caddy validate` accepts the configuration this repository ships.
#
# The repository's signing key is pinned by **GPG fingerprint** — the key that
# signs the packages, not an SSH host key — and verified before it is written to
# the keyring. A mismatch aborts before apt is told to trust anything.
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

#: The minimum the shipped Caddyfile can run on. `handle_errors` with an explicit
#: `status` in `file_server` landed in 2.7.
CADDY_MIN="${CADDY_MIN:-2.7.0}"
#: What production runs. Below this the install still succeeds, with a warning:
#: the floor is the correctness gate, this is the parity target.
CADDY_PARITY="${CADDY_PARITY:-2.11.4}"

REPO_URL="${CADDY_REPO_URL:-https://dl.cloudsmith.io/public/caddy/stable/deb/debian}"
KEY_URL="${CADDY_KEY_URL:-https://dl.cloudsmith.io/public/caddy/stable/gpg.key}"
#: Fingerprint of the GPG key that signs the caddy/stable repository — the key
#: that signs the *packages*, not an SSH host key. Verified against the
#: downloaded key before it is written to the keyring; a mismatch aborts before
#: apt is told to trust anything.
#:
#: Provenance (this constant is the trust anchor, so where it came from matters):
#: read on 2026-09-03 from the keyring of the host that has been verifying Caddy
#: packages from this repository since 2026-08-17 —
#:   gpg --show-keys /usr/share/keyrings/caddy-stable-archive-keyring.gpg
#:   pub rsa4096 2016-04-01 [SC] 65760C51EDEA2017CEA2CA15155B6D79CA56EA34
#:   uid "Caddy Web Server <contact@caddyserver.com>"
#: keyring sha256 c17cd5298a0bab02fda439fff278d9a55df2120cf9dac790c6ce71930db90b37
KEY_FPR="${CADDY_KEY_FPR:-65760C51EDEA2017CEA2CA15155B6D79CA56EA34}"
KEYRING=/usr/share/keyrings/caddy-stable-archive-keyring.gpg
LIST=/etc/apt/sources.list.d/caddy-stable.list
CADDYFILE="${QEVIK_CADDYFILE:-$HERE/qevik-production.Caddyfile}"

say() { printf '\n== %s\n' "$*"; }
die() { echo "REFUSED: $*" >&2; exit 1; }

#: `sort -V` decides, so 2.10 is newer than 2.9 rather than older.
version_at_least() {
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]
}

installed_version() {
  command -v caddy >/dev/null || return 1
  # `caddy version` prints "v2.11.4 h1:..."; the leading v and the hash go.
  caddy version 2>/dev/null | head -1 | awk '{print $1}' | sed 's/^v//'
}

gate_version() {
  local found
  found="$(installed_version)" || die "caddy is not installed."
  [ -n "$found" ] || die "could not read a version from \`caddy version\`."
  case "$found" in
    [0-9]*) ;;
    *) die "\`caddy version\` printed '$found', which is not a version. A check that cannot run is a refusal, never a pass." ;;
  esac
  version_at_least "$found" "$CADDY_MIN" \
    || die "caddy $found is older than $CADDY_MIN, which this repository's Caddyfile needs (handle_errors + file_server status). Ubuntu's package is 2.6.2 and is not usable here."
  if version_at_least "$found" "$CADDY_PARITY"; then
    echo "caddy $found (>= $CADDY_MIN, >= production $CADDY_PARITY)"
  else
    echo "caddy $found (>= $CADDY_MIN, but production runs $CADDY_PARITY — note the difference in the phase evidence)"
  fi
}

gate_config() {
  [ -f "$CADDYFILE" ] || die "no configuration at $CADDYFILE to validate."
  caddy validate --config "$CADDYFILE" >/dev/null \
    || die "caddy validate rejected $CADDYFILE. Nothing was started."
  echo "caddy validate: $CADDYFILE is accepted by this build"
}

if [ "${1:-}" = "--check-only" ]; then
  say "version"; gate_version
  say "configuration"; gate_config
  exit 0
fi

[ "$(id -u)" -eq 0 ] || die "run as root (this installs an apt source and a package)."

say "1/4 what is installed now"
if found="$(installed_version)" && version_at_least "$found" "$CADDY_MIN"; then
  echo "caddy $found already satisfies the floor; nothing to install"
else
  echo "${found:-no caddy} — installing from $REPO_URL"

  say "2/4 the repository signing key, pinned by fingerprint"
  [ -n "$KEY_FPR" ] || die "CADDY_KEY_FPR is empty. The signing key must be pinned before apt is told to trust it — put the fingerprint in this script (or the environment) and record where it came from."
  command -v gpg >/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -y -q gnupg >/dev/null
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  curl -fsSL "$KEY_URL" -o "$tmp/caddy.key" || die "could not download the signing key."
  got="$(gpg --show-keys --with-colons --fingerprint "$tmp/caddy.key" 2>/dev/null \
         | awk -F: '/^fpr:/ {print $10; exit}')"
  [ -n "$got" ] || die "the downloaded key has no readable fingerprint."
  if [ "$got" != "$KEY_FPR" ]; then
    echo "  expected $KEY_FPR" >&2
    echo "  got      $got" >&2
    die "the signing key is not the pinned one. Nothing was trusted, nothing installed."
  fi
  echo "signing key fingerprint matches the pin ($got)"
  gpg --dearmor < "$tmp/caddy.key" > "$KEYRING"
  chmod 644 "$KEYRING"
  printf 'deb [signed-by=%s] %s any-version main\n' "$KEYRING" "$REPO_URL" > "$LIST"
  chmod 644 "$LIST"

  say "3/4 apt"
  DEBIAN_FRONTEND=noninteractive apt-get update -q -o Dir::Etc::sourcelist="$LIST" \
    -o Dir::Etc::sourceparts=/dev/null -o APT::Get::List-Cleanup=0 >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q caddy >/dev/null
  # The artifact, for the phase evidence: version, origin and package digest.
  dpkg-query -W -f='installed: ${Package} ${Version}\n' caddy
  apt-cache policy caddy | sed -n '1,6p'
  if deb="$(ls -1t /var/cache/apt/archives/caddy_*.deb 2>/dev/null | head -1)" && [ -n "$deb" ]; then
    echo "package sha256: $(sha256sum "$deb")"
  else
    echo "package sha256: (the .deb was not retained by apt; record dpkg's version instead)"
  fi
fi

say "4/4 gates"
gate_version
gate_config
echo
echo "Caddy is installed and can run this repository's configuration."
echo "It has NOT been started and no configuration was installed: that is a"
echo "deploy step (deploy_console.sh), and on a host with no traffic yet the"
echo "certificate decision (D-E) comes first."
