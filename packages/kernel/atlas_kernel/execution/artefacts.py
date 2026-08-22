"""What an executor produced, and the one way its identity is computed.

A capability may produce one document or a whole site. Both are *bundles* — a
mapping of relative path to text — and a single document is simply a bundle with
one entry. Normalising at the boundary means the layers downstream have one
shape to handle rather than two, and, more importantly, **one hashing rule**.

Two rules would drift, and the drift would be silent in the worst possible
place: the publication gate compares the bytes about to go out against the hash
that was approved, so a hash computed one way at execution and another way at
publication would either refuse everything or — far worse — refuse nothing.
"""

from __future__ import annotations

import hashlib
import json

#: Where a single-document capability's output lands. A site is served from a
#: directory, and the document that is the directory is its index.
DEFAULT_PATH = "index.html"


def normalise(artefact: str | dict[str, str]) -> dict[str, str]:
    """A bundle, whatever the executor returned."""
    if isinstance(artefact, str):
        return {DEFAULT_PATH: artefact} if artefact else {}
    return dict(artefact)


def bundle_hash(files: str | dict[str, str]) -> str:
    """The identity of exactly this set of files with exactly these contents.

    Canonical: sorted paths, so a dictionary that iterates differently on
    another run is the same bundle, and a renamed file is a different one.
    """
    bundle = normalise(files)
    if not bundle:
        return ""
    canonical = json.dumps(bundle, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def primary(files: str | dict[str, str]) -> str:
    """The document a preview should open. `index.html` when there is one."""
    bundle = normalise(files)
    if DEFAULT_PATH in bundle:
        return DEFAULT_PATH
    return sorted(bundle)[0] if bundle else ""
