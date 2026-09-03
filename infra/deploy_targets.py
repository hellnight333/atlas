"""Read `infra/deploy_targets.conf` — the one place that says where a deploy may go.

The shell resolver (`infra/deploy_target.sh`) and this module answer the same
question from the same file, so the deploy scripts and the Python callers (the
DevLoop gates, boundary and inspection modules) cannot drift apart about which
host is production and which key reaches it.

The rules are the shell's rules, and they are deliberately unforgiving:

* a registry name resolves to that entry;
* a raw ``user@host`` resolves only with an explicit identity, never a guessed one;
* nothing given is a refusal — this tooling has no default host;
* an unknown name is a refusal, never a fallback.

`TargetError` carries the message a caller should print; every caller treats it
as "stop", not as "try something else".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CONF = Path(__file__).resolve().parent / "deploy_targets.conf"


def _conf(conf: Path | None = None) -> Path:
    """The registry to read: an explicit path, then QEVIK_TARGETS_FILE, then the
    repository's own — the same override the shell resolver honours, so a test
    or a rehearsal points both readers at one file."""
    if conf is not None:
        return conf
    override = os.environ.get("QEVIK_TARGETS_FILE")
    return Path(override) if override else CONF


class TargetError(RuntimeError):
    """A target could not be resolved. The message names the known targets."""


@dataclass(frozen=True)
class Target:
    """One row of the registry, resolved for this machine."""

    name: str
    host: str
    #: Identity file, or None when the entry defers to ``~/.ssh/config``.
    key: str | None
    role: str = ""

    def ssh_argv(self, *command: str) -> list[str]:
        """`ssh` argv for this target, with the identity pinned when there is one."""
        argv = ["ssh"]
        if self.key:
            argv += ["-i", self.key, "-o", "IdentitiesOnly=yes"]
        argv.append(self.host)
        argv += list(command)
        return argv


def _rows(conf: Path | None = None) -> list[tuple[str, str, str, str]]:
    conf = _conf(conf)
    rows: list[tuple[str, str, str, str]] = []
    if not conf.is_file():
        return rows
    for line in conf.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = [p.strip() for p in stripped.split("|")]
        if len(parts) < 3:
            continue
        name, host, key = parts[0], parts[1], parts[2]
        role = parts[3] if len(parts) > 3 else ""
        rows.append((name, host, key, role))
    return rows


def names(conf: Path | None = None) -> list[str]:
    return [row[0] for row in _rows(conf)]


def _expand(key: str) -> str:
    return os.path.expanduser(key)


def resolve(spec: str | None = None, *, conf: Path | None = None,
            key: str | None = None, require_key_file: bool = True) -> Target:
    """Resolve a target name or a raw ``user@host``.

    `spec` falls back to ``QEVIK_DEPLOY_TARGET``; `key` to ``QEVIK_DEPLOY_KEY``.
    Both fallbacks are environment, never a built-in host.
    """
    conf = _conf(conf)
    spec = spec or os.environ.get("QEVIK_DEPLOY_TARGET") or ""
    known = names(conf)
    hint = (f"known targets: {' '.join(known) or '(none)'}; "
            f"registry: {conf}")

    if not spec:
        raise TargetError(
            "no target given and this tooling has no default host — "
            f"pass a target name or set QEVIK_DEPLOY_TARGET. {hint}")

    if "@" in spec:
        identity = key or os.environ.get("QEVIK_DEPLOY_KEY") or ""
        if not identity:
            raise TargetError(
                f"'{spec}' is a raw host; set QEVIK_DEPLOY_KEY to the identity "
                f"it may be reached with. An approved identity is never guessed. {hint}")
        identity = _expand(identity)
        if require_key_file and not Path(identity).is_file():
            raise TargetError(f"identity file '{identity}' does not exist.")
        return Target(name="explicit", host=spec, key=identity, role="ad-hoc")

    for name, host, raw_key, role in _rows(conf):
        if name != spec:
            continue
        if raw_key == "-":
            return Target(name=name, host=host, key=None, role=role)
        identity = _expand(raw_key)
        if require_key_file and not Path(identity).is_file():
            raise TargetError(
                f"target '{name}' needs identity '{identity}', which does not "
                "exist on this machine.")
        return Target(name=name, host=host, key=identity, role=role)

    raise TargetError(f"unknown target '{spec}' — there is no fallback. {hint}")
