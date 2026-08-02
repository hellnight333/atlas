from __future__ import annotations

import ast
from pathlib import Path

from atlas_kernel.composition_root import create_runtime
from atlas_kernel.models import Asset, CapabilitySpec

REPO_ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = REPO_ROOT / "packages" / "kernel" / "atlas_kernel"


def _read_module(name: str) -> str:
    return (KERNEL_ROOT / name).read_text(encoding="utf-8")


def test_event_bus_is_singleton_through_composition_root():
    runtime = create_runtime()

    assert runtime.orchestrator.bus is runtime.event_bus
    assert runtime.worker.bus is runtime.event_bus
    assert runtime.executor.bus is runtime.event_bus
    assert runtime.asset_service.bus is runtime.event_bus
    assert runtime.workflow_engine.bus is runtime.event_bus
    assert runtime.execution_policy.event_bus is runtime.event_bus


def test_workflow_engine_never_selects_providers():
    source = _read_module("workflow_engine.py")

    assert "select_provider(" not in source
    assert "ProviderRouter" not in source


def test_execution_policy_never_executes_jobs():
    source = _read_module("execution_policy.py")

    assert ".execute(" not in source
    assert "ProviderManager" not in source


def test_executors_never_choose_providers():
    source = _read_module("executor.py")

    assert "select_provider(" not in source
    assert "ProviderRouter" not in source


def test_providers_never_choose_executors():
    source = _read_module("providers.py")

    assert "ExecutionLocationExecutor" not in source
    assert "ExecutionDecision" not in source


def test_capabilities_remain_provider_agnostic():
    fields = set(CapabilitySpec.model_fields)

    assert "provider_id" not in fields
    assert "model_id" not in fields
    assert "executor_id" not in fields


def test_assets_always_belong_to_a_project():
    asset = Asset(type="image", uri="atlas://asset")

    assert asset.project_id == "project-unassigned"


def test_composition_root_remains_only_construction_point_for_core_runtime():
    disallowed = {
        "EventBus",
        "Orchestrator",
        "Worker",
        "WorkflowEngine",
        "JobExecutor",
        "AssetService",
        "ExecutionPolicyEngine",
    }
    allowed_files = {"composition_root.py", "api.py"}

    for path in KERNEL_ROOT.glob("*.py"):
        if path.name in allowed_files:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in disallowed:
                    raise AssertionError(
                        f"{path.name} constructs {func.id} outside composition root"
                    )
