#!/usr/bin/env bash
#
# Bring Qevik up on the canonical server (qevik-core-01 class: Ubuntu, 4 vCPU,
# 8 GB). Idempotent — safe to re-run.
#
#   ssh root@HOST 'bash -s' < infra/bootstrap_qevik_server.sh
#
# Exists because §0 rule 10 of the execution spec requires a reproducible
# deployment path. The first bring-up was done by hand, which is the state that
# rule forbids leaving behind, so this script is the record of what actually
# worked rather than a description of what should.
#
# Decisions worth stating:
#
#   * A non-root `qevik` user owns everything (§28).
#   * PostgreSQL is installed natively rather than in Docker. Docker is not
#     present on this box and a container runtime is a lot of moving parts to
#     add on 8 GB for one database. Ubuntu's postgres already listens on
#     loopback only, which is what §28 asks for.
#   * The venv falls back to `--without-pip` if the dpkg lock is held. On the
#     other Hetzner box `unattended-upgrades` had held that lock for thirteen
#     days; a bootstrap that cannot proceed because a package manager is wedged
#     is not a reproducible path.
#   * The firewall is opened for SSH *before* it is enabled. §28 is explicit
#     about not removing the recovery path, and the order of those two commands
#     is the whole difference.
#   * No password is ever printed. It is generated, written 0600, and read back
#     from disk when needed.
#
set -euo pipefail

REPO_SSH="${QEVIK_REPO:-git@github.com:hellnight333/atlas.git}"
APP_USER="${QEVIK_USER:-qevik}"
BASE="${QEVIK_BASE:-/opt/qevik}"
APP="${BASE}/atlas"
ENV_FILE="${BASE}/atlas.env"
SECRET="${BASE}/.pgpass"

say() { printf '\n=== %s ===\n' "$1"; }
export DEBIAN_FRONTEND=noninteractive

say "packages"
if fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
    echo "dpkg lock is held; skipping apt and using fallbacks"
    APT_OK=0
else
    apt-get update -qq || true
    # ffmpeg is not optional. Without it 85 media tests skip, and the suite then
    # reports 88% coverage against a 90% gate -- a red build caused by a missing
    # binary rather than by any code being wrong, which is the most misleading
    # kind of failure.
    apt-get install -y -qq python3-venv python3-pip postgresql git curl ffmpeg >/dev/null 2>&1 \
        && { echo "python3-venv, postgresql, git, curl, ffmpeg present"; APT_OK=1; } \
        || { echo "apt install failed; continuing with fallbacks"; APT_OK=0; }
fi

say "application user"
id "$APP_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$APP_USER"
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$BASE"
install -d -o "$APP_USER" -g "$APP_USER" -m 0700 "/home/${APP_USER}/.ssh"
echo "${APP_USER} owns ${BASE}"

say "deploy key"
KEY="/home/${APP_USER}/.ssh/id_ed25519"
if [ ! -f "$KEY" ]; then
    sudo -u "$APP_USER" ssh-keygen -t ed25519 -N "" -C "${APP_USER}@$(hostname)" -f "$KEY" -q
    echo "NEW KEY GENERATED. Add this public key to the repo as a read-only deploy key:"
    cat "${KEY}.pub"
    echo "then re-run this script."
    exit 2
fi
# `-n` matters more than it looks. This script is normally delivered as
# `ssh HOST 'bash -s' < bootstrap.sh`, so the remote shell is reading the script
# itself from stdin. An inner ssh without -n reads that same stdin and swallows
# the remainder of the script, which then simply stops — no error, no output,
# nothing in `bash -x` except the last line that ran. It cost a confused
# debugging round to find.
sudo -u "$APP_USER" ssh -n -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
    -T git@github.com 2>&1 | head -1 || true

say "source"
if [ -d "${APP}/.git" ]; then
    sudo -u "$APP_USER" git -C "$APP" fetch --quiet origin
    sudo -u "$APP_USER" git -C "$APP" reset --hard origin/main --quiet
else
    sudo -u "$APP_USER" git clone --quiet "$REPO_SSH" "$APP"
fi
sudo -u "$APP_USER" git -C "$APP" log --oneline -1

