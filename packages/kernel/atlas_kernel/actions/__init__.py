"""Executable actions: the layer that turns capabilities into a plan that runs.

`ExecutionPlan` and `PlanStep` described work; the registry catalogued action
names; the providers behind those names were stubs that slept and returned a
hashed `example.com` URL. Nothing joined them up.

This package registers the verified capabilities — search, code execution,
browser, deployment — as actions a plan can compose, threads each step's output
into the next, records every action as lineage, and repairs a step that fails
instead of stopping at it.
"""

from .context import ActionRecord, ExecutionContext
from .handlers import (
    BROWSER_OPERATE,
    CODE_EXECUTE,
    CODE_GENERATE,
    CODE_WRITE,
    SITE_DEPLOY,
    WEB_SEARCH,
    ActionError,
    PublishNotAuthorised,
)
from .llm_planner import LLMPlanner, PlanRejected
from .planning import (
    RegenerateRepairer,
    default_planner,
    plan_website,
    title_from_request,
)
from .runner import (
    ActionRunner,
    PlanReport,
    PlanRunner,
    Repairer,
    default_action_runner,
    resolve,
    topological,
)

__all__ = [
    "BROWSER_OPERATE",
    "CODE_EXECUTE",
    "CODE_GENERATE",
    "CODE_WRITE",
    "SITE_DEPLOY",
    "WEB_SEARCH",
    "ActionError",
    "ActionRecord",
    "ActionRunner",
    "ExecutionContext",
    "PlanReport",
    "PlanRunner",
    "PublishNotAuthorised",
    "LLMPlanner",
    "PlanRejected",
    "RegenerateRepairer",
    "default_planner",
    "Repairer",
    "default_action_runner",
    "plan_website",
    "resolve",
    "title_from_request",
    "topological",
]
