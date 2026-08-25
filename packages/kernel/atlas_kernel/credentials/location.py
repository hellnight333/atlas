"""Where credentials live. One answer, and every process asks it.

The control plane wrote `<QEVIK_STATE>/vault.json`; the worker read
`<vault_root>/credentials.json`. Two different files, so the Credential Centre
could show a credential CONNECTED that the worker could not see — and the
worker's refusal read as "no credential configured" to an operator looking at a
screen that said otherwise.

The first fix accepted either shape and fell back to whichever existed. That is
worse than the bug: two paths that usually agree diverge the moment one of them
gets written, and nothing reports it. **There is no fallback here.** A
deployment names its state directory and both files follow from it.

## Two files, one boundary

    <state>/vault.json          the sealed secrets
    <state>/credentials.jsonl   the records: fingerprint, hint, verification

Both, or neither. The vault holds the secret and nothing else; the timeline
holds the metadata and never a secret. A process with only one of them finds
nothing usable, which is why they are returned together rather than resolved
separately at two call sites.

## Nothing constructs these paths itself

`test_credential_location.py` reads the source of every caller and fails on a
literal `vault.json` or `credentials.jsonl` outside this module. That test is
the reason the two halves cannot drift apart again.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: The sealed secrets. Named here and nowhere else.
VAULT_FILE = "vault.json"

#: The records the Centre reads: fingerprint, hint, verification result. Never a
#: secret — `CredentialRecord` has no field that could hold one.
RECORDS_FILE = "credentials.jsonl"

#: Where a deployment says its durable state lives.
STATE_ENV = "QEVIK_STATE"

#: For a developer running without a state directory. Under the user's home
#: rather than the repository, so a checkout can be deleted without destroying
#: the keys in it — and so a `git status` never lists them.
DEFAULT_STATE = Path.home() / ".qevik"


@dataclass(frozen=True)
class CredentialPaths:
    """The two files, together.

    Returned as a pair because they are one boundary. A caller that resolved the
    vault in one place and the records in another is the shape of the bug this
    module replaced.
    """

    state: Path
    vault: Path
    records: Path

    def summary(self) -> dict:
        return {"state": str(self.state), "vault": str(self.vault),
                "records": str(self.records)}


def paths_for(state: Path | str | None = None) -> CredentialPaths:
    """Both credential files for one deployment.

    `state` is the directory, never a file. Passing a file would reintroduce the
    question this module exists to answer once — and a function that accepted
    both would be the fallback that silently diverges.
    """
    root = Path(state) if state is not None else _state_from_environment()
    if root.suffix:
        raise ValueError(
            f"{root} looks like a file. `paths_for` takes the state *directory*; "
            "the file names are this module's to decide, and a caller that "
            "chose one would be the second answer that drifts.")
    return CredentialPaths(state=root, vault=root / VAULT_FILE,
                           records=root / RECORDS_FILE)


def _state_from_environment() -> Path:
    configured = os.environ.get(STATE_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_STATE


def describe(state: Path | str | None = None) -> dict:
    """What this process would read, for a health check or a report.

    Worth surfacing: the failure it replaced was invisible precisely because
    neither process ever said which file it was looking at.
    """
    paths = paths_for(state)
    return {**paths.summary(),
            "vault_exists": paths.vault.exists(),
            "records_exist": paths.records.exists(),
            "note": ("One boundary for every process. The vault holds the "
                     "secret, the timeline holds the record, and a process "
                     "with only one of them finds nothing.")}
