"""Workspace: where Qevik builds things.

The execution layer could route jobs and generate text but could not write a
file or run a command, which made steps 7–13 of the autonomous loop — write
code, run tools, run tests, diagnose, fix, re-run, build — unreachable rather
than merely unimplemented.
"""

from .models import (
    CODE_EXECUTE,
    CommandResult,
    FileWrite,
    PathEscape,
    WorkspaceError,
    WorkspaceRecord,
    safe_join,
)
from .workspace import Workspace, free_port, wait_for_port

__all__ = [
    "CODE_EXECUTE",
    "CommandResult",
    "FileWrite",
    "PathEscape",
    "Workspace",
    "WorkspaceError",
    "WorkspaceRecord",
    "free_port",
    "safe_join",
    "wait_for_port",
]
