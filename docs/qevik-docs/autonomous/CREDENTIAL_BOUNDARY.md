# One credential boundary

*Canonical path: `<QEVIK_STATE>/vault.json` + `<QEVIK_STATE>/credentials.jsonl`.
Verified live, 16/16, with both processes restarted.*

## The defect

The control plane wrote `<QEVIK_STATE>/vault.json`. The worker read
`<vault_root>/credentials.json`. Two different files — so the Credential Centre
could show a credential `CONNECTED` while the worker could not see it, and the
worker's refusal read as "no credential configured" to an operator looking at a
screen that said otherwise.

## The first fix was worse than the bug

It accepted either shape and fell back to whichever file existed. Two paths that
usually agree diverge the moment one of them is written, and nothing reports it.
A fallback here does not remove the ambiguity, it hides it.

## What replaced it

`credentials/location.py` is the only module that decides where credentials
live. It returns **both files together**, because they are one boundary:

    <state>/vault.json          the sealed secrets
    <state>/credentials.jsonl   fingerprint, hint, verification result

A process with only one of them finds nothing usable, which is why they are
never resolved separately at two call sites.

`paths_for()` takes the state **directory**. Passing a file raises. A function
that accepted both would be the fallback again.

`QEVIK_VAULT` is gone. It named a single file, which meant the records file was
resolved somewhere else — precisely how the two ended up in different
directories. `--vault` on the worker is likewise gone, replaced by `--state`.

## Why it cannot drift again

`test_credential_location.py` reads the source of every caller and fails on a
string literal naming a credential file outside `location.py`, in either
direction:

- no caller may name `vault.json`, `credentials.jsonl` or `credentials.json`
- every caller **must** call `paths_for` — otherwise a file with no literals and
  no credentials would pass the first check

That pairing matters. The original bug was two literals in two files that agreed
on the day they were written.

Both processes also **log where they looked** at start-up:

    credentials: {'state': '/var/lib/qevik/control',
                  'vault': '.../vault.json',
                  'records': '.../credentials.jsonl', ...}

The failure was invisible for as long as it was precisely because neither
process ever said which file it was reading. An operator comparing a Centre
showing CONNECTED against a worker saying "no credential configured" had nothing
to compare.

## Live acceptance — 16/16

`infra/verify_vault_boundary.py`, on qevik-core-01:

| | |
|---|---|
| save through the Credential Centre | HTTP 201, no secret returned |
| **restart the control plane** | still `PENDING_CREDENTIAL`, same fingerprint |
| **restart the worker** | running, and it logs the same two paths |
| the worker's own view | same fingerprint, same hint, resolved its own way |
| no second store | only `vault.json` + `credentials.jsonl`; nothing else appeared |
| secret on disk | absent from the records file, absent in clear from the vault |

One check was deliberately removed rather than made to pass: the production
worker runs `--agent self-check`, which needs no credentials and therefore never
opens the store, so asserting a "restored N record(s)" line would have been
asserting a code path that agent does not take. The worker's own view above
makes the stronger claim anyway.

## A side effect worth knowing

`qevik-worker.service` stops after five starts in five minutes. Repeated
verification restarts hit that, and the harness now runs `systemctl reset-failed`
first — which is what an operator does. Lowering the limit to make a test
convenient would remove the protection it exists to provide.
