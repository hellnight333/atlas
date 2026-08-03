from __future__ import annotations

from dataclasses import dataclass

from .agents.runtime import AgentRuntime
from .agents.scheduler import AgentScheduler
from .approval.gate import RuntimeApprovalGate
from .approval.policies import ApprovalPolicyEngine
from .approval.service import ApprovalService
from .asset_system import AssetService
from .automation_engine import AutomationEngine
from .backup import BackupService
from .cluster.cluster_state import ClusterStateService
from .cluster.dispatcher import Dispatcher
from .cluster.heartbeat_service import HeartbeatService
from .cluster.lease_manager import LeaseManager
from .cluster.worker_registry import WorkerRegistry
from .config import AtlasConfig, load_config
from .db import engine as db_engine
from .db import init_db
from .demo_installer import DemoInstaller
from .diagnostics import DiagnosticsService
from .event_bus import EventBus
from .execution_policy import ExecutionPolicyEngine
from .executor import ExecutionLocationExecutor, JobExecutor, LocalExecutor
from .graph_service import GraphService
from .logging_setup import configure_logging
from .models import ActionSpec, CapabilitySpec, ExecutorSpec, ModelSpec, ProviderSpec, RecipeSpec
from .onboarding import OnboardingService
from .orchestrator import Orchestrator
from .organization.audit import AuditService
from .organization.identity import IdentityService
from .organization.permissions import PermissionEngine
from .organization.policy_resolver import PolicyResolver
from .organization.service import OrganizationService
from .providers import LocalFluxProvider, LocalTextProvider, ProviderManager
from .recovery import RecoveryService
from .registry import Registry
from .repository import AtlasRepository
from .router import ProviderRouter
from .state_machine import ExecutionStateMachine
from .storage import LocalFileStorageBackend
from .telemetry import FileSink, TelemetryConsent, TelemetryService
from .updates import GitHubReleaseFeed, StaticFeed, UpdateService
from .worker import Worker
from .workflow_engine import KernelWorkflowNodeDelegate, WorkflowEngine


@dataclass(frozen=True)
class AtlasRuntime:
    event_bus: EventBus
    registry: Registry
    provider_registry: ProviderManager
    repository: AtlasRepository
    state_machine: ExecutionStateMachine
    router: ProviderRouter
    asset_service: AssetService
    execution_policy: ExecutionPolicyEngine
    graph_service: GraphService
    executor: JobExecutor
    worker: Worker
    agent_runtime: AgentRuntime
    agent_scheduler: AgentScheduler
    approval_service: ApprovalService
    approval_gate: RuntimeApprovalGate
    worker_registry: WorkerRegistry
    heartbeat_service: HeartbeatService
    lease_manager: LeaseManager
    dispatcher: Dispatcher
    cluster_state: ClusterStateService
    audit_service: AuditService
    identity_service: IdentityService
    organization_service: OrganizationService
    config: AtlasConfig
    diagnostics: DiagnosticsService
    backup_service: BackupService
    recovery_service: RecoveryService
    telemetry: TelemetryService
    onboarding: OnboardingService
    demo_installer: DemoInstaller
    update_service: UpdateService
    orchestrator: Orchestrator
    workflow_delegate: KernelWorkflowNodeDelegate
    workflow_engine: WorkflowEngine
    automation_engine: AutomationEngine


