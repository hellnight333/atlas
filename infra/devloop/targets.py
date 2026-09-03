"""Which host the DevLoop's gates may reach, from the one reviewed registry.

`infra/` is not a Python package, so the sibling module is loaded by path
rather than imported — the alternative is a second copy of the registry parser,
and a second copy is how the host and the key drifted apart in the first place.

The DevLoop follows the same rule as the deploy scripts: **no implicit
production default.** With `QEVIK_DEPLOY_TARGET` unset there is no host to
reach, and a gate that cannot reach a host reports `unmeasured` — it never
falls back to whichever host used to be production.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[1] / "deploy_targets.py"

_spec = importlib.util.spec_from_file_location("qevik_deploy_targets", _MODULE)
if _spec is None or _spec.loader is None:  # pragma: no cover - packaging accident
    raise ImportError(f"cannot load the deploy-target registry from {_MODULE}")
_targets = importlib.util.module_from_spec(_spec)
# Registered before execution: `@dataclass` looks its own module up in
# sys.modules while the class body is being processed, and a module that is not
# there yet raises rather than defining the class.
sys.modules.setdefault("qevik_deploy_targets", _targets)
_spec.loader.exec_module(_targets)

Target = _targets.Target
TargetError = _targets.TargetError
resolve = _targets.resolve


def control_plane() -> Target | None:
    """The host the gates may reach, or None when none is configured.

    None is not an error here: it is the state "this machine has not been told
    which production host to look at", which every caller already knows how to
    report as `unmeasured`.
    """
    if not os.environ.get("QEVIK_DEPLOY_TARGET"):
        return None
    try:
        return resolve()
    except TargetError:
        return None


def ssh_argv(target: Target, remote: str, *, connect_timeout: int = 20,
             attempts: int = 4) -> list[str]:
    """The one way this package reaches the control plane."""
    argv = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}",
            "-o", f"ConnectionAttempts={attempts}"]
    if target.key:
        argv += ["-i", target.key, "-o", "IdentitiesOnly=yes"]
    argv += [target.host, remote]
    return argv


#: Where the control plane keeps its environment and its virtualenv. Stated once
#: here because three call sites used to spell it out, each with its own copy of
#: the shell that read the environment file.
APP_DIR = "/opt/qevik/atlas"
ENV_FILE = "/opt/qevik/atlas.env"
APP_USER = "qevik"


def remote_python(script: str, *, heredoc: str = "PY") -> str:
    """A remote command that runs `script` with the control plane's environment.

    The environment arrives through systemd's own `EnvironmentFile=` parser,
    given a path — the same parser the units use. What stood here sourced the
    environment file in a shell: a database password containing ``$``, a
    backtick, a quote or a space either broke the command or was silently
    altered before the process saw it. Fixing the reader rather
    than the password is the whole point; a credential's entropy is not a
    deploy-time variable.
    """
    return (f"systemd-run --wait --collect --pipe --quiet "
            f"--property=EnvironmentFile={ENV_FILE} "
            f"--property=User={APP_USER} --property=Group={APP_USER} "
            f"--property=WorkingDirectory={APP_DIR} "
            f"--setenv=PYTHONPATH={APP_DIR}/packages/kernel "
            f"{APP_DIR}/.venv/bin/python - <<'{heredoc}'\n{script}\n{heredoc}")
