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
Latest report:
- 461 tests passing.
- 64 Gmail/credential/YouTube tests included in the passing set.
- Full suite is NOT green.
- PostgreSQL was unavailable on port 5432.
- 20 failures + 87 collection errors were attributed to PostgreSQL availability.

Do not call the full suite green until PostgreSQL is running and the complete suite passes.

## Google credentials
Desktop/installed OAuth client.
Local path:
`~/.qevik/credentials/google_client_secret.json`
Permissions: `600`
First scope:
`https://www.googleapis.com/auth/gmail.send`
Google app remains in Testing.

## Immediate priorities
1. Restore PostgreSQL and run the complete test suite.
2. Decide niche + geography + offer.
3. Run a small, manually approved Opportunity Factory pilot.
4. Set up OpenClaw on a dedicated P520 operator machine.
5. Keep project documentation in Git.
6. Keep broad Atlas → Qevik internal refactoring deferred.

## Deferred
- Broad package/schema/database rename.
- High-volume autonomous prospecting.
- Adding every Google API scope at once.
- Giving agents unrestricted access to personal browser accounts.
