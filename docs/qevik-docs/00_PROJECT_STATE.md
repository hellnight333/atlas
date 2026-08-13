# Qevik — Current Project State

**Last consolidated: 2026-08-13**

## Current identity
Working product/brand: **Qevik**.

## Current technical milestone
Google OAuth/Gmail integration has reached a real end-to-end test.

Reported by Claude:
- A real Gmail message was sent through the complete M014 path.
- Approval gate, fingerprint verification, suppression and cooldown executed.
- Duplicate outreach was blocked by a 90-day cooldown.
- Editing a proposal after approval was blocked by fingerprint mismatch.
- Suppressed addresses were blocked.
- Secrets were kept outside the repository and logging was hardened.

## Test state
**Full suite is GREEN as of 2026-08-13.**
- 1044 passed, 0 failed. Coverage 92.46% (gate is 90%).
- Verified twice; the second run shows 1040 passed + 4 skipped, which are
  demo-installer tests that skip once demos exist ("already installed by an
  earlier run"). Benign and expected.
- ruff, tsc, oxlint, rustfmt and clippy all clean.

PostgreSQL was not actually down. The server was running; the role `atlas` and
database `atlas` did not exist, so every connection failed with
`role "atlas" does not exist`. Both were created.

Creating them then exposed a real bug: `init_db()` could not build the schema
from nothing. An `ALTER TABLE atlas_scene_renders` ran before that table's
`CREATE TABLE`, and because the whole of `init_db()` is one transaction, the
failure rolled everything back and left zero tables. Invisible on any database
that already had the table — which was every database anyone had used. Fixed by
moving the ALTER after the CREATE.

## Google credentials
Desktop/installed OAuth client.
Local path:
`~/.qevik/credentials/google_client_secret.json`
Permissions: `600`
First scope:
`https://www.googleapis.com/auth/gmail.send`
Google app remains in Testing.

## Immediate priorities
1. ~~Restore PostgreSQL and run the complete test suite.~~ **Done 2026-08-13.**
2. Decide niche + geography + offer. **← now the blocker**
3. Run a small, manually approved Opportunity Factory pilot.
4. Set up OpenClaw on a dedicated P520 operator machine.
5. Keep project documentation in Git.
6. Keep broad Atlas → Qevik internal refactoring deferred.

## Deferred
- Broad package/schema/database rename.
- High-volume autonomous prospecting.
- Adding every Google API scope at once.
- Giving agents unrestricted access to personal browser accounts.
