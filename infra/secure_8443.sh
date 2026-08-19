#!/usr/bin/env bash
#
# PROPOSAL — NOT YET APPLIED. Requires the operator's approval before running.
#
# What :8443 is today
# -------------------
# Caddy listens on *:8443 and serves the full operator control plane — the
# console, /auth/*, /control/*, /health — over a self-signed certificate, open
# to the entire internet. It exists as a way back in if DNS or Cloudflare
# breaks, which was the right call when no domain resolved to this host.
#
# Why it is no longer worth its exposure
# --------------------------------------
# app.qevik.ai now serves exactly the same routes behind a real certificate,
# verified: /health 200, /control/ 401, /auth/login 405 (POST-only). Nothing on
# the host depends on :8443 — no unit, timer, script or test references it.
# In fourteen days of Caddy's journal, exactly one external address reached it:
# 198.74.59.236, a scanner. So the port's whole traffic is hostile.
#
# What this changes
# -----------------
# The fallback door is kept, and moved behind SSH. Caddy binds the listener to
# 127.0.0.1 instead of every interface, and ufw stops allowing 8443 inward.
# The operator reaches it through the SSH key they already hold:
#
#     ssh -i ~/.ssh/naml_hetzner -L 8443:127.0.0.1:8443 root@2.28.62.83
#     # then open https://127.0.0.1:8443
#
# This is strictly better than the current arrangement as a break-glass route:
# it survives DNS failure, Cloudflare misconfiguration and domain lapse exactly
# as before — those are the scenarios it exists for, and none of them affect
# SSH — while being unreachable to anyone without the key.
#
# What it does not change
# -----------------------
# Ports 22, 80 and 443 are untouched. No Cloudflare setting is read or written.
# The API stays on 127.0.0.1:8080 as it always has.
#
# Rollback
# --------
# Restore /etc/caddy/Caddyfile from the backup this script takes, then
# `ufw allow 8443/tcp` and `systemctl restart caddy`. Under a minute.
#
set -euo pipefail

CADDYFILE=/etc/caddy/Caddyfile
BACKUP="${CADDYFILE}.pre-8443-lockdown"

if [[ ! -f "$CADDYFILE" ]]; then
    echo "no Caddyfile at $CADDYFILE" >&2
    exit 1
fi

if ! grep -q '^https://2\.28\.62\.83:8443 {' "$CADDYFILE"; then
    echo "the public :8443 block is not present — already applied, or the file changed" >&2
    exit 1
fi

cp -a "$CADDYFILE" "$BACKUP"
echo "backed up to $BACKUP"

# One line. The block's contents are already correct; only its address is wrong.
sed -i 's|^https://2\.28\.62\.83:8443 {|https://127.0.0.1:8443 {|' "$CADDYFILE"

# Validate before restarting. A malformed Caddyfile has taken this server down
# once already, and `caddy reload` cannot be used here because the admin API is
# deliberately off — so a restart is the only path and it must not be blind.
caddy validate --config "$CADDYFILE" >/dev/null
echo "Caddyfile validates"

systemctl restart caddy
sleep 2
systemctl is-active --quiet caddy || { echo "caddy failed to start — restore $BACKUP" >&2; exit 1; }

ufw delete allow 8443/tcp >/dev/null 2>&1 || true
echo "ufw rule removed"

echo
echo "--- verification ---"
ss -lntp | grep ':8443' || echo "  nothing listening on 8443 (unexpected)"
printf '  loopback  : '; curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1:8443/health
printf '  app.qevik : '; curl -s  -o /dev/null -w '%{http_code}\n' https://app.qevik.ai/health
echo
echo "Now confirm from OUTSIDE the server that :8443 no longer answers:"
echo "  curl -sk --max-time 10 https://2.28.62.83:8443/health   # expect a timeout"