say "python environment"
if [ ! -x "${APP}/.venv/bin/python" ]; then
    if sudo -u "$APP_USER" python3 -c "import ensurepip" 2>/dev/null; then
        sudo -u "$APP_USER" python3 -m venv "${APP}/.venv"
    else
        sudo -u "$APP_USER" python3 -m venv --without-pip "${APP}/.venv"
        sudo -u "$APP_USER" bash -c "curl -sS https://bootstrap.pypa.io/get-pip.py | ${APP}/.venv/bin/python -" >/dev/null
    fi
fi
sudo -u "$APP_USER" "${APP}/.venv/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1 || true
sudo -u "$APP_USER" "${APP}/.venv/bin/python" -m pip install -q -e "${APP}[dev]" \
    || sudo -u "$APP_USER" "${APP}/.venv/bin/python" -m pip install -q -e "${APP}"
echo "python $(sudo -u "$APP_USER" "${APP}/.venv/bin/python" -V 2>&1 | cut -d' ' -f2), deps installed"

say "database"
systemctl is-active --quiet postgresql || systemctl start postgresql
systemctl enable --quiet postgresql 2>/dev/null || true

if [ ! -f "$SECRET" ]; then
    openssl rand -base64 33 | tr -d '/+=\n' | head -c 40 > "$SECRET"
    chmod 600 "$SECRET"
fi
PW="$(cat "$SECRET")"

# Role and database are created only if absent, and the password is set every
# time so the stored secret and the server never drift apart.
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='qevik'" | grep -q 1 \
    || sudo -u postgres psql -qc "CREATE ROLE qevik LOGIN CREATEDB" >/dev/null
sudo -u postgres psql -qc "ALTER ROLE qevik WITH PASSWORD '${PW}'" >/dev/null
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='qevik'" | grep -q 1 \
    || sudo -u postgres psql -qc "CREATE DATABASE qevik OWNER qevik" >/dev/null
echo "role and database ready; postgres on loopback"

say "application configuration"
printf 'ATLAS_DATABASE_URL=postgresql+psycopg://qevik:%s@127.0.0.1:5432/qevik\n' "$PW" > "$ENV_FILE"
chown "${APP_USER}:${APP_USER}" "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "wrote ${ENV_FILE} (0600, ${APP_USER}); password not printed"

say "schema"
# The environment comes from systemd's own EnvironmentFile parser, not from a
# shell: a generated database password contains arbitrary bytes, and `source`
# would either break on them or alter them silently.
systemd-run --wait --collect --pipe --quiet \
  --property=EnvironmentFile="${ENV_FILE}" \
  --property=User="${APP_USER}" --property=Group="${APP_USER}" \
  --property=WorkingDirectory="${APP}" \
  --setenv=PYTHONPATH="${APP}/packages/kernel" \
  "${APP}/.venv/bin/python" -c '
from atlas_kernel.db import init_db
init_db(); init_db()   # twice: idempotency is half the contract
print("schema initialised, and idempotent on re-run")
'

say "service"
# Managed rather than nohup-ed: "run my system" means it survives a reboot and
# returns after a crash, and a backgrounded process does neither.
if [ -f "${APP}/infra/qevik-api.service" ]; then
    install -m 0644 "${APP}/infra/qevik-api.service" /etc/systemd/system/qevik-api.service
    systemctl daemon-reload
    systemctl enable --now qevik-api >/dev/null 2>&1 || systemctl restart qevik-api
    for _ in $(seq 1 30); do
        curl -sf -m 2 http://127.0.0.1:8080/health >/dev/null 2>&1 && break
        sleep 1
    done
    echo "qevik-api: $(systemctl is-active qevik-api), boot: $(systemctl is-enabled qevik-api), health: $(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health)"
fi

say "firewall (§28)"
# Order matters. Allowing SSH before enabling is the difference between a
# firewall and a lockout, and this box is reachable only over SSH.
ufw allow 22/tcp >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true
ufw status | head -6

say "done"
echo "Qevik installed at ${APP}, owned by ${APP_USER}."
echo "API on 127.0.0.1:8080 (loopback only — no auth layer yet)."
echo "Reach it from a laptop with:  ssh -N -L 8080:127.0.0.1:8080 root@HOST"
echo
echo "Run the suite:"
echo "  systemd-run --wait --pipe --property=EnvironmentFile=${ENV_FILE} \\"
echo "    --property=User=${APP_USER} --property=WorkingDirectory=${APP} \\"
echo "    ${APP}/.venv/bin/python -m pytest packages/kernel/tests -q"
