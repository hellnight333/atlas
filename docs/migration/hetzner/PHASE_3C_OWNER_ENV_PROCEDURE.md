# STOP GATE 3-C — the owner's procedure for the environment files

**This is a procedure for you to run on `qevik-prod-01`. The agent does not run
it, does not see any value, and must never be sent one** — not in chat, not in a
file, not in a task. Everything below deals in *names*, *paths*, *modes* and
*presence*. No value, and no derived form of one — no hash, no length (owner's instruction, 2026-09-04).

Prerequisites, all satisfied at Phase 3 completion (`8c2685e`): the `qevik`
account exists (uid 999, `nologin`), `/opt/qevik` is `root:root 0755`, and access
is key-only. Phase 4 has not begun — nothing on the host reads these files yet,
which is exactly why this is a safe moment to write them.

---

## 1. The files

Five files. `backup.env` already exists from the off-host backup work and is not
touched here.

| Path | Owner | Mode | Variable names — **names only, never values** |
|---|---|---|---|
| `/opt/qevik/atlas.env` | `root:root` | `0600` | `ATLAS_DATABASE_URL`, `QEVIK_DASHSCOPE_API_KEY`, `QEVIK_DASHSCOPE_BASE_URL`, `QEVIK_ADMIN_PASSWORD`, `QEVIK_SITES_BASE_URL`, `QEVIK_LEDGER`, `QEVIK_REPORTS_STORE` |
| `/opt/qevik/control.env` | `qevik:qevik` | `0600` | `QEVIK_VAULT_MASTER_KEY`, `QEVIK_CLAIMS_DSN`, `QEVIK_REQUIRE_ATOMIC_CLAIMS` |
| `/opt/qevik/worker.env` | `qevik:qevik` | `0600` | `QEVIK_CLAIMS_DSN`, `QEVIK_REQUIRE_ATOMIC_CLAIMS` |
| `/opt/qevik/brave.env` | `root:root` | `0600` | `QEVIK_BRAVE_API_KEY` |
| `/opt/qevik/places.env` | `qevik:qevik` | `0600` | `QEVIK_GOOGLE_PLACES_API_KEY` |
| *(exists)* `/opt/qevik/backup.env` | `root:root` | `0600` | `RESTIC_PASSWORD` — **do not touch** |

`cloudflare.env` must **not** be created: nothing uses it, and the `qevik-api`
drop-in references it only with a leading `-` (optional).

**Three of these values are configuration, not secrets**, and are stated here so
you do not have to guess:

- `QEVIK_LEDGER=postgres` — PROVED from the old host's journal ("watching the postgres ledger").
- `QEVIK_SITES_BASE_URL=https://sites.qevik.ai` — the public base; the old host's origin-IP form is retired (WS-1 moved the code defaults to this name).
- `QEVIK_REQUIRE_ATOMIC_CLAIMS` — the flag the old host sets; copy its value from the old host (§5).

---

## 2. Four decisions only you can make

| # | Decision | Default if you say "your call" |
|---|---|---|
| **O4 / U9** | `QEVIK_VAULT_MASTER_KEY`: reuse the old host's value, or generate a fresh one and start the vault empty | **Generate a fresh one.** The old host's `vault.json` is 2 bytes — effectively empty — so nothing is lost. Reuse only if you know a real credential was sealed there; a wrong choice surfaces in Phase 7 as a failed "vault sealed" component, not as silent loss |
| **O7 / D-K** | `QEVIK_ADMIN_PASSWORD`: a new value, or the old one | **New.** The operator accounts themselves migrate with the database rows; this variable only bootstraps |
| **O5 / D-J** | DashScope and Brave keys: rotate, or re-enter the same values | **Rotate.** Every credential that lived on the old host is treated as exposed; the old keys stay valid until Phase 11 so nothing breaks meanwhile |
| **O6 / SR-5** | Google Places | **A new key is mandatory, not optional.** The current one is IP-restricted to the old host and will fail here. Create it restricted to `91.107.244.253` (and the IPv6 `2a01:4f8:1c1b:1dbe::1` if you use AAAA) **and** to the Places API |

---

## 3. DSN sequencing (§8 of the Phase 3 plan) — pick (a) or (b)

`ATLAS_DATABASE_URL` and `QEVIK_CLAIMS_DSN` embed the password of a PostgreSQL
role that **does not exist yet**: Phase 3 created no database (that is Phase 4).

- **(a) recommended — choose the password now.** Generate it in your password
  manager, write all five files now, and in Phase 4 the role is created and given
  *that* password (`\password qevik`, typed by you). One pass, one place.
  **The character set is unconstrained**: the enablement stage removed shell
  parsing entirely, so `$`, backticks, quotes, spaces and semicolons are all fine.
- **(b) two passes.** Write `brave.env` and `places.env` now; write
  `atlas.env`, `control.env` and `worker.env` in Phase 4, immediately after the
  role exists. Choose this if you would rather not hold an unused password.

Both DSNs must carry the **same** role and password. Their shape (no secret here):

```
ATLAS_DATABASE_URL=postgresql+psycopg://qevik:<password>@127.0.0.1:5432/qevik
QEVIK_CLAIMS_DSN=postgresql://qevik:<password>@127.0.0.1:5432/qevik
```

> If the password contains `@`, `/`, `:`, `#` or `?`, **percent-encode it inside
> the URL** (`@` → `%40`, `/` → `%2F`, `:` → `%3A`, `#` → `%23`, `?` → `%3F`).
> That is a URL rule, not a shell rule — the parser that splits the DSN is a URL
> parser. Everything else may be literal. If you would rather avoid encoding
> altogether, ask your password manager for a long alphanumeric string; that is a
> convenience, not a security compromise, at 32+ characters.

---

## 4. How to write them — the no-shell model, in your own SSH session

Two rules make this safe:

1. **A quoted heredoc.** `<<'EOF'` with the delimiter in single quotes means the
   shell you are typing into performs **no** expansion: `$`, backticks and
   quotes reach the file exactly as typed.
2. **systemd, not a shell, reads the file later.** The units and the deploy use
   `EnvironmentFile=`, so nothing re-interprets the value at runtime either.

```sh
ssh qevik-prod-01                 # your own session; the agent is not involved
umask 077                          # anything created below is 0600 from birth

cat > /opt/qevik/atlas.env <<'EOF'
ATLAS_DATABASE_URL=postgresql+psycopg://qevik:REPLACE@127.0.0.1:5432/qevik
QEVIK_DASHSCOPE_API_KEY=REPLACE
QEVIK_DASHSCOPE_BASE_URL=REPLACE_FROM_OLD_HOST
QEVIK_ADMIN_PASSWORD=REPLACE
QEVIK_SITES_BASE_URL=https://sites.qevik.ai
QEVIK_LEDGER=postgres
QEVIK_REPORTS_STORE=REPLACE_FROM_OLD_HOST
EOF
chown root:root /opt/qevik/atlas.env && chmod 600 /opt/qevik/atlas.env

cat > /opt/qevik/control.env <<'EOF'
QEVIK_VAULT_MASTER_KEY=REPLACE
QEVIK_CLAIMS_DSN=postgresql://qevik:REPLACE@127.0.0.1:5432/qevik
QEVIK_REQUIRE_ATOMIC_CLAIMS=REPLACE_FROM_OLD_HOST
EOF
chown qevik:qevik /opt/qevik/control.env && chmod 600 /opt/qevik/control.env

cat > /opt/qevik/worker.env <<'EOF'
QEVIK_CLAIMS_DSN=postgresql://qevik:REPLACE@127.0.0.1:5432/qevik
QEVIK_REQUIRE_ATOMIC_CLAIMS=REPLACE_FROM_OLD_HOST
EOF
chown qevik:qevik /opt/qevik/worker.env && chmod 600 /opt/qevik/worker.env

cat > /opt/qevik/brave.env <<'EOF'
QEVIK_BRAVE_API_KEY=REPLACE
EOF
chown root:root /opt/qevik/brave.env && chmod 600 /opt/qevik/brave.env

cat > /opt/qevik/places.env <<'EOF'
QEVIK_GOOGLE_PLACES_API_KEY=REPLACE_NEW_KEY_RESTRICTED_TO_THIS_HOST
EOF
chown qevik:qevik /opt/qevik/places.env && chmod 600 /opt/qevik/places.env
```

**Four things that quietly corrupt a value** — the validator in §6 catches all four:

- a trailing space after the value (systemd keeps it);
- a carriage return, if the value came through a Windows clipboard (it becomes part of the value);
- outer quotes: systemd strips a *matching* pair of leading and trailing `'` or `"`, so a value that genuinely begins and ends with the same quote character loses them — if that happens, wrap the whole value in one extra pair;
- a line break inside a value from a wrapped paste — each variable must be exactly one line.

---

## 4a. Filling the values — the exact commands (2026-09-04)

The five files now exist on the host as **scaffolds**: `root:root`/`qevik:qevik`
as documented, `0600`, holding the non-secret configuration, the variable names
and these instructions as comments. No secret has ever been in them.

| File | Active now | Still to add |
|---|---|---|
| `atlas.env` | `QEVIK_LEDGER`, `QEVIK_SITES_BASE_URL` | `ATLAS_DATABASE_URL`, `QEVIK_DASHSCOPE_API_KEY`, `QEVIK_DASHSCOPE_BASE_URL`, `QEVIK_ADMIN_PASSWORD`, `QEVIK_REPORTS_STORE` |
| `control.env` | — | `QEVIK_VAULT_MASTER_KEY`, `QEVIK_CLAIMS_DSN`, `QEVIK_REQUIRE_ATOMIC_CLAIMS` |
| `worker.env` | — | `QEVIK_CLAIMS_DSN`, `QEVIK_REQUIRE_ATOMIC_CLAIMS` |
| `brave.env` | — | `QEVIK_BRAVE_API_KEY` |
| `places.env` | — | `QEVIK_GOOGLE_PLACES_API_KEY` |

The placeholders are **commented out** on purpose: an uncommented `KEY=` is a
real assignment of the empty string, and systemd would hand that to a service as
a value. A missing variable fails loudly; an empty one fails obscurely.

### Why `read -rs` rather than an editor or a heredoc

`read -rs` echoes nothing to the screen, `-r` stops backslashes being eaten, and
the value reaches `printf` as one argument — so it never appears in your shell
history, never on a command line, and is never expanded. It is the same pattern
`qevik-backup-set-password` already uses on this host.

```sh
ssh qevik-prod-01          # your own session
umask 077
```

**1 — the database password, written into all three DSNs at once.** One prompt,
three files: this is why the two `QEVIK_CLAIMS_DSN` lines cannot drift apart, and
it removes the need to compare the two files afterwards at all.

```sh
read -rsp 'qevik DB password: ' P; echo
printf 'ATLAS_DATABASE_URL=postgresql+psycopg://qevik:%s@127.0.0.1:5432/qevik\n' "$P" >> /opt/qevik/atlas.env
printf 'QEVIK_CLAIMS_DSN=postgresql://qevik:%s@127.0.0.1:5432/qevik\n'          "$P" >> /opt/qevik/control.env
printf 'QEVIK_CLAIMS_DSN=postgresql://qevik:%s@127.0.0.1:5432/qevik\n'          "$P" >> /opt/qevik/worker.env
unset P
```

> Percent-encode `@ / : # ?` **inside the password** before typing it here — that
> is a URL rule, not a shell rule (§3). Keep the same password in your manager:
> Phase 4 applies it to the role with `\password qevik`, typed by you.

**2 — the remaining single-value secrets.** One line each; run only the ones you
are ready for.

```sh
read -rsp 'DashScope API key: ' V;   echo; printf 'QEVIK_DASHSCOPE_API_KEY=%s\n' "$V" >> /opt/qevik/atlas.env;   unset V
read -rsp 'admin password: ' V;      echo; printf 'QEVIK_ADMIN_PASSWORD=%s\n'    "$V" >> /opt/qevik/atlas.env;   unset V
read -rsp 'vault master key: ' V;    echo; printf 'QEVIK_VAULT_MASTER_KEY=%s\n'  "$V" >> /opt/qevik/control.env; unset V
read -rsp 'Brave API key: ' V;       echo; printf 'QEVIK_BRAVE_API_KEY=%s\n'     "$V" >> /opt/qevik/brave.env;   unset V
read -rsp 'NEW Places API key: ' V;  echo; printf 'QEVIK_GOOGLE_PLACES_API_KEY=%s\n' "$V" >> /opt/qevik/places.env; unset V
```

**3 — the three non-secret values copied from the old host** (§5). These are
configuration, so a plain `printf` is fine — substitute what the old host says:

```sh
printf 'QEVIK_DASHSCOPE_BASE_URL=%s\n'    'https://…'   >> /opt/qevik/atlas.env
printf 'QEVIK_REPORTS_STORE=%s\n'         '…'           >> /opt/qevik/atlas.env
printf 'QEVIK_REQUIRE_ATOMIC_CLAIMS=%s\n' '…'           >> /opt/qevik/control.env
printf 'QEVIK_REQUIRE_ATOMIC_CLAIMS=%s\n' '…'           >> /opt/qevik/worker.env
```

**4 — restore the ownership the appends may have changed** (appending as root
leaves the owner alone, but this is cheap and idempotent):

```sh
chown root:root /opt/qevik/atlas.env /opt/qevik/brave.env
chown qevik:qevik /opt/qevik/control.env /opt/qevik/worker.env /opt/qevik/places.env
chmod 600 /opt/qevik/*.env
```

**Mistyped something?** Append the line again — the last assignment wins, proved
on this host on 2026-09-04 with invented values. To start a file over, re-create
the scaffold from this document and repeat.

**Generating a value rather than pasting one** (vault master key, admin password,
DB password), if you would rather not use a manager for these:

```sh
openssl rand -base64 32        # prints to your screen only; store it before use
```

---

## 5. The three values to copy from the old host

`QEVIK_DASHSCOPE_BASE_URL`, `QEVIK_REPORTS_STORE` and
`QEVIK_REQUIRE_ATOMIC_CLAIMS` are configuration whose values the agent has never
read (U10). Read them yourself, in your own session — this is a read on the old
host, which AR-4 permits:

```sh
ssh -i ~/.ssh/naml_hetzner root@2.28.62.83 \
  "grep -E '^(QEVIK_DASHSCOPE_BASE_URL|QEVIK_REPORTS_STORE)=' /opt/qevik/atlas.env; \
   grep -E '^QEVIK_REQUIRE_ATOMIC_CLAIMS=' /opt/qevik/control.env"
```

Do not paste the output anywhere; type the values into the new host's files.

---

## 6. Validation — proves presence, ownership, mode and parseability, prints no value

Run all four. The last asks **systemd's own parser** to read the files — the
same parser the units and the deploy use — and reports **presence and
non-emptiness** per variable: no value, and no derived form of one.

```sh
# 1. the files: existence, owner, mode. Nothing else may live in /opt/qevik.
stat -c '%n %U:%G %a' /opt/qevik/*.env

# 2. the names, and nothing but the names
for f in /opt/qevik/*.env; do
  echo "== $f"; grep -v '^[[:space:]]*#' "$f" | grep '=' | cut -d= -f1 | sed 's/^/   /'
done

# 3. hygiene: no CR, no trailing space, no empty value, one line per variable
for f in /opt/qevik/*.env; do
  printf '%s: CR=%s trailing-space=%s empty-value=%s\n' "$f" \
    "$(grep -c $'\r' "$f")" \
    "$(grep -cE '[[:space:]]+$' "$f")" \
    "$(grep -cE '^[A-Za-z_][A-Za-z0-9_]*=$' "$f")"
done   # every count must be 0

# 4. systemd parses it, and each variable arrives non-empty — presence only
# (verified on this host on 2026-09-04 with an invented value containing a
#  space, a `$` and a quote: it reported the variable as present and printed
#  nothing of it)
systemd-run --wait --collect --pipe --quiet \
  --property=EnvironmentFile=/opt/qevik/atlas.env \
  /usr/bin/python3 -c 'import os, sys
for k in sys.argv[1:]:
    v = os.environ.get(k)
    if v is None:
        print(k, "MISSING")
    else:
        print(k, "present, non-empty" if v else "PRESENT BUT EMPTY")' \
  ATLAS_DATABASE_URL QEVIK_DASHSCOPE_API_KEY QEVIK_DASHSCOPE_BASE_URL \
  QEVIK_ADMIN_PASSWORD QEVIK_SITES_BASE_URL QEVIK_LEDGER QEVIK_REPORTS_STORE
```

Repeat step 4 for `control.env` (`QEVIK_VAULT_MASTER_KEY QEVIK_CLAIMS_DSN
QEVIK_REQUIRE_ATOMIC_CLAIMS`), `worker.env` and the two key files.

**The comparison that used to need a digest** — `QEVIK_CLAIMS_DSN` identical in
`control.env` and `worker.env` — is handled structurally instead: §4a step 1
writes both from one prompt, so they cannot diverge. That divergence is the kind
of bug that otherwise stays invisible until workers fail to claim missions in
Phase 7.

Nothing derived from a value is produced, printed or recorded.

---

## 7. Rollback / removal

Nothing consumes these files until Phase 4, so removal is free and complete:

```sh
shred -u /opt/qevik/atlas.env /opt/qevik/control.env /opt/qevik/worker.env \
         /opt/qevik/brave.env /opt/qevik/places.env       # overwrite, then unlink
stat -c '%n %U:%G %a' /opt/qevik/*.env                     # only backup.env remains
```

To correct a single value, rewrite that file with the same quoted heredoc — do
not edit in place with `sed`, which would need the value on a command line.
**Never touch `/opt/qevik/backup.env`**: it holds the restic repository password
and the nightly off-host backup depends on it.

If a value is ever exposed in a terminal that is logged or shared, treat it as
compromised: rotate at the provider, rewrite the file, and tell the agent only
that a rotation happened.

---

## 8. What happens after you confirm

Confirm to the agent that 3-C is complete — **without any value**. The agent will
then verify names and modes only (`stat`, `cut -d= -f1`) and record that. That
verification is the last Phase 3 action.

**STOP GATE 3-D is separate and requires its own explicit GO.** Phase 4 — the
Caddy install, PostgreSQL, the venv, Playwright, the unit installer, the deploy —
begins on that GO and not before.
