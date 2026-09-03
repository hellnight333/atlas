#!/usr/bin/env bash
# Recover qevik-core-01 after the userspace-exhaustion incident, and install the
# limits that stop it recurring.
#
# Run this on the server as root, as early as possible after a reboot:
#
#     bash infra/recover_qevik_server.sh
#
# Idempotent. Safe to run twice, and safe to run on a healthy host.
#
# ---------------------------------------------------------------------------
# If SSH still does not answer after a power cycle
# ---------------------------------------------------------------------------
#
# The signature to check first, from a laptop:
#
#     ping HOST                 # answers  -> the kernel is alive
#     nc -z HOST 22 && nc -z HOST 9999
#
# If 22 completes and 9999 refuses, you are talking to the real host: the kernel
# holds the listening socket and completes handshakes whether or not any process
# is left to accept them. That is userspace exhaustion, not a network fault, and
# no amount of waiting fixes it.
#
# If a power cycle does not clear it, something is re-exhausting the box during
# boot. Use Hetzner's **Rescue System** (Robot -> Rescue -> activate, then
# reset), which boots a network image with the disk mountable, and disable the
# timers before the installed system comes up again:
#
#     mount /dev/sda1 /mnt        # confirm the device in Robot first
#     chroot /mnt systemctl disable qevik-market-scan.timer qevik-backup.timer
#     # then look for the actual cause:
#     journalctl -D /mnt/var/log/journal -b -1 -p err --no-pager | tail -50
#     grep -ci "out of memory\|oom-kill" /mnt/var/log/syslog
#
# Re-enable the timers once the cause is understood. Leaving them off is a
# workaround, not a fix, and a silent one if nobody writes it down.

set -euo pipefail

REPO="${QEVIK_REPO:-/opt/qevik/atlas}"
INSTALLER="$REPO/infra/install_qevik_infra.sh"

say() { printf '\n== %s\n' "$*"; }

say "1. What is running now"
uptime
free -m | sed -n '1,3p'
printf 'processes: %s\n' "$(ps -e --no-headers | wc -l)"
printf 'browsers:  %s\n' "$(pgrep -c -f 'chrom|headless_shell|playwright' 2>/dev/null || echo 0)"
printf 'stray servers: %s\n' "$(pgrep -c -f 'http.server' 2>/dev/null || echo 0)"

say "2. Reaping anything the last run left behind"
# Orphans from an interrupted end-to-end run. Matched narrowly on purpose: a
# broad pkill on a host that also runs PostgreSQL is a worse outage than the one
# being cleaned up.
for pattern in 'headless_shell' 'chrome --type=' 'playwright' 'python -m http.server'; do
	if pgrep -f "$pattern" >/dev/null 2>&1; then
		printf 'terminating: %s\n' "$pattern"
		pkill -TERM -f "$pattern" || true
	fi
done
sleep 3
for pattern in 'headless_shell' 'chrome --type=' 'playwright' 'python -m http.server'; do
	pgrep -f "$pattern" >/dev/null 2>&1 && pkill -KILL -f "$pattern" || true
done
printf 'browsers after reap: %s\n' "$(pgrep -c -f 'chrom|headless_shell|playwright' 2>/dev/null || echo 0)"

say "3. Installing the resource limits"
# Delegated (D-S6). This script is incident response; the limits, the directory
# layout and the enablement rules are one implementation, in
# infra/install_qevik_infra.sh, so a recovery cannot install a different set from
# a provisioning run. Two copies of that logic is how a host ends up with the
# slice but not the drop-in.
if [[ -x "$INSTALLER" ]]; then
	"$INSTALLER" || echo "WARNING: $INSTALLER did not complete" >&2
else
	echo "WARNING: $INSTALLER not found — sync the repo first" >&2
fi

say "4. Restarting the control plane"
systemctl restart qevik-api
sleep 5
for unit in qevik-api postgresql caddy; do
	printf '  %-14s %s\n' "$unit" "$(systemctl is-active "$unit" 2>&1)"
done

say "5. Verifying it answers"
curl -fsS -m 10 http://127.0.0.1:8080/health && echo || echo "  API DID NOT ANSWER"
curl -fsS -m 10 -o /dev/null -w '  site host: %{http_code}\n' http://127.0.0.1/ || echo "  site host did not answer"

say "6. Effective limits"
systemctl show qevik-jobs.slice -p MemoryMax -p TasksMax -p CPUQuotaPerSecUSec 2>/dev/null || true
systemctl show qevik-api -p MemoryMax -p TasksMax 2>/dev/null || true

say "7. Baseline after recovery"
free -m | sed -n '2p'
printf 'processes: %s\n' "$(ps -e --no-headers | wc -l)"
df -h / | tail -1

cat <<'NOTE'

Before running the end-to-end suite again:
  - keep QEVIK_MAX_BROWSERS at 2 (the default)
  - run `pytest -m "not e2e"` first; only the e2e set opens browsers
  - watch `free -m` and the browser count during the run
NOTE