def create_runtime(
    event_bus: EventBus | None = None,
    registry: Registry | None = None,
    provider_registry: ProviderManager | None = None,
    repository: AtlasRepository | None = None,
    state_machine: ExecutionStateMachine | None = None,
    location_executor: ExecutionLocationExecutor | None = None,
    config: AtlasConfig | None = None,
) -> AtlasRuntime:
    config = config or load_config()
    configure_logging(config)
    init_db()

    event_bus = event_bus or EventBus()
    registry = registry or Registry()
    provider_registry = provider_registry or ProviderManager()
    repository = repository or AtlasRepository()
    state_machine = state_machine or ExecutionStateMachine()

    _register_default_actions(registry)
    _register_default_providers(registry, provider_registry)
    _register_default_capabilities(registry)
    _register_default_execution_inventory(registry)

    router = ProviderRouter(registry)
    asset_service = AssetService(
        repository=repository,
        bus=event_bus,
        storage_backend=LocalFileStorageBackend(),
    )
    execution_policy = ExecutionPolicyEngine(
        registry=registry,
        repository=repository,
        event_bus=event_bus,
    )
    graph_service = GraphService(repository=repository, event_bus=event_bus)
    executor = JobExecutor(
        repository=repository,
        provider_manager=provider_registry,
        location_executor=location_executor or LocalExecutor(),
        bus=event_bus,
        asset_service=asset_service,
    )
    worker = Worker(
        repository=repository,
        router=router,
        provider_manager=provider_registry,
        event_bus=event_bus,
        execution_policy=execution_policy,
        executor=executor,
    )
    approval_service = ApprovalService(
        repository=repository,
        event_bus=event_bus,
        policy_engine=ApprovalPolicyEngine(),
    )
    approval_gate = RuntimeApprovalGate(service=approval_service, event_bus=event_bus)
    worker_registry = WorkerRegistry(repository=repository, event_bus=event_bus)
    heartbeat_service = HeartbeatService(
        repository=repository, event_bus=event_bus, registry=worker_registry
    )
    lease_manager = LeaseManager(repository=repository, event_bus=event_bus)
    audit_service = AuditService(repository=repository, event_bus=event_bus)
    identity_service = IdentityService(repository=repository, event_bus=event_bus)
    organization_service = OrganizationService(
        repository=repository,
        event_bus=event_bus,
        audit=audit_service,
        permission_engine=PermissionEngine(),
        policy_resolver=PolicyResolver(),
    )
    dispatcher = Dispatcher(
        registry=worker_registry,
        lease_manager=lease_manager,
        event_bus=event_bus,
        ownership_filter=organization_service,
    )
    heartbeat_service.timeout_seconds = config.heartbeat_timeout_seconds
    lease_manager.lease_seconds = config.lease_seconds
    cluster_state = ClusterStateService(
        repository=repository,
        registry=worker_registry,
        heartbeats=heartbeat_service,
        lease_manager=lease_manager,
    )
    # A single-machine install is a cluster of one: register the in-process
    # worker so nothing needs configuring for Atlas to keep working.
    worker_registry.ensure_local_worker()
    agent_runtime = AgentRuntime(
        repository=repository,
        event_bus=event_bus,
        worker=worker,
        approval_gate=approval_gate,
        placement_gate=dispatcher,
    )
    orchestrator = Orchestrator(
        state_machine=state_machine,
        repository=repository,
        event_bus=event_bus,
    )
    workflow_delegate = KernelWorkflowNodeDelegate(orchestrator=orchestrator, worker=worker)
    workflow_engine = WorkflowEngine(delegate=workflow_delegate, bus=event_bus)
    agent_scheduler = AgentScheduler(repository=repository, event_bus=event_bus)
    automation_engine = AutomationEngine(
        repository=repository,
        event_bus=event_bus,
        scheduler=agent_scheduler,
        runtime=agent_runtime,
        graph_service=graph_service,
    )

    diagnostics = DiagnosticsService(
        config=config,
        repository=repository,
        registry=registry,
        provider_manager=provider_registry,
        cluster_state=cluster_state,
    )
    backup_service = BackupService(repository=repository, config=config)
    recovery_service = RecoveryService(
        repository=repository,
        runtime=agent_runtime,
        lease_manager=lease_manager,
        heartbeats=heartbeat_service,
        registry=worker_registry,
    )

    # Telemetry consent comes from configuration, which defaults to disabled.
    # The sink is always the real one: every record_* method returns early
    # unless consent covers it, so nothing can be written while telemetry is
    # off. Handing a disabled service a NullSink instead would mean that
    # opting in at runtime silently did nothing until the next restart.
    telemetry = TelemetryService(
        consent=TelemetryConsent(mode=config.telemetry_mode),
        sink=FileSink(config.data_dir / "telemetry.jsonl"),
        profile=str(config.profile),
    )
    # The feed stays offline unless the operator opted in, so constructing the
    # runtime never makes a network call.
    update_service = UpdateService(
        feed=GitHubReleaseFeed() if config.update_check_enabled else StaticFeed()
    )

    onboarding = OnboardingService(engine=db_engine)
    demo_installer = DemoInstaller(
        orchestrator=orchestrator,
        automation_engine=automation_engine,
        graph_service=graph_service,
        repository=repository,
        approval_service=approval_service,
    )

    return AtlasRuntime(
        event_bus=event_bus,
        registry=registry,
        provider_registry=provider_registry,
        repository=repository,
        state_machine=state_machine,
        router=router,
        asset_service=asset_service,
        execution_policy=execution_policy,
        graph_service=graph_service,
        executor=executor,
        worker=worker,
        agent_runtime=agent_runtime,
        agent_scheduler=agent_scheduler,
        approval_service=approval_service,
        approval_gate=approval_gate,
        worker_registry=worker_registry,
        heartbeat_service=heartbeat_service,
        lease_manager=lease_manager,
        dispatcher=dispatcher,
        cluster_state=cluster_state,
        audit_service=audit_service,
        identity_service=identity_service,
        organization_service=organization_service,
        orchestrator=orchestrator,
        workflow_delegate=workflow_delegate,
        workflow_engine=workflow_engine,
        automation_engine=automation_engine,
        config=config,
        diagnostics=diagnostics,
        backup_service=backup_service,
        recovery_service=recovery_service,
        telemetry=telemetry,
        onboarding=onboarding,
        demo_installer=demo_installer,
        update_service=update_service,
    )


