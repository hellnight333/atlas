"""Jobs that outlive the connection that started them.

The link between the operator and this machine is unreliable — it drops
mid-command and recovers minutes later. Any design where losing SSH loses the
work, or the record of the work, is wrong here. A job is therefore a directory
on the server, and reconnecting and reading it is the whole recovery procedure.
"""

from .health import collect
from .models import HealthReport, JobRecord, JobState, default_root
from .runner import JobError, JobRunner

__all__ = [
    "HealthReport",
    "JobError",
    "JobRecord",
    "JobRunner",
    "JobState",
    "collect",
    "default_root",
]
