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

if ! grep -qE '^https://(2\.28\.62\.83|127\.0\.0\.1):8443 \{' "$CADDYFILE"; then
    echo "no :8443 block found — the file changed since this was written" >&2
    exit 1
fi

cp -a "$CADDYFILE" "$BACKUP"
echo "backed up to $BACKUP"

# Two changes, and the second is the one that actually does the work.
#
# The site address is what Caddy matches a request against — its Host header and
# SNI — not what it binds. Rewriting it to 127.0.0.1 alone leaves the listener on
# *:8443, reachable from every interface, which is precisely what this script
# exists to stop. `bind` is the directive that chooses the interface.
sed -i 's|^https://2\.28\.62\.83:8443 {|https://127.0.0.1:8443 {|' "$CADDYFILE"

if ! awk '/^https:\/\/127\.0\.0\.1:8443 \{/,/^}/' "$CADDYFILE" | grep -q 'bind 127.0.0.1'; then
    sed -i '/^https:\/\/127\.0\.0\.1:8443 {/a\\tbind 127.0.0.1' "$CADDYFILE"
fi

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

listener=$(ss -lntH "sport = :8443" | awk '{print $4}')
echo "  listener  : ${listener:-none}"
case "$listener" in
    127.0.0.1:8443) echo "            bound to loopback only" ;;
    *)              echo "            NOT loopback-only — restore $BACKUP" >&2; exit 1 ;;
esac

printf '  loopback  : '; curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1:8443/health
printf '  app.qevik : '; curl -s  -o /dev/null -w '%{http_code}\n' https://app.qevik.ai/health

echo "  ufw       :"; ufw status | grep -E '^(22|80|443|8443)/tcp' | sed 's/^/            /'

echo
echo "Now confirm from OUTSIDE the server that :8443 no longer answers:"
echo "  curl -sk --max-time 10 https://2.28.62.83:8443/health   # expect a timeout"
echo "and that the tunnel does:"
echo "  ssh -i ~/.ssh/naml_hetzner -L 8443:127.0.0.1:8443 -N root@2.28.62.83 &"
echo "  curl -sk https://127.0.0.1:8443/health                  # expect 200"
