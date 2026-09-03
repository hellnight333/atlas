# PHASE_2_OWNER_CONSOLE_ACTIONS — rebuild server 164307556 into `qevik-prod-01`

**Decision basis:** D-R-1 (owner, 2026-09-03) — reuse the existing Hetzner server, clean console
rebuild, Ubuntu 26.04, `qevik_prod` key only, `devloop_01` must not remain authorised, same id and
IPs, **no** new/replacement server or extra compute. Old production host untouched.
**Status:** presented for approval. **Nothing here has been executed.** Every step below waits for
the owner's explicit GO; the console steps are the owner's own hands.
**Tags:** PROVED · OBSERVED-3P (docs.hetzner.com FAQ, read 2026-09-03 via devloop-01 because
docs.hetzner.com is unreachable from the Mac) · INFERRED · UNKNOWN.

## 0. One correction to the assessment before anything is clicked

`DEVLOOP01_SUITABILITY_ASSESSMENT.md` §9/§10 said the rebuild dialog could select the `qevik_prod`
key. **That is wrong.** Hetzner's FAQ (OBSERVED-3P): *"Case 2: Server1 was created with selecting
your SSH key key1: After rebuild, the key key1 will be injected into server1 on first boot using the
cloud-init mechanism."* The console rebuild takes **only an image**; it re-injects the key chosen at
creation — i.e. **`devloop_01`** — and there is no user-data or key picker. Whether deleting the
`devloop_01` key from the project *before* the rebuild changes that behaviour is UNKNOWN and must not
be gambled on (it could leave the rebuilt host with no key and no mailed password).

Therefore the key swap happens **on the freshly rebuilt host, as the first thing after rebuild, under
the AR-2 two-session procedure** (step 6). The `devloop_01` key is present on the clean image for the
minutes between first boot and step 6; its private key lives only on the same Mac as `qevik_prod`,
so this is a sequencing detail, not an exposure. The owner's requirement — *"the existing
`devloop_01` key must not **remain** authorised on the rebuilt production target"* — is met by
step 6 and verified in step 7. If the owner prefers the key to never be injected at all, the only
alternative is the "Case 1" path (no key → mailed root password → password login → then key
install), which creates a credential and is worse; **not recommended**.

## 1. Pre-flight facts recorded now (read-only, PROVED 2026-09-03)

