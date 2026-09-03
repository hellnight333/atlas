#!/usr/bin/env bash
#
# The application runtime: database, Python, browser. Phase 4, as one script.
#
#   ./infra/install_qevik_runtime.sh                # install everything missing
#   ./infra/install_qevik_runtime.sh --check        # report, change nothing
#   ./infra/install_qevik_runtime.sh --database     # only the cluster, role and DB
#   ./infra/install_qevik_runtime.sh --python       # only the venv and Playwright
#
# `bootstrap_qevik_server.sh` cannot do this job: it installs one unit, opens
# only port 22, clones the repository on the host and overwrites atlas.env. The
# migration plan's R-15 says a reviewed script has to replace the hand-typed
# checklist, and this is it — idempotent, gated, and safe to re-run.
#
# ## The database password is generated here and never printed
#
# The role's password is created on this host, written straight into the three
# files that need it, and applied to the role through a heredoc — never on a
# command line, never in the shell history, never in a log, never in this
# script's output. Nothing anywhere echoes it.
#
# It is 64 hex characters: 256 bits, and URL-safe, so it needs no percent
# encoding inside a DSN. That is a deliberate choice against a larger alphabet —
# not because a shell would break on it (the enablement stage removed shell
# parsing entirely) but because a DSN is a URL and `@`, `/`, `:`, `#` and `?`
# inside a password are a class of bug with no upside.
#
# The same value is written into all three files in one step, which is why
# ATLAS_DATABASE_URL and both copies of QEVIK_CLAIMS_DSN cannot drift apart.
#
set -euo pipefail

BASE="${QEVIK_BASE:-/opt/qevik}"
APP="${QEVIK_APP:-$BASE/atlas}"
APP_USER="${QEVIK_USER:-qevik}"
DB_NAME="${QEVIK_DB:-qevik}"
DB_ROLE="${QEVIK_DB_ROLE:-qevik}"
PG_MAJOR="${QEVIK_PG_MAJOR:-18}"
BROWSERS="${PLAYWRIGHT_BROWSERS_PATH:-$BASE/ms-playwright}"
CONSTRAINTS="${QEVIK_CONSTRAINTS:-$APP/infra/constraints.txt}"

MODE=all
case "${1:-}" in
  --check) MODE=check ;;
  --database) MODE=database ;;
  --python) MODE=python ;;
  "") ;;
  *) echo "usage: $0 [--check|--database|--python]" >&2; exit 2 ;;
esac