def _register_default_actions(registry: Registry) -> None:
    registry.register_action(
        ActionSpec(name="image.generate", description="Generate an image from a prompt")
    )
    registry.register_action(
        ActionSpec(name="text.generate", description="Generate text output from a prompt")
    )
    registry.register_action(
        ActionSpec(name="code.generate", description="Generate code from a prompt")
    )


def _register_default_providers(registry: Registry, provider_registry: ProviderManager) -> None:
    registry.register_provider(
        ProviderSpec(name=LocalFluxProvider.name, kind="image", is_local=True, vram_gb=24)
    )
    registry.register_provider(
        ProviderSpec(name=LocalTextProvider.name, kind="llm", is_local=True, vram_gb=0)
    )

    provider_registry.register_adapter(LocalFluxProvider.name, LocalFluxProvider())
    provider_registry.register_adapter(LocalTextProvider.name, LocalTextProvider())


def _register_default_capabilities(registry: Registry) -> None:
    default_capabilities = [
        CapabilitySpec(
            id="cap-image-generation",
            name="Image Generation",
            description="Generate still images from prompts and recipe context.",
            supported_provider_kinds=["image"],
            supported_executor_kinds=["local", "docker", "remote", "cluster", "cloud", "comfy"],
            metadata={"category": "image", "stable": True},
        ),
        CapabilitySpec(
            id="cap-reasoning",
            name="Reasoning",
            description="General text reasoning and synthesis capability.",
            supported_provider_kinds=["llm"],
            supported_executor_kinds=["local", "docker", "remote", "cluster", "cloud", "ollama"],
            metadata={"category": "text", "stable": True},
        ),
        CapabilitySpec(
            id="cap-code-generation",
            name="Code Generation",
            description="Generate source code from prompts and constraints.",
            supported_provider_kinds=["llm"],
            supported_executor_kinds=["local", "docker", "remote", "cluster", "cloud", "ollama"],
            metadata={"category": "code", "stable": True},
        ),
    ]

    for capability in default_capabilities:
        registry.register_capability(capability)

    default_recipes = [
        RecipeSpec(
            id="recipe-image-fast-draft",
            capability_id="cap-image-generation",
            name="Fast Draft",
            profile="fast",
            parameters={"quality": "draft", "steps": 20},
            metadata={"supported_executor_kinds": ["local", "comfy", "cloud"]},
        ),
        RecipeSpec(
            id="recipe-image-product-photo",
            capability_id="cap-image-generation",
            name="Product Photography",
            profile="quality",
            parameters={"quality": "high", "style": "product-photo"},
            metadata={"supported_executor_kinds": ["local", "comfy", "cloud"]},
        ),
        RecipeSpec(
            id="recipe-reasoning-default",
            capability_id="cap-reasoning",
            name="Default Reasoning",
            profile="default",
            parameters={"temperature": 0.2},
            metadata={"supported_executor_kinds": ["local", "ollama", "cloud"]},
        ),
    ]

    for recipe in default_recipes:
        registry.register_capability_recipe(recipe)


def _register_default_execution_inventory(registry: Registry) -> None:
    registry.register_executor(
        ExecutorSpec(
            id="local",
            kind="local",
            is_local=True,
            health="healthy",
            max_vram_gb=48,
            metadata={"label": "Local Executor"},
        )
    )
    registry.register_executor(
        ExecutorSpec(
            id="cloud",
            kind="cloud",
            is_local=False,
            health="healthy",
            max_vram_gb=0,
            metadata={"label": "Cloud Executor"},
        )
    )

    registry.register_model(
        ModelSpec(
            id="flux-dev",
            provider_id="local-flux",
            capability_ids=["cap-image-generation"],
            quality_score=0.9,
            latency_ms=900,
            cost_per_unit=0.05,
            commercial_use=True,
            private_execution=True,
        )
    )
    registry.register_model(
        ModelSpec(
            id="qwen-local",
            provider_id="local-text",
            capability_ids=["cap-reasoning", "cap-code-generation"],
            quality_score=0.82,
            latency_ms=450,
            cost_per_unit=0.01,
            supports_streaming=True,
            commercial_use=True,
            private_execution=True,
        )
    )
