#!/usr/bin/env bash
# Put the customer sites on a real domain with real HTTPS.
#
#     bash enable_domain.sh sites.example.com
#
# Prerequisite, and the only part Qevik cannot do for itself: a DNS **A record**
# for that name pointing at this server's public IP. Certificate authorities do
# not issue for bare IP addresses, which is why everything is plain HTTP today —
# not an oversight, a constraint.
#
# Run it after the record resolves. Caddy obtains and renews the certificate on
# its own; there is no certbot, no cron entry and no renewal to forget.
set -euo pipefail

DOMAIN="${1:-}"
[[ -n "$DOMAIN" ]] || { echo "usage: enable_domain.sh <domain>" >&2; exit 2; }

IP="$(curl -fsS -4 https://api.ipify.org || echo unknown)"
RESOLVED="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)"

echo "domain   : $DOMAIN"
echo "this host: $IP"
echo "resolves : ${RESOLVED:-<nothing>}"

if [[ "$RESOLVED" != "$IP" ]]; then
	# Refusing rather than proceeding: Caddy would attempt an ACME challenge,
	# fail, and retry with backoff, and the site would serve nothing while the
	# logs filled with something that reads like a Caddy fault rather than a
	# missing DNS record.
	echo >&2
	echo "REFUSING: $DOMAIN does not resolve to this host yet." >&2
	echo "Add an A record  $DOMAIN -> $IP  and run this again once it propagates." >&2
	exit 1
fi

cat > /etc/caddy/sites.d/domain.caddy <<CADDY
# Customer sites, on a real certificate. Same document root and the same
# publish-then-promote layout as the IP host; only the address changed.
$DOMAIN {
	root * /srv/sites

	# A site directory holds versions/ and a current symlink; the live document
	# root is the symlink. This is the server-side half of publish-then-promote.
	@site_root path_regexp siteroot ^/([^/]+)/?\$
	rewrite @site_root /{re.siteroot.1}/current/

	file_server
	header X-Qevik-Host "sites"
	log { format console }
}
CADDY

caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
echo "waiting for the certificate…"
for _ in $(seq 1 30); do
	if curl -fsS -m 5 -o /dev/null "https://$DOMAIN/" 2>/dev/null; then
		echo "HTTPS is live: https://$DOMAIN/"
		break
	fi
	sleep 4
done

# The deployment target writes this into every page it publishes and verifies
# against it after promoting, so it has to change at the same time.
umask 077
grep -v '^QEVIK_SITES_BASE_URL=' /opt/qevik/atlas.env > /opt/qevik/atlas.env.new || true
echo "QEVIK_SITES_BASE_URL=https://$DOMAIN" >> /opt/qevik/atlas.env.new
mv /opt/qevik/atlas.env.new /opt/qevik/atlas.env
chmod 600 /opt/qevik/atlas.env
systemctl restart qevik-api

echo
echo "Done. New deployments publish to https://$DOMAIN/<slug>/"
echo "Existing demos keep working on the IP; re-run the pipeline to move them."