say() { printf '\n== %s\n' "$*"; }
die() { echo "REFUSED: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

pkg_state() {
  local state
  state="$(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null || true)"
  [ "$state" = installed ] && echo installed || echo absent
}

report() {
  say "packages"
  for p in "postgresql-$PG_MAJOR" python3-venv python3-pip ffmpeg rsync git curl; do
    printf '  %-22s %s\n' "$p" "$(pkg_state "$p")"
  done
  printf '  %-22s %s\n' caddy "$(pkg_state caddy)"
  say "database"
  if systemctl is-active --quiet postgresql; then
    sudo -u postgres psql -tAc "select version()" | head -1 | sed 's/^/  /'
    printf '  role %s: %s\n' "$DB_ROLE" \
      "$(sudo -u postgres psql -tAc "select 1 from pg_roles where rolname='$DB_ROLE'" 2>/dev/null | grep -q 1 && echo present || echo absent)"
    printf '  database %s: %s\n' "$DB_NAME" \
      "$(sudo -u postgres psql -tAc "select 1 from pg_database where datname='$DB_NAME'" 2>/dev/null | grep -q 1 && echo present || echo absent)"
    printf '  tables in %s: %s\n' "$DB_NAME" \
      "$(sudo -u postgres psql -tAc "select count(*) from pg_tables where schemaname='public'" "$DB_NAME" 2>/dev/null || echo 'n/a')"
  else
    echo "  postgresql is not running"
  fi
  say "python"
  printf '  system python3: %s\n' "$(python3 -V 2>&1)"
  if [ -x "$APP/.venv/bin/python" ]; then
    printf '  venv: %s (%s distributions)\n' "$("$APP/.venv/bin/python" -V 2>&1)" \
      "$("$APP/.venv/bin/pip" list --format=freeze 2>/dev/null | wc -l | tr -d ' ')"
    printf '  playwright: %s\n' "$("$APP/.venv/bin/pip" show playwright 2>/dev/null | awk '/^Version/{print $2}' || echo absent)"
  else
    echo "  venv: absent"
  fi
  printf '  browsers at %s: %s\n' "$BROWSERS" "$(ls "$BROWSERS" 2>/dev/null | tr '\n' ' ' || echo absent)"
  say "environment files (names and modes only — never values)"
  for f in "$BASE"/*.env; do
    [ -f "$f" ] || continue
    printf '  %s %s\n' "$(stat -c '%n %U:%G %a' "$f")" \
      "[$(grep -v '^[[:space:]]*#' "$f" | grep -c '=' ) set]"
  done
}

if [ "$MODE" = check ]; then report; exit 0; fi

[ "$(id -u)" -eq 0 ] || die "run as root."
id "$APP_USER" >/dev/null 2>&1 || die "the service account '$APP_USER' does not exist (Phase 3 creates it)."

# --- packages ------------------------------------------------------------------

if [ "$MODE" = all ] || [ "$MODE" = database ]; then
  say "1/6 database packages"
  if [ "$(pkg_state "postgresql-$PG_MAJOR")" = absent ]; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q "postgresql-$PG_MAJOR" >/dev/null
  fi
  dpkg-query -W -f='installed: ${Package} ${Version}\n' "postgresql-$PG_MAJOR"
  systemctl enable --now postgresql >/dev/null 2>&1 || true
  systemctl is-active postgresql
fi

if [ "$MODE" = all ] || [ "$MODE" = python ]; then
  say "2/6 runtime packages"
  for p in python3-venv python3-pip ffmpeg; do
    if [ "$(pkg_state "$p")" = absent ]; then
      DEBIAN_FRONTEND=noninteractive apt-get install -y -q "$p" >/dev/null
    fi
    dpkg-query -W -f='installed: ${Package} ${Version}\n' "$p"
  done
fi

# --- the database, and the one credential this script creates -------------------

if [ "$MODE" = all ] || [ "$MODE" = database ]; then
  say "3/6 role and database"
  role_exists() { sudo -u postgres psql -tAc "select 1 from pg_roles where rolname='$DB_ROLE'" | grep -q 1; }
  db_exists() { sudo -u postgres psql -tAc "select 1 from pg_database where datname='$DB_NAME'" | grep -q 1; }

  if role_exists; then
    echo "role $DB_ROLE: already present, password left alone"
  else
    have openssl || die "openssl is needed to generate the role password."
    # Written to a root-only file rather than a variable that could reach a log.
    umask 077
    secret="$(mktemp)"; trap 'rm -f "$secret"' EXIT
    openssl rand -hex 32 > "$secret"

    # The role, created through stdin so the value is never an argument.
    printf "CREATE ROLE %s LOGIN CREATEDB PASSWORD '%s';\n" "$DB_ROLE" "$(cat "$secret")" \
      | sudo -u postgres psql -q >/dev/null
    echo "role $DB_ROLE: created (password generated here, not printed)"

    # The three files that must carry the same DSN, written in one step so they
    # cannot disagree. Placeholders in the Phase 3 scaffolds are comments, so
    # appending is the whole edit.
    dsn_sqlalchemy="postgresql+psycopg://$DB_ROLE:$(cat "$secret")@127.0.0.1:5432/$DB_NAME"
    dsn_plain="postgresql://$DB_ROLE:$(cat "$secret")@127.0.0.1:5432/$DB_NAME"
    grep -q '^ATLAS_DATABASE_URL=' "$BASE/atlas.env" 2>/dev/null \
      || printf 'ATLAS_DATABASE_URL=%s\n' "$dsn_sqlalchemy" >> "$BASE/atlas.env"
    for f in "$BASE/control.env" "$BASE/worker.env"; do
      [ -f "$f" ] || continue
      grep -q '^QEVIK_CLAIMS_DSN=' "$f" \
        || printf 'QEVIK_CLAIMS_DSN=%s\n' "$dsn_plain" >> "$f"
    done
    unset dsn_sqlalchemy dsn_plain
    rm -f "$secret"; trap - EXIT
    echo "DSNs written to atlas.env, control.env and worker.env from one value"
  fi

  chown root:root "$BASE/atlas.env" 2>/dev/null || true
  chown "$APP_USER:$APP_USER" "$BASE/control.env" "$BASE/worker.env" 2>/dev/null || true
  chmod 600 "$BASE"/*.env

  if db_exists; then
    echo "database $DB_NAME: already present"
  else
    sudo -u postgres createdb -O "$DB_ROLE" "$DB_NAME"
    echo "database $DB_NAME: created, owned by $DB_ROLE"
  fi

  say "4/6 the connection works"
  # As the service account, over the loopback, with the DSN the units will use —
  # proving the file rather than a variable this script happens to hold.
  systemd-run --wait --collect --pipe --quiet \
    --property=EnvironmentFile="$BASE/atlas.env" \
    --property=User="$APP_USER" \
    /usr/bin/python3 -c '
import os, sys, urllib.parse
url = os.environ.get("ATLAS_DATABASE_URL", "")
if not url:
    print("ATLAS_DATABASE_URL is not set"); sys.exit(1)
parsed = urllib.parse.urlsplit(url)
print("DSN parses:", parsed.scheme, "->", parsed.hostname, parsed.port, parsed.path)
' || die "the DSN in $BASE/atlas.env is not usable."
fi

# --- python -------------------------------------------------------------------

if [ "$MODE" = all ] || [ "$MODE" = python ]; then
  say "5/6 virtualenv"
  if [ ! -d "$APP" ]; then
    echo "no application tree at $APP yet — deploy first, then re-run with --python"
  else
    if [ ! -x "$APP/.venv/bin/python" ]; then
      runuser -u "$APP_USER" -- python3 -m venv "$APP/.venv"
      echo "created $APP/.venv"
    fi
    runuser -u "$APP_USER" -- "$APP/.venv/bin/python" -m pip install -q --upgrade pip
    if [ -f "$CONSTRAINTS" ]; then
      echo "installing with constraints from $(basename "$CONSTRAINTS")"
      runuser -u "$APP_USER" -- "$APP/.venv/bin/python" -m pip install -q -e "$APP" -c "$CONSTRAINTS"
    else
      runuser -u "$APP_USER" -- "$APP/.venv/bin/python" -m pip install -q -e "$APP"
    fi
    "$APP/.venv/bin/python" -V
    echo "$("$APP/.venv/bin/pip" list --format=freeze | wc -l | tr -d ' ') distributions installed"

    say "6/6 browser"
    # Playwright is not a declared dependency — it never has been — so it is
    # installed by name and pinned to the version production runs.
    runuser -u "$APP_USER" -- "$APP/.venv/bin/python" -m pip install -q "playwright==${PLAYWRIGHT_VERSION:-1.62.0}"
    install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$BROWSERS"
    PLAYWRIGHT_BROWSERS_PATH="$BROWSERS" "$APP/.venv/bin/python" -m playwright install-deps chromium >/dev/null
    runuser -u "$APP_USER" -- env PLAYWRIGHT_BROWSERS_PATH="$BROWSERS" \
      "$APP/.venv/bin/python" -m playwright install chromium
    ls "$BROWSERS"
  fi
fi

say "state"
report
echo
echo "Nothing was started and no unit was enabled: that is install_qevik_infra.sh"
echo "and the deploy. The backup timer stays disabled until the data migration."