| Item | Value |
|---|---|
| Server | id **164307556**, name `qevik-devloop-01`, nbg1-dc3, 8 vCPU / 15.2 GiB / 305 GB |
| IPv4 / IPv6 | `91.107.244.253` / `2a01:4f8:1c1b:1dbe::1/64` — to be **kept** (rebuild reimages the same server: FAQ "reset the server to its delivery state … select the server and then Rebuild", OBSERVED-3P) |
| Key currently injected | `devloop_01` ED25519 `SHA256:0ony14dB7vfo4y0xVmaDwHIonDE2khTODM2YiE76ues` |
| **Pre-rebuild host keys** (must **change** after the rebuild — that is how the agent proves the rebuild happened) | ED25519 `SHA256:3jMtwUlaGN3zlLRgTp0NDjeWO5vIUZ7YWmztwgc0tD4` · ECDSA `SHA256:wHfDYuaTGWUFbUCNJ4gOzW8F/z7gcvUpa+AT8hi76PI` · RSA `SHA256:ZwgL68n0G3h2gaFiSdS335uFIEGZXc1tSkNUl8mHjQw` (3 entries in the Mac's `known_hosts`) |
| `qevik_prod` key | **does not exist yet** on the Mac (`~/.ssh` holds only `devloop_01`, `devloop_01.pub` for this host) |
| Data on the server | none worth keeping (assessment §5) |

## 2. The sequence — who does what, and where the GO points are

Legend: **OWNER** = your hands in the console or on the Mac · **AGENT** = me, over SSH, only after
the GO named in that row · ⏸ = stop and report before continuing.

### Step 0 — `qevik_prod` key pair (OWNER, on the Mac; or AGENT on an explicit GO)

The standing rule is that I never create credentials on my own. Either run this yourself:

```
ssh-keygen -t ed25519 -a 64 -f ~/.ssh/qevik_prod -C qevik_prod
```

(choose the passphrase; it is never shared with me), then `cat ~/.ssh/qevik_prod.pub` — or tell me
"generate qevik_prod" and I run exactly that command with an empty passphrase unless you specify
one in the GO. Add to `~/.ssh/config` (I can write this on GO; it contains no secret):

```
Host qevik-prod-01
    HostName 91.107.244.253
    User root
    IdentityFile ~/.ssh/qevik_prod
    IdentitiesOnly yes
```

### Step 1 — register the public key (OWNER, console)

Hetzner Cloud Console → project → **Security** → **SSH keys** → **Add SSH key** → paste the contents of
`~/.ssh/qevik_prod.pub` → name `qevik_prod`. Cost: none. Do **not** delete `devloop_01` from the
project yet (see §0).

While there, please read and tell me (no screenshots with secrets): the project's name, whether it
holds resources other than the two servers, and whether 2FA is on (U1, §2 of the Phase 1 report).

### Step 2 — rename (OWNER, console) — free, no reboot

**Servers** → `qevik-devloop-01` → top-left, click the server's **name** → `qevik-prod-01` → **OK**.
FAQ: "this will not change the hostname in your host's operating system" — the OS hostname is set in
step 8. Cost: none.

### Step 3 — record what the console shows (OWNER reads, tells me; AGENT records)

From the server page: **Type** (expected CPX42) and **price**; **Backups** tab state (on/off; any
existing backups); **Snapshots** (any?); **Firewalls** (any attached?); **Volumes** (expect none);
**Networking** → confirm `91.107.244.253` and the IPv6 `/64`. If anything differs from §1 ⏸.

### Step 4 — REBUILD (OWNER, console) — the destructive step; free; ~2 minutes

**Servers** → `qevik-prod-01` → **Rebuild** tab → image **Ubuntu 26.04** → **Rebuild server**.
The console warns that all data will be lost — that is intended (assessment §5: all disposable).

Immediately after: open the server's **Console** (the `>_` button, top right) and watch the first
boot. cloud-init normally prints a block `-----BEGIN SSH HOST KEY FINGERPRINTS-----` — if you can read
the ED25519 line, tell me the `SHA256:` value; if it scrolls past, that is fine (see step 5). You
will **not** receive a root password e-mail (server was key-created — FAQ case 2). Do not log in via
the web console; nothing is needed there.

⏸ Tell me "rebuild done".

### Step 5 — post-rebuild identity check (AGENT, read-only, needs GO "verify")

1. `ssh-keyscan` the IP: every host-key fingerprint must **differ** from the pre-rebuild values in §1
   (proves the reimage). If any is unchanged ⏸.
2. Remove the three stale `known_hosts` lines for `91.107.244.253` on the Mac and record the new
   ED25519 fingerprint (compared with your console reading, if you got one; otherwise
   trust-on-first-use, explicitly recorded as such).
3. First login **with `devloop_01`** (the only key Hetzner injected): read-only `os-release`,
   `hostnamectl`, `journalctl --list-boots` (expect exactly **one** boot), `df -h /` (expect ≈ 1.5 GB
   used), `cat /root/.ssh/authorized_keys | wc -l` (expect 1 = devloop_01), `sshd -T | grep -i
   passwordauth` (expect `yes` — Hetzner default), `ufw status` (inactive).
4. Write `evidence/phase-2/host-identity.txt` (no key material, fingerprints only).

### Step 6 — key swap under AR-2 (AGENT, needs GO "swap keys") — this is the only change to the host in Phase 2

Session **A** (devloop_01) stays open the whole time.
1. Append `qevik_prod.pub` to `/root/.ssh/authorized_keys` (mode 600 unchanged).
2. Open a **fresh** session **B**: `ssh -i ~/.ssh/qevik_prod -o IdentitiesOnly=yes root@91.107.244.253 hostname` — must succeed.
3. Rewrite `authorized_keys` to **exactly one line** = `qevik_prod.pub`.
4. Open a fresh session **C** with `qevik_prod` — must succeed; attempt with `devloop_01` — must be **refused** (`Permission denied (publickey)`).
5. Only then close A. Session timestamps A/B/C + the refusal go into `evidence/phase-2/`.

`PasswordAuthentication no`, `MaxAuthTries 3`, fail2ban, ufw, swap: **Phase 3** (same AR-2 discipline),
not here — Phase 2 changes nothing on the host except the key line. Hetzner's default already denies
root password login (`prohibit-password`) and no other user exists, so the host is key-only in
practice from first boot.

### Step 7 — retire `devloop_01` (OWNER)

Console → **Security** → **SSH keys** → delete `devloop_01`. On the Mac: delete `~/.ssh/devloop_01`
and `devloop_01.pub` (I can do the Mac part on GO). ADR-0011 note: the future DevLoop host gets its
own new key when it is created. After this, a future console rebuild of 164307556 would fall into
FAQ "case 1" (mailed root password) — acceptable; noted in the runbook.

### Step 8 — hostname + patches (AGENT, needs GO "upgrade") — optional in Phase 2, otherwise Phase 3

`hostnamectl set-hostname qevik-prod-01`; `apt full-upgrade -y`; reboot **this host only**;
confirm `reboot-required` absent and `hostname` = `qevik-prod-01`.

### Step 9 — image backups (OWNER, console) — first recurring cost change

**Servers** → `qevik-prod-01` → **Backups** → **Enable**. Cost: +20 % of the server price
(≈ €13.90/mo on CPX42, OBSERVED-3P). Enabling after the rebuild means the first backup is of the
clean image, not of the old state.

### Step 10 — Cloud Firewall (OWNER, console) — free

**Firewalls** → **Create Firewall** → name `qevik-prod-fw` → inbound rules: TCP 22 from any
(`0.0.0.0/0`, `::/0`), TCP 80 any, TCP 443 any, ICMP any; outbound: leave "allow all" → **Apply to** →
select `qevik-prod-01` → create. (D-D: no IP restriction on 22; `:8443` stays closed; Cloudflare-only
80/443 is Phase 10 hardening.) ⏸ Tell me "firewall attached" — I re-verify 22 open / 80, 443 closed
from the second vantage (U16: read-only `nc` from `qevik-core-01` — needs your one-time OK for that
read-only use of the old host — plus an external checker).

### Step 11 — Storage Box (OWNER, Robot/console) — second recurring cost

Hetzner **Storage Boxes** → order **BX11** (1 TB, €3.20/mo OBSERVED-3P), location Germany →
after delivery: **Sub-accounts** → create `qevik-prod-backup`, home directory its own folder, SFTP
enabled, SSH support enabled. The sub-account password/key goes **only** into the target's `/root`
in Phase 4 (never to me, chat or repo). Tell me the Storage Box hostname (not the credential).

### Step 12 — evidence + docs (AGENT)

`evidence/phase-2/` complete; `MASTER_MIGRATION_PLAN.md` Phase 2 → COMPLETE; DQ-014 status;
memory. Commit, no push. ⏸ **Phase 3 gate.**

## 3. What each step costs and how it is undone

| Step | Cost | Undo |
|---|---|---|
| 0–3 | none | delete key / rename back |
| 4 rebuild | none | rebuild again (nothing to restore) |
| 5–8 | none | `authorized_keys` edit is reversible while session A is open; reboot is a reboot |
| 9 backups | +≈ €13.90/mo | disable |
| 10 firewall | none | detach/delete |
| 11 Storage Box | +€3.20/mo | cancel |

Total recurring change after Phase 2: **+≈ €17.10/mo**. No server is created, replaced, resized or deleted.

## 4. Stop

Waiting for the owner's GO on step 0 (who generates `qevik_prod`) and confirmation that steps 1–4 will
be performed in the console. Until the GO for each agent step: no SSH change, no key change, no
reboot, no console action, no DNS, no data movement, no production contact.
