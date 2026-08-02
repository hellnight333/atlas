from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .agents.models import (
    AgentCreate,
    AgentMemoryReference,
    AgentPermission,
    AgentRole,
    AgentStatus,
    AgentUpdate,
)
from .agents.plan_models import ExecutionPlan
from .agents.schedule_models import SchedulerPriority
from .agents.service import AgentFoundation
from .approval.models import (
    ApprovalCondition,
    ApprovalContext,
    ApprovalPolicy,
    ApprovalPolicyMode,
    ApprovalScope,
    ApprovalState,
)
from .approval.service import ApprovalError, SelfApprovalError
from .cluster.models import (
    HeartbeatReport,
    WorkerMetrics,
    WorkerRegistration,
    WorkerResources,
    WorkerState,
)
from .cluster.worker_registry import WorkerRegistryError
from .organization.identity import IdentityError
from .organization.models import (
    AuditAction,
    Branding,
    IdentityProviderKind,
    License,
    MembershipScope,
    Permission,
    PolicyDomain,
    PolicyScopeKind,
    PolicySet,
    TeamKind,
)
from .organization.service import (
    CrossOrganizationError,
    OrganizationError,
    PermissionDeniedError,
)
from .composition_root import create_runtime
from .event_bus import CapabilityRegistered, CapabilityUpdated, RecipeRegistered, RecipeSelected
from .models import (
    AssetCreate,
    AutomationAction,
    AutomationCondition,
    AutomationTrigger,
    ChatConversation,
    ChatMessage,
    ChatConversationCreate,
    ChatMessageCreate,
    CapabilityRequest,
    CapabilitySpec,
    ProjectCreate,
    ResearchGraph,
    ResearchSearchResult,
    ResearchSession,
    ReviewComment,
    ReviewHistoryEvent,
    ReviewItem,
    ReviewSession,
    RecipeSpec,
    RunCreate,
    RuntimeContext,
    WorkflowCreate,
    WorkspaceCreate,
    normalize_capability_request,
)
from .workflow_engine import (
    Condition,
    FailureStrategy,
    RetryPolicy,
    WorkflowDefinition,
    WorkflowNode,
)

app = FastAPI(title="Atlas Kernel")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:4174", "http://localhost:4174", "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
runtime = create_runtime()
registry = runtime.registry
repository = runtime.repository
orchestrator = runtime.orchestrator
workflow_engine = runtime.workflow_engine
asset_service = runtime.asset_service
event_bus = runtime.event_bus
execution_policy = runtime.execution_policy
graph_service = runtime.graph_service
automation_engine = runtime.automation_engine
approval_service = runtime.approval_service
worker_registry = runtime.worker_registry
heartbeat_service = runtime.heartbeat_service
lease_manager = runtime.lease_manager
dispatcher = runtime.dispatcher
cluster_state = runtime.cluster_state
organization_service = runtime.organization_service
identity_service = runtime.identity_service
audit_service = runtime.audit_service
agent_runtime = runtime.agent_runtime
agent_foundation = AgentFoundation(
    repository=repository,
    event_bus=event_bus,
    worker=runtime.worker,
    approval_gate=runtime.approval_gate,
    placement_gate=runtime.dispatcher,
)


class RunRequest(BaseModel):
    title: str
    description: str = ""
    studio: str = "image"
    workspace_id: str | None = None
    project_id: str | None = None
    workflow_id: str | None = None


class WorkspaceRequest(BaseModel):
    name: str
    description: str = ""


class ProjectRequest(BaseModel):
    workspace_id: str | None = None
    name: str
    description: str = ""


class AgentRequest(BaseModel):
    name: str
    description: str = ""
    role: str
    workspace_id: str | None = None
    project_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    memory_id: str | None = None
    permission_set: list[AgentPermission] = Field(default_factory=list)


class AgentPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    role: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    capabilities: list[str] | None = None
    status: AgentStatus | None = None
    memory_id: str | None = None
    permission_set: list[AgentPermission] | None = None


class AgentMemoryAttachRequest(BaseModel):
    kind: str
    asset_id: str


class AgentPlanRequest(BaseModel):
    goal: str


class SchedulerCreateRequest(BaseModel):
    agent_id: str
    goal: str
    priority: SchedulerPriority = SchedulerPriority.NORMAL
    available_executors: list[str] = Field(default_factory=list)
    execution_policy: dict[str, object] = Field(default_factory=dict)


class OrganizationCreateRequest(BaseModel):
    name: str
    slug: str | None = None
    description: str = ""
    branding: Branding | None = None
    license: License | None = None
    actor_id: str = "system"


class OrganizationUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    branding: Branding | None = None
    license: License | None = None
    allow_shared_pool: bool | None = None
    active: bool | None = None
    actor_id: str = "system"


class MemberAddRequest(BaseModel):
    identity_id: str
    role_ids: list[str] = Field(default_factory=list)
    team_ids: list[str] = Field(default_factory=list)
    scope: MembershipScope = MembershipScope.ORGANIZATION
    scope_id: str | None = None
    expires_at: datetime | None = None
    actor_id: str = "system"


class MembershipUpdateRequest(BaseModel):
    role_ids: list[str] | None = None
    team_ids: list[str] | None = None
    active: bool | None = None
    expires_at: datetime | None = None
    actor_id: str = "system"


class RoleCreateRequest(BaseModel):
    name: str
    permissions: list[Permission] = Field(default_factory=list)
    organization_id: str | None = None
    description: str = ""
    actor_id: str = "system"


class RoleUpdateRequest(BaseModel):
    permissions: list[Permission] = Field(default_factory=list)
    actor_id: str = "system"


class TeamCreateRequest(BaseModel):
    organization_id: str
    name: str
    kind: TeamKind = TeamKind.CUSTOM
    description: str = ""
    actor_id: str = "system"


class PolicySetRequest(BaseModel):
    id: str | None = None
    organization_id: str
    domain: PolicyDomain
    scope: PolicyScopeKind = PolicyScopeKind.ORGANIZATION
    scope_id: str | None = None
    settings: dict[str, object] = Field(default_factory=dict)
    locked_keys: list[str] = Field(default_factory=list)
    enabled: bool = True
    actor_id: str = "system"


class IdentityCreateRequest(BaseModel):
    subject: str
    display_name: str
    email: str | None = None
    provider: IdentityProviderKind = IdentityProviderKind.LOCAL


class WorkerAssignRequest(BaseModel):
    organization_id: str | None = None
    actor_id: str = "system"


class WorkerRegisterRequest(BaseModel):
    hostname: str
    display_name: str | None = None
    platform: str = "unknown"
    resources: WorkerResources = Field(default_factory=WorkerResources)
    capabilities: list[str] = Field(default_factory=list)
    max_concurrency: int = 1
    version: str = "0.0.0"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    worker_id: str | None = None


class WorkerHeartbeatRequest(BaseModel):
    worker_id: str
    status: WorkerState | None = None
    current_load: int | None = None
    metrics: WorkerMetrics | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class WorkerActionRequest(BaseModel):
    actor: str = "system"


class ApprovalCreateRequest(BaseModel):
    title: str
    action: str = ""
    scopes: list[ApprovalScope] = Field(default_factory=list)
    estimated_cost: float = 0.0
    project_id: str | None = None
    workspace_id: str | None = None
    agent_id: str | None = None
    execution_id: str | None = None
    schedule_id: str | None = None
    entry_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    asset_id: str | None = None
    priority: int = 0
    payload: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    requested_by: str = "system"


class ApprovalDecisionRequest(BaseModel):
    actor: str
    comment: str | None = None


class ApprovalEscalateRequest(BaseModel):
    actor: str
    escalated_to: str


class ApprovalViewRequest(BaseModel):
    actor: str


class ApprovalPolicyRequest(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    mode: ApprovalPolicyMode = ApprovalPolicyMode.SCOPED
    scopes: list[ApprovalScope] = Field(default_factory=list)
    cost_threshold: float | None = None
    conditions: list[ApprovalCondition] = Field(default_factory=list)
    required_approvers: list[str] = Field(default_factory=list)
    approvals_required: int = 1
    expires_after_seconds: int | None = None
    project_id: str | None = None
    workspace_id: str | None = None
    priority: int = 0
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class AutomationRuleRequest(BaseModel):
    name: str
    description: str = ""
    trigger: AutomationTrigger
    conditions: list[AutomationCondition] = Field(default_factory=list)
    actions: list[AutomationAction] = Field(default_factory=list)
    project_id: str | None = None
    workspace_id: str | None = None
    schedule: dict[str, object] | None = None
    priority: int = 0
    dry_run: bool = False
    actor: str = "system"


class AutomationRuleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger: AutomationTrigger | None = None
    conditions: list[AutomationCondition] | None = None
    actions: list[AutomationAction] | None = None
    schedule: dict[str, object] | None = None
    priority: int | None = None
    dry_run: bool | None = None
    actor: str = "system"


class AutomationRunRequest(BaseModel):
    trigger_data: dict[str, object] = Field(default_factory=dict)
    agent_id: str | None = None
    actor: str = "system"


class AgentAssignmentRequest(BaseModel):
    agent_id: str
    role: AgentRole
    title: str
    action: str
    payload: dict[str, object] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)


class AgentTeamCreateRequest(BaseModel):
    name: str
    project_id: str | None = None
    workspace_id: str | None = None
    assignments: list[AgentAssignmentRequest] = Field(default_factory=list)


class WorkflowRequest(BaseModel):
    id: str | None = None
    project_id: str | None = None
    name: str
    description: str = ""
    studio: str = "core"
    default_action: str | None = None
    capability_req: CapabilityRequest | dict[str, object] = Field(default_factory=CapabilityRequest)
    nodes: list[WorkflowNodeRequest] = Field(default_factory=list)


class AssetRequest(BaseModel):
    type: str
    project_id: str = "project-unassigned"
    workflow_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    parent_asset_id: str | None = None
    version: int = 1
    uri: str = ""
    mime_type: str | None = None
    file_size: int | None = None
    content_hash: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    source_asset_ids: list[str] = Field(default_factory=list)


class WorkflowNodeRequest(BaseModel):
    id: str
    action: str
    payload: dict[str, object] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    input_asset_ids: list[str] = Field(default_factory=list)
    output_labels: list[str] = Field(default_factory=list)
    capability_req: CapabilityRequest | dict[str, object] = Field(default_factory=CapabilityRequest)
    max_retries: int = 0
    retry_delay_seconds: float = 0.0
    failure_strategy: str = "fail_fast"
    condition_expression: str | None = None


class WorkflowDefinitionRequest(BaseModel):
    id: str
    name: str
    project_id: str = "project-unassigned"
    workflow_id: str | None = None
    nodes: list[WorkflowNodeRequest]


class WorkflowExecuteRequest(BaseModel):
    run_id: str


class CapabilitySpecRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    supported_provider_kinds: list[str] = Field(default_factory=list)
    supported_executor_kinds: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class RecipeRequest(BaseModel):
    id: str
    capability_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    profile: str = "default"
    parameters: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class RecipeSelectionRequest(BaseModel):
    run_id: str | None = None


class ExecutionPolicyEvaluateRequest(BaseModel):
    capability_req: CapabilityRequest | dict[str, object]
    runtime_context: RuntimeContext | None = None
    workspace_preferences: dict[str, object] = Field(default_factory=dict)
    project_preferences: dict[str, object] = Field(default_factory=dict)


class ChatConversationRequest(BaseModel):
    project_id: str
    title: str
    pinned: bool = False
    parent_conversation_id: str | None = None
    workflow_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ChatConversationUpdateRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    provider_name: str | None = None
    execution_time_ms: int | None = None
    tokens: int | None = None
    workflow_id: str | None = None
    parent_conversation_id: str | None = None
    prompt_asset_id: str | None = None
    response_asset_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ChatMessageRequest(BaseModel):
    conversation_id: str
    role: str
    content: str
    asset_id: str | None = None
    prompt_asset_id: str | None = None
    response_asset_id: str | None = None
    provider_name: str | None = None
    execution_time_ms: int | None = None
    tokens: int | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ChatConversationPatchRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    provider_name: str | None = None
    execution_time_ms: int | None = None
    tokens: int | None = None
    workflow_id: str | None = None
    parent_conversation_id: str | None = None
    prompt_asset_id: str | None = None
    response_asset_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ResearchSessionRequest(BaseModel):
    project_id: str
    title: str
    question: str
    conversation_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ResearchSearchRequest(BaseModel):
    session_id: str
    query: str
    provider: str = 'mock-search'


class ResearchSummarizeRequest(BaseModel):
    session_id: str
    source_asset_ids: list[str] = Field(default_factory=list)
    prompt: str = ''


class ResearchReportRequest(BaseModel):
    session_id: str
    format: str = 'markdown'
    prompt: str = ''


class ReviewRequest(BaseModel):
    project_id: str
    title: str
    asset_id: str | None = None
    workflow_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ReviewDecisionRequest(BaseModel):
    asset_id: str
    comment: str = ''
    metadata: dict[str, object] = Field(default_factory=dict)


class ReviewCommentRequest(BaseModel):
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)


class ReviewPublishRequest(BaseModel):
    asset_id: str
    metadata: dict[str, object] = Field(default_factory=dict)


class ImageGenerateRequest(BaseModel):
    project_id: str
    prompt: str
    negative_prompt: str = ''
    styles: list[str] = Field(default_factory=list)
    template: str | None = None
    variables: dict[str, object] = Field(default_factory=dict)
    seed: int | None = None
    steps: int = 30
    cfg: float = 7.0
    resolution: str = '1024x1024'
    sampler: str = 'euler'
    provider: str = 'local-flux'
    workflow: str = 'image.generate'
    model: str = 'flux-dev'
    metadata: dict[str, object] = Field(default_factory=dict)


class ImageVariantRequest(BaseModel):
    prompt: str | None = None
    negative_prompt: str | None = None
    styles: list[str] | None = None
    template: str | None = None
    variables: dict[str, object] | None = None
    seed: int | None = None
    steps: int | None = None
    cfg: float | None = None
    resolution: str | None = None
    sampler: str | None = None
    provider: str | None = None
    workflow: str | None = None
    model: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


ExecutionPolicyEvaluateRequest.model_rebuild()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/workspaces")
def create_workspace(request: WorkspaceRequest) -> dict[str, object]:
    workspace = orchestrator.create_workspace(
        WorkspaceCreate(name=request.name, description=request.description)
    )
    return {
        "workspace_id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
    }


@app.post("/projects")
def create_project(request: ProjectRequest) -> dict[str, object]:
    project = orchestrator.create_project(
        ProjectCreate(
            workspace_id=request.workspace_id, name=request.name, description=request.description
        )
    )
    return {
        "project_id": project.id,
        "workspace_id": project.workspace_id,
        "name": project.name,
        "description": project.description,
    }


@app.get("/projects")
def list_projects(workspace_id: str | None = None) -> list[dict[str, object]]:
    projects = repository.list_projects(workspace_id=workspace_id)
    return [project.model_dump() for project in projects]


@app.post("/agents")
def create_agent(request: AgentRequest) -> dict[str, object]:
    agent = agent_foundation.create_agent(
        AgentCreate(
            name=request.name,
            description=request.description,
            role=request.role,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            capabilities=list(request.capabilities),
            status=request.status,
            memory_id=request.memory_id,
            permission_set=list(request.permission_set),
        )
    )
    return agent.model_dump()


@app.get("/agents")
def list_agents(project_id: str | None = None) -> list[dict[str, object]]:
    return [agent.model_dump() for agent in agent_foundation.list_agents(project_id=project_id)]


@app.get("/agents/{agent_id}")
def get_agent(agent_id: str) -> dict[str, object]:
    agent = agent_foundation.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent.model_dump()


@app.patch("/agents/{agent_id}")
def patch_agent(agent_id: str, request: AgentPatchRequest) -> dict[str, object]:
    agent = agent_foundation.update_agent(
        agent_id,
        AgentUpdate(
            name=request.name,
            description=request.description,
            role=request.role,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            capabilities=request.capabilities,
            status=request.status,
            memory_id=request.memory_id,
            permission_set=request.permission_set,
        ),
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent.model_dump()


@app.delete("/agents/{agent_id}")
def delete_agent(agent_id: str) -> dict[str, object]:
    deleted = agent_foundation.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted", "agent_id": agent_id}


@app.get("/agents/{agent_id}/memory")
def list_agent_memory(agent_id: str) -> list[dict[str, object]]:
    if agent_foundation.get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    memory_refs: list[AgentMemoryReference] = agent_foundation.list_memory(agent_id)
    return [reference.model_dump() for reference in memory_refs]


@app.post("/agents/{agent_id}/memory")
def attach_agent_memory(agent_id: str, request: AgentMemoryAttachRequest) -> dict[str, object]:
    try:
        reference = agent_foundation.attach_memory_reference(
            agent_id=agent_id,
            kind=request.kind,
            asset_id=request.asset_id,
        )
        return reference.model_dump()
    except ValueError as exc:
        if str(exc) in {"Agent not found", "Asset not found"}:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/agents/{agent_id}/permissions")
def get_agent_permissions(agent_id: str) -> list[str]:
    if agent_foundation.get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return [permission.value for permission in agent_foundation.get_permissions(agent_id)]


@app.post("/agents/{agent_id}/plan")
def create_agent_plan(agent_id: str, request: AgentPlanRequest) -> dict[str, object]:
    agent = agent_foundation.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    workspace_intelligence: dict[str, object] = {}
    if agent.project_id:
        try:
            workspace_intelligence = _workspace_context(agent.project_id).get("workspace_context", {})
        except HTTPException:
            workspace_intelligence = {}

    try:
        plan: ExecutionPlan = agent_foundation.generate_plan(
            agent_id=agent_id,
            goal=request.goal,
            workspace_intelligence=workspace_intelligence,
        )
    except ValueError as exc:
        if str(exc) == "Agent not found":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return plan.model_dump()


@app.post("/scheduler/schedule")
def create_schedule(request: SchedulerCreateRequest) -> dict[str, object]:
    agent = agent_foundation.get_agent(request.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    workspace_intelligence: dict[str, object] = {}
    if agent.project_id:
        try:
            workspace_intelligence = _workspace_context(agent.project_id).get("workspace_context", {})
        except HTTPException:
            workspace_intelligence = {}

    try:
        plan = agent_foundation.generate_plan(
            agent_id=request.agent_id,
            goal=request.goal,
            workspace_intelligence=workspace_intelligence,
        )
        schedule = agent_foundation.create_schedule(
            agent_id=request.agent_id,
            plan=plan,
            priority=request.priority,
            workspace_state=workspace_intelligence,
            available_executors=list(request.available_executors),
            execution_policy=dict(request.execution_policy),
        )
    except ValueError as exc:
        if str(exc) == "Agent not found":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return schedule.model_dump(mode="json")


@app.get("/scheduler/{schedule_id}")
def get_schedule(schedule_id: str) -> dict[str, object]:
    schedule = agent_foundation.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule.model_dump(mode="json")


@app.get("/scheduler/{schedule_id}/queue")
def get_schedule_queue(schedule_id: str) -> list[dict[str, object]]:
    schedule = agent_foundation.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return [entry.model_dump(mode="json") for entry in schedule.queue_entries]


@app.post("/scheduler/{schedule_id}/pause")
def pause_schedule(schedule_id: str) -> dict[str, object]:
    try:
        result = agent_foundation.pause_schedule(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@app.post("/scheduler/{schedule_id}/resume")
def resume_schedule(schedule_id: str) -> dict[str, object]:
    try:
        result = agent_foundation.resume_schedule(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@app.post("/scheduler/{schedule_id}/cancel")
def cancel_schedule(schedule_id: str) -> dict[str, object]:
    try:
        result = agent_foundation.cancel_schedule(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@app.post("/runtime/schedule/{schedule_id}/start")
def start_runtime_schedule(schedule_id: str) -> list[dict[str, object]]:
    schedule = agent_foundation.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    try:
        return agent_foundation.start_runtime_for_schedule(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/runtime")
def list_runtime() -> list[dict[str, object]]:
    return agent_foundation.list_runtime()


@app.get("/runtime/running")
def list_runtime_running() -> list[dict[str, object]]:
    return agent_foundation.list_runtime_running()


@app.get("/runtime/history")
def list_runtime_history() -> list[dict[str, object]]:
    return agent_foundation.list_runtime_history()


@app.get("/runtime/{execution_id}")
def get_runtime_execution(execution_id: str) -> dict[str, object]:
    execution = agent_foundation.get_runtime_execution(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Runtime execution not found")
    return execution


@app.post("/runtime/{execution_id}/cancel")
def cancel_runtime_execution(execution_id: str) -> dict[str, object]:
    try:
        return agent_foundation.cancel_runtime_execution(execution_id)
    except ValueError as exc:
        if str(exc) == "Runtime execution not found":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/runtime/{execution_id}/retry")
def retry_runtime_execution(execution_id: str) -> dict[str, object]:
    try:
        return agent_foundation.retry_runtime_execution(execution_id)
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/agents/team")
def create_agent_team(request: AgentTeamCreateRequest) -> dict[str, object]:
    try:
        team = agent_foundation.create_team(
            name=request.name,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            assignments=[assignment.model_dump(mode="json") for assignment in request.assignments],
        )
        team = agent_foundation.execute_team(team.id)
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return team.model_dump(mode="json")


@app.get("/agents/team/{team_id}")
def get_agent_team(team_id: str) -> dict[str, object]:
    team = agent_foundation.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team.model_dump(mode="json")


@app.get("/agents/team/{team_id}/messages")
def get_agent_team_messages(team_id: str) -> list[dict[str, object]]:
    team = agent_foundation.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return [message.model_dump(mode="json") for message in agent_foundation.list_team_messages(team_id)]


@app.post("/agents/team/{team_id}/cancel")
def cancel_agent_team(team_id: str) -> dict[str, object]:
    try:
        team = agent_foundation.cancel_team(team_id)
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return team.model_dump(mode="json")


@app.get("/agents/team/{team_id}/status")
def get_agent_team_status(team_id: str) -> dict[str, object]:
    try:
        return agent_foundation.get_team_status(team_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/graph/project/{project_id}")
def get_project_graph(project_id: str) -> dict[str, object]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    graph = graph_service.materialize_project_graph(project_id)
    snapshot = graph_service.create_snapshot("project", project_id)
    return {
        "graph": graph.model_dump(mode="json"),
        "snapshot": snapshot.model_dump(mode="json"),
    }


@app.get("/graph/node/{node_id}")
def get_graph_node(node_id: str) -> dict[str, object]:
    node = graph_service.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return node.model_dump(mode="json")


@app.get("/graph/node/{node_id}/neighbors")
def get_graph_neighbors(node_id: str) -> list[dict[str, object]]:
    node = graph_service.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return [neighbor.model_dump(mode="json") for neighbor in graph_service.neighbors(node_id)]


@app.get("/graph/path")
def get_graph_path(start: str, end: str) -> dict[str, object]:
    return {"path": graph_service.shortest_path(start, end)}


@app.get("/graph/context/{project_id}")
def get_graph_context(project_id: str) -> dict[str, object]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return graph_service.context_bundle(project_id).model_dump(mode="json")


@app.get("/graph/lineage/{asset_id}")
def get_graph_lineage(asset_id: str) -> dict[str, object]:
    asset = repository.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return graph_service.asset_lineage(asset_id).model_dump(mode="json")


@app.get("/graph/history/{node_id}")
def get_graph_history(node_id: str) -> list[dict[str, object]]:
    node = graph_service.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return graph_service.node_history(node_id)


@app.post("/chat/conversations")
def create_chat_conversation(request: ChatConversationRequest) -> dict[str, object]:
    project = repository.get_project(request.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    conversation = repository.create_chat_conversation(
        ChatConversation(
            id=f"conversation-{__import__('uuid').uuid4().hex[:8]}",
            project_id=request.project_id,
            title=request.title,
            pinned=request.pinned,
            parent_conversation_id=request.parent_conversation_id,
            workflow_id=request.workflow_id,
            metadata=dict(request.metadata),
        )
    )
    return conversation.model_dump()


@app.post("/research/session")
def create_research_session(request: ResearchSessionRequest) -> dict[str, object]:
    project = repository.get_project(request.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    session_record = repository.create_research_session(
        ResearchSession(
            id=f"research-session-{__import__('uuid').uuid4().hex[:8]}",
            project_id=request.project_id,
            title=request.title,
            question=request.question,
            conversation_id=request.conversation_id,
            metadata=dict(request.metadata),
        )
    )
    return session_record.model_dump()


@app.get("/research/session/{session_id}")
def get_research_session(session_id: str) -> dict[str, object]:
    session_record = repository.get_research_session(session_id)
    if session_record is None:
        raise HTTPException(status_code=404, detail="Research session not found")
    return session_record.model_dump()


@app.get("/research/session")
def list_research_sessions(project_id: str | None = None) -> list[dict[str, object]]:
    return [session_record.model_dump() for session_record in repository.list_research_sessions(project_id)]


@app.post("/research/search")
def research_search(request: ResearchSearchRequest) -> dict[str, object]:
    session_record = repository.get_research_session(request.session_id)
    if session_record is None:
        raise HTTPException(status_code=404, detail="Research session not found")
    query = request.query.strip()
    results = [
        ResearchSearchResult(
            id=f"source-{index}",
            title=f"{query} source {index + 1}",
            url=f"https://example.com/research/{query.replace(' ', '-').lower()}/{index + 1}",
            provider=request.provider,
            author="Atlas Mock Provider",
            language="en",
            content_type="text/html",
            trust_score=0.6 + (index * 0.1),
            hash=f"hash-{index + 1}",
            metadata={"query": query, "session_id": request.session_id},
        )
        for index in range(3)
    ]
    imported_assets = []
    for result in results:
        imported_assets.append(
            asset_service.create_asset_from_request(
                AssetCreate(
                    type="document",
                    project_id=session_record.project_id,
                    uri=result.url,
                    metadata={
                        "kind": "source",
                        "title": result.title,
                        "provider": result.provider,
                        "retrieved_at": __import__('datetime').datetime.now(__import__('datetime').UTC).isoformat(),
                        "author": result.author,
                        "language": result.language,
                        "content_type": result.content_type,
                        "trust_score": result.trust_score,
                        "hash": result.hash,
                        **result.metadata,
                    },
                    tags=["research-source", request.provider],
                )
            )
        )
    graph = repository.get_research_graph(session_record.project_id)
    graph.nodes.extend(
        [
            {
                "id": asset.id,
                "type": "Source",
                "label": asset.metadata.get("title") or asset.id,
                "asset_id": asset.id,
            }
            for asset in imported_assets
        ]
    )
    graph.edges.extend(
        [
            {
                "id": f"edge-{asset.id}",
                "type": "Belongs To",
                "from": asset.id,
                "to": session_record.project_id,
            }
            for asset in imported_assets
        ]
    )
    repository.save_research_graph(graph)
    return {
        "session_id": request.session_id,
        "provider": request.provider,
        "sources": [asset.model_dump() for asset in imported_assets],
    }


@app.post("/research/summarize")
def research_summarize(request: ResearchSummarizeRequest) -> dict[str, object]:
    session_record = repository.get_research_session(request.session_id)
    if session_record is None:
        raise HTTPException(status_code=404, detail="Research session not found")
    run = orchestrator.create_run(
        RunCreate(
            title=session_record.title,
            description=request.prompt or session_record.question,
            studio="text",
            project_id=session_record.project_id,
        )
    )
    job = orchestrator.enqueue_job(
        run.id,
        action="text.generate",
        payload={
            "prompt": request.prompt or f"Summarize research for: {session_record.question}",
            "source_asset_ids": request.source_asset_ids,
            "session_id": request.session_id,
        },
        capability_req={"capability_id": "cap-reasoning", "requirements": {"required_vram_gb": 0}},
    )
    result = runtime.worker.execute_job(job)
    summary_asset = repository.get_asset(result.get("asset_id")) if result.get("asset_id") else None
    if summary_asset is None:
        summary_asset = asset_service.create_asset_from_request(
            AssetCreate(
                type="text",
                project_id=session_record.project_id,
                run_id=run.id,
                job_id=job.id,
                uri=f"atlas://research/{request.session_id}/summary",
                source_asset_ids=request.source_asset_ids,
                metadata={
                    "kind": "finding",
                    "session_id": request.session_id,
                    "content": result.get("output", {}).get("text") or f"Generated response for: {request.prompt or session_record.question}",
                    "provider": result.get("provider") or "local-text",
                    "citations": request.source_asset_ids,
                },
                tags=["research-finding"],
            )
        )
    else:
        summary_asset = asset_service.update_asset(
            summary_asset.id,
            {
                "metadata": {
                    **(summary_asset.metadata or {}),
                    "kind": "finding",
                    "session_id": request.session_id,
                    "content": result.get("output", {}).get("text")
                    or summary_asset.metadata.get("text")
                    or summary_asset.metadata.get("content")
                    or f"Generated response for: {request.prompt or session_record.question}",
                    "provider": result.get("provider") or "local-text",
                    "citations": request.source_asset_ids,
                },
                "tags": list({*(summary_asset.tags or []), "research-finding"}),
                "source_asset_ids": request.source_asset_ids,
            },
        )
    graph = repository.get_research_graph(session_record.project_id)
    graph.nodes.append({
        "id": summary_asset.id,
        "type": "Finding",
        "label": summary_asset.metadata.get("content") or summary_asset.id,
        "asset_id": summary_asset.id,
    })
    graph.edges.extend(
        [
            {
                "id": f"derived-{summary_asset.id}-{source_id}",
                "type": "Derived From",
                "from": summary_asset.id,
                "to": source_id,
            }
            for source_id in request.source_asset_ids
        ]
    )
    repository.save_research_graph(graph)
    return {
        "run_id": run.id,
        "job_id": job.id,
        "provider": result.get("provider") or "local-text",
        "asset": summary_asset.model_dump(),
    }


@app.post("/research/report")
def research_report(request: ResearchReportRequest) -> dict[str, object]:
    session_record = repository.get_research_session(request.session_id)
    if session_record is None:
        raise HTTPException(status_code=404, detail="Research session not found")
    findings = [asset for asset in repository.list_assets(project_id=session_record.project_id) if (asset.metadata or {}).get("kind") == "finding"]
    report_content = "\n\n".join(
        [
            f"# {session_record.title}",
            f"Question: {session_record.question}",
            *(str((finding.metadata or {}).get("content", "")) for finding in findings[:5]),
        ]
    )
    report_asset = asset_service.create_asset_from_request(
        AssetCreate(
            type="document",
            project_id=session_record.project_id,
            uri=f"atlas://research/{request.session_id}/report.{request.format}",
            metadata={
                "kind": "report",
                "session_id": request.session_id,
                "format": request.format,
                "content": report_content,
                "source_finding_ids": [finding.id for finding in findings],
            },
            source_asset_ids=[finding.id for finding in findings],
            tags=["research-report", request.format],
        )
    )
    updated = session_record.model_copy(
        update={
            "report_asset_id": report_asset.id,
            "updated_at": __import__('datetime').datetime.now(__import__('datetime').UTC),
        }
    )
    repository.update_research_session(updated)
    return report_asset.model_dump()


@app.get("/research/graph/{project_id}")
def get_research_graph(project_id: str) -> dict[str, object]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return repository.get_research_graph(project_id).model_dump()


def _load_review_or_404(review_id: str) -> ReviewSession:
    review = repository.get_review_session(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


def _build_review_payload(review: ReviewSession) -> dict[str, object]:
    return {
        **review.model_dump(),
        "items": [item.model_dump() for item in repository.list_review_items(review.id)],
        "comments": [comment.model_dump() for comment in repository.list_review_comments(review.id)],
    }


def _parse_resolution(value: str) -> tuple[int, int]:
    parts = value.lower().split('x')
    if len(parts) != 2:
        return 1024, 1024
    try:
        width = int(parts[0])
        height = int(parts[1])
        if width <= 0 or height <= 0:
            return 1024, 1024
        return width, height
    except Exception:
        return 1024, 1024


def _next_image_seed(seed: int | None) -> int:
    if seed is not None:
        return int(seed)
    return int(__import__('time').time()) % 2_147_483_647


def _coerce_image_payload(asset: dict[str, object] | None) -> dict[str, object]:
    source = asset or {}
    metadata = source.get('metadata') if isinstance(source.get('metadata'), dict) else {}
    return {
        'id': source.get('id'),
        'project_id': source.get('project_id'),
        'run_id': source.get('run_id'),
        'job_id': source.get('job_id'),
        'workflow_id': source.get('workflow_id'),
        'parent_asset_id': source.get('parent_asset_id'),
        'version': source.get('version'),
        'uri': source.get('uri'),
        'thumbnail_uri': source.get('thumbnail_uri'),
        'content_hash': source.get('content_hash'),
        'prompt': metadata.get('prompt', ''),
        'negative_prompt': metadata.get('negative_prompt', ''),
        'styles': metadata.get('styles', []),
        'template': metadata.get('template'),
        'variables': metadata.get('variables', {}),
        'prompt_history': metadata.get('prompt_history', []),
        'prompt_version': metadata.get('prompt_version', 1),
        'seed': metadata.get('seed'),
        'steps': metadata.get('steps'),
        'cfg': metadata.get('cfg'),
        'resolution': metadata.get('resolution'),
        'sampler': metadata.get('sampler'),
        'provider': metadata.get('provider'),
        'workflow': metadata.get('workflow'),
        'model': metadata.get('model'),
        'execution_time_ms': metadata.get('execution_time_ms'),
        'metadata': metadata,
        'created_at': source.get('created_at'),
        'updated_at': source.get('updated_at'),
    }


def _resolve_image_base(image_id: str) -> dict[str, object]:
    asset = repository.get_asset(image_id)
    if asset is None:
        raise HTTPException(status_code=404, detail='Image asset not found')
    if asset.type != 'image':
        raise HTTPException(status_code=400, detail='Asset is not an image')
    return asset.model_dump()


def _image_payload_from_request(
    base: dict[str, object] | None,
    request: ImageGenerateRequest | ImageVariantRequest,
    prompt_fallback: str = '',
) -> dict[str, object]:
    base_metadata = {}
    if base and isinstance(base.get('metadata'), dict):
        base_metadata = dict(base.get('metadata', {}))

    def _get(name: str, default: object) -> object:
        request_value = getattr(request, name, None)
        if request_value is not None:
            return request_value
        if name in base_metadata:
            return base_metadata[name]
        return default

    prompt = _get('prompt', prompt_fallback)
    negative_prompt = _get('negative_prompt', '')
    styles = _get('styles', [])
    template = _get('template', None)
    variables = _get('variables', {})
    seed = _next_image_seed(_get('seed', None) if isinstance(_get('seed', None), int) else None)
    steps = int(_get('steps', 30))
    cfg = float(_get('cfg', 7.0))
    resolution = str(_get('resolution', '1024x1024'))
    sampler = str(_get('sampler', 'euler'))
    provider_name = str(_get('provider', 'local-flux'))
    workflow = str(_get('workflow', 'image.generate'))
    model = str(_get('model', 'flux-dev'))

    width, height = _parse_resolution(resolution)
    rendered_prompt = str(prompt)
    if isinstance(variables, dict):
        for key, value in variables.items():
            rendered_prompt = rendered_prompt.replace(f'{{{{{key}}}}}', str(value))

    base_prompt_history = []
    if isinstance(base_metadata.get('prompt_history'), list):
        base_prompt_history = list(base_metadata['prompt_history'])
    next_prompt_history = [*base_prompt_history, rendered_prompt][-20:]

    return {
        'prompt': rendered_prompt,
        'negative_prompt': str(negative_prompt),
        'styles': list(styles) if isinstance(styles, list) else [],
        'template': template,
        'variables': variables if isinstance(variables, dict) else {},
        'prompt_history': next_prompt_history,
        'prompt_version': len(next_prompt_history),
        'seed': seed,
        'steps': steps,
        'cfg': cfg,
        'resolution': resolution,
        'sampler': sampler,
        'provider': provider_name,
        'workflow': workflow,
        'model': model,
        'width': width,
        'height': height,
    }


def _execute_image_generation(
    project_id: str,
    payload: dict[str, object],
    parent_asset_id: str | None = None,
    source_asset_ids: list[str] | None = None,
) -> dict[str, object]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='Project not found')

    run = orchestrator.create_run(
        RunCreate(
            title=f"Image generation: {str(payload.get('prompt', 'Untitled'))[:48]}",
            description='Image Studio generation',
            studio='image',
            project_id=project_id,
            workflow_id='image-studio-default',
        )
    )

    version = 1
    if parent_asset_id is not None:
        parent_asset = repository.get_asset(parent_asset_id)
        if parent_asset is None:
            raise HTTPException(status_code=404, detail='Parent image not found')
        version = parent_asset.version + 1

    job_payload = {
        'prompt': payload.get('prompt'),
        'negative_prompt': payload.get('negative_prompt'),
        'seed': payload.get('seed'),
        'steps': payload.get('steps'),
        'cfg': payload.get('cfg'),
        'resolution': payload.get('resolution'),
        'sampler': payload.get('sampler'),
        'provider': payload.get('provider'),
        'workflow': payload.get('workflow'),
        'model': payload.get('model'),
        'styles': payload.get('styles', []),
        'template': payload.get('template'),
        'variables': payload.get('variables', {}),
        'prompt_history': payload.get('prompt_history', []),
        'prompt_version': payload.get('prompt_version', 1),
        'execution_time_ms': 0,
        'parent_asset_id': parent_asset_id,
        'version': version,
        'input_asset_ids': source_asset_ids or [],
    }

    job = orchestrator.enqueue_job(
        run.id,
        action='image.generate',
        payload=job_payload,
        capability_req={'capability_id': 'cap-image-generation', 'requirements': {'required_vram_gb': 0}},
    )

    result = runtime.worker.execute_job(job)
    if result.get('status') != 'completed':
        raise HTTPException(status_code=500, detail=result.get('error') or 'Image generation failed')

    image_asset = repository.get_asset(result.get('asset_id')) if result.get('asset_id') else None
    if image_asset is None:
        raise HTTPException(status_code=500, detail='Generated image asset missing')

    # Backfill execution timing metadata from provider output when available.
    metadata = dict(image_asset.metadata or {})
    if isinstance(result.get('output'), dict):
        output_payload = result['output']
        if output_payload.get('execution_time_ms') is not None:
            metadata['execution_time_ms'] = output_payload.get('execution_time_ms')
    updated_asset = asset_service.update_asset(image_asset.id, {'metadata': metadata}) or image_asset

    return {
        'run': run.model_dump(),
        'job': {
            'id': job.id,
            'run_id': job.run_id,
            'status': result.get('status'),
            'provider': result.get('provider'),
            'output': result.get('output'),
        },
        'image': _coerce_image_payload(updated_asset.model_dump()),
    }


@app.post('/images/generate')
def generate_image(request: ImageGenerateRequest) -> dict[str, object]:
    payload = _image_payload_from_request(None, request, prompt_fallback=request.prompt)
    response = _execute_image_generation(
        project_id=request.project_id,
        payload={**payload, **dict(request.metadata)},
    )
    image_id = response['image'].get('id') if isinstance(response.get('image'), dict) else None
    if isinstance(image_id, str):
        repository.create_review_session(
            ReviewSession(
                id=f"review-{__import__('uuid').uuid4().hex[:8]}",
                project_id=request.project_id,
                title=f"Image Review {str(payload.get('prompt', 'Untitled'))[:48]}",
                status='pending',
                asset_id=image_id,
                workflow_id='image-studio-default',
                metadata={'kind': 'image-review', 'auto_created': True},
            )
        )
    return response


@app.get('/images')
def list_images(project_id: str | None = None) -> list[dict[str, object]]:
    assets = repository.list_assets(project_id=project_id)
    images = [asset for asset in assets if asset.type == 'image']
    return [_coerce_image_payload(image.model_dump()) for image in images]


@app.get('/images/{image_id}')
def get_image(image_id: str) -> dict[str, object]:
    return _coerce_image_payload(_resolve_image_base(image_id))


@app.post('/images/{image_id}/variant')
def create_image_variant(image_id: str, request: ImageVariantRequest) -> dict[str, object]:
    base = _resolve_image_base(image_id)
    payload = _image_payload_from_request(base, request, prompt_fallback=str((base.get('metadata') or {}).get('prompt', '')))
    return _execute_image_generation(
        project_id=str(base.get('project_id')),
        payload={**payload, **dict(request.metadata)},
        parent_asset_id=image_id,
        source_asset_ids=[image_id],
    )


@app.post('/images/{image_id}/regenerate')
def regenerate_image(image_id: str, request: ImageVariantRequest) -> dict[str, object]:
    base = _resolve_image_base(image_id)
    payload = _image_payload_from_request(base, request, prompt_fallback=str((base.get('metadata') or {}).get('prompt', '')))
    # Regenerate intentionally creates another versioned variant in the same lineage.
    return _execute_image_generation(
        project_id=str(base.get('project_id')),
        payload={**payload, **dict(request.metadata)},
        parent_asset_id=image_id,
        source_asset_ids=[image_id],
    )


@app.get('/images/{image_id}/versions')
def list_image_versions(image_id: str) -> list[dict[str, object]]:
    base = _resolve_image_base(image_id)
    lineage_root_id = str(base.get('parent_asset_id') or image_id)
    root_asset = repository.get_asset(lineage_root_id)
    if root_asset is None:
        root_asset = repository.get_asset(image_id)
    if root_asset is None:
        raise HTTPException(status_code=404, detail='Image asset not found')

    versions = [root_asset, *repository.list_child_assets(root_asset.id)]
    versions = [asset for asset in versions if asset.type == 'image']
    versions.sort(key=lambda item: item.version)
    return [_coerce_image_payload(asset.model_dump()) for asset in versions]


def _normalize_asset_type(asset_type: str) -> str:
    value = (asset_type or '').lower()
    if value == 'image':
        return 'image'
    if value in {'document', 'text'}:
        return 'research'
    if value in {'dataset'}:
        return 'knowledge'
    if value in {'video'}:
        return 'media'
    return 'asset'


def _workspace_recent(project_id: str) -> dict[str, object]:
    assets = repository.list_assets(project_id=project_id)
    runs = repository.list_runs_by_project(project_id)
    jobs = repository.list_jobs_by_project(project_id)
    chats = repository.list_chat_conversations(project_id)
    research = repository.list_research_sessions(project_id)
    reviews = repository.list_review_sessions(project_id)
    workflows = repository.list_workflows(project_id)

    return {
        'project_id': project_id,
        'recent_activity': [
            {
                'id': job.id,
                'type': 'job',
                'action': job.action,
                'status': job.status.value,
                'provider': job.provider_name,
                'created_at': job.created_at,
            }
            for job in jobs[:20]
        ],
        'recent_assets': [asset.model_dump() for asset in assets[:20]],
        'recent_conversations': [conversation.model_dump() for conversation in chats[:10]],
        'recent_research': [session.model_dump() for session in research[:10]],
        'recent_reviews': [review.model_dump() for review in reviews[:10]],
        'recent_images': [
            _coerce_image_payload(asset.model_dump())
            for asset in assets
            if asset.type == 'image'
        ][:10],
        'recent_workflows': [workflow.model_dump() for workflow in workflows[:10]],
        'recent_runs': [run.model_dump() for run in runs[:10]],
    }


def _workspace_recommendations(project_id: str) -> dict[str, object]:
    assets = repository.list_assets(project_id=project_id)
    reviews = repository.list_review_sessions(project_id)
    research = repository.list_research_sessions(project_id)
    jobs = repository.list_jobs_by_project(project_id)

    pending_reviews = [review for review in reviews if review.status in {'pending', 'changes_requested'}]
    latest_image = next((asset for asset in assets if asset.type == 'image'), None)
    latest_research = research[0] if research else None
    blocked_jobs = [job for job in jobs if job.status.value in {'blocked', 'failed'}]

    recommendations: list[dict[str, object]] = []
    if latest_research is not None:
        recommendations.append({
            'type': 'continue_research',
            'title': 'Continue Research',
            'reason': f"Research session '{latest_research.title}' is active.",
            'action': 'open-research',
            'reference_id': latest_research.id,
        })
        recommendations.append({
            'type': 'summarize_findings',
            'title': 'Summarize Findings',
            'reason': 'Recent research sources are available for consolidation.',
            'action': 'summarize-research',
            'reference_id': latest_research.id,
        })
        recommendations.append({
            'type': 'create_report',
            'title': 'Create Report',
            'reason': 'Generate a report from current research findings.',
            'action': 'create-report',
            'reference_id': latest_research.id,
        })
    if latest_image is not None:
        recommendations.append({
            'type': 'generate_variant',
            'title': 'Generate Variant',
            'reason': 'An image is available for iterative variation.',
            'action': 'open-image-studio',
            'reference_id': latest_image.id,
        })
    if pending_reviews:
        recommendations.append({
            'type': 'review_pending_asset',
            'title': 'Review Pending Asset',
            'reason': f'{len(pending_reviews)} reviews require attention.',
            'action': 'open-review-studio',
            'reference_id': pending_reviews[0].id,
        })
    published_reviews = [review for review in reviews if review.status == 'approved']
    if published_reviews:
        recommendations.append({
            'type': 'publish',
            'title': 'Publish',
            'reason': 'Approved reviews are ready for publication.',
            'action': 'publish-review',
            'reference_id': published_reviews[0].id,
        })
    if blocked_jobs:
        recommendations.append({
            'type': 'resolve_blocked_job',
            'title': 'Resolve Blocked Job',
            'reason': f'{len(blocked_jobs)} job(s) are blocked or failed.',
            'action': 'open-activity-center',
            'reference_id': blocked_jobs[0].id,
        })

    return {
        'project_id': project_id,
        'recommendations': recommendations,
    }


def _workspace_context(project_id: str) -> dict[str, object]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='Project not found')

    assets = repository.list_assets(project_id=project_id)
    runs = repository.list_runs_by_project(project_id)
    jobs = repository.list_jobs_by_project(project_id)
    chats = repository.list_chat_conversations(project_id)
    research = repository.list_research_sessions(project_id)
    reviews = repository.list_review_sessions(project_id)

    pinned_assets = [asset for asset in assets if bool((asset.metadata or {}).get('pinned'))]
    open_tasks = [job for job in jobs if job.status.value in {'queued', 'running', 'blocked'}]
    suggested_tasks = _workspace_recommendations(project_id)['recommendations']
    knowledge_highlights = [
        {
            'asset_id': asset.id,
            'title': (asset.metadata or {}).get('title') or asset.id,
            'summary': asset.ai_summary or (asset.metadata or {}).get('content') or '',
            'kind': _normalize_asset_type(asset.type),
        }
        for asset in assets[:5]
    ]

    return {
        'workspace_context': {
            'project': project.model_dump(),
            'project_summary': {
                'total_assets': len(assets),
                'total_runs': len(runs),
                'running_jobs': len([job for job in jobs if job.status.value == 'running']),
                'open_reviews': len([review for review in reviews if review.status in {'pending', 'changes_requested'}]),
                'knowledge_growth': len([asset for asset in assets if _normalize_asset_type(asset.type) in {'research', 'knowledge'}]),
            },
            'recent_activity': [
                {
                    'id': job.id,
                    'action': job.action,
                    'status': job.status.value,
                    'created_at': job.created_at,
                }
                for job in jobs[:15]
            ],
            'recent_assets': [asset.model_dump() for asset in assets[:15]],
            'pinned_assets': [asset.model_dump() for asset in pinned_assets[:10]],
            'open_tasks': [
                {
                    'id': job.id,
                    'action': job.action,
                    'status': job.status.value,
                    'run_id': job.run_id,
                }
                for job in open_tasks[:10]
            ],
            'suggested_tasks': suggested_tasks[:10],
            'recent_conversations': [conversation.model_dump() for conversation in chats[:10]],
            'recent_research': [session.model_dump() for session in research[:10]],
            'recent_reviews': [review.model_dump() for review in reviews[:10]],
            'recent_images': [
                _coerce_image_payload(asset.model_dump())
                for asset in assets
                if asset.type == 'image'
            ][:10],
            'knowledge_highlights': knowledge_highlights,
            'recommendations': suggested_tasks,
        }
    }


def _workspace_dashboard(project_id: str) -> dict[str, object]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='Project not found')

    assets = repository.list_assets(project_id=project_id)
    runs = repository.list_runs_by_project(project_id)
    jobs = repository.list_jobs_by_project(project_id)
    workflows = repository.list_workflows(project_id)
    research = repository.list_research_sessions(project_id)
    reviews = repository.list_review_sessions(project_id)
    chats = repository.list_chat_conversations(project_id)

    recent_timeline = [
        {
            'id': item['id'],
            'type': item['type'],
            'title': item['title'],
            'created_at': item['created_at'],
        }
        for item in sorted(
            [
                *[
                    {'id': run.id, 'type': 'run', 'title': run.title, 'created_at': run.created_at}
                    for run in runs[:10]
                ],
                *[
                    {'id': asset.id, 'type': 'asset', 'title': asset.id, 'created_at': asset.created_at}
                    for asset in assets[:10]
                ],
                *[
                    {'id': review.id, 'type': 'review', 'title': review.title, 'created_at': review.created_at}
                    for review in reviews[:10]
                ],
            ],
            key=lambda record: str(record.get('created_at', '')),
            reverse=True,
        )[:20]
    ]

    return {
        'project_summary': {
            'project': project.model_dump(),
            'summary': f"{len(assets)} assets, {len(runs)} runs, {len(reviews)} reviews, {len(chats)} conversations",
        },
        'project_health': {
            'running_jobs': len([job for job in jobs if job.status.value == 'running']),
            'blocked_jobs': len([job for job in jobs if job.status.value in {'blocked', 'failed'}]),
            'open_reviews': len([review for review in reviews if review.status in {'pending', 'changes_requested'}]),
            'research_sessions': len(research),
            'image_queue': len([asset for asset in assets if asset.type == 'image']),
        },
        'recent_timeline': recent_timeline,
        'recent_workflows': [workflow.model_dump() for workflow in workflows[:10]],
        'research_progress': {
            'total_sessions': len(research),
            'active_sessions': len([session for session in research if session.status == 'active']),
        },
        'review_queue': [review.model_dump() for review in reviews if review.status in {'pending', 'changes_requested'}],
        'image_queue': [
            _coerce_image_payload(asset.model_dump())
            for asset in assets
            if asset.type == 'image'
        ][:20],
        'knowledge_growth': {
            'research_assets': len([asset for asset in assets if _normalize_asset_type(asset.type) in {'research', 'knowledge'}]),
            'conversations': len(chats),
            'research_sessions': len(research),
        },
    }


@app.get('/workspace/context/{project_id}')
def workspace_context(project_id: str) -> dict[str, object]:
    return _workspace_context(project_id)


@app.get('/workspace/recommendations/{project_id}')
def workspace_recommendations(project_id: str) -> dict[str, object]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return _workspace_recommendations(project_id)


@app.get('/workspace/recent/{project_id}')
def workspace_recent(project_id: str) -> dict[str, object]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return _workspace_recent(project_id)


@app.get('/workspace/dashboard/{project_id}')
def workspace_dashboard(project_id: str) -> dict[str, object]:
    return _workspace_dashboard(project_id)


@app.post("/reviews")
def create_review(request: ReviewRequest) -> dict[str, object]:
    project = repository.get_project(request.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if request.asset_id is not None and repository.get_asset(request.asset_id) is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    review = repository.create_review_session(
        ReviewSession(
            id=f"review-{__import__('uuid').uuid4().hex[:8]}",
            project_id=request.project_id,
            title=request.title,
            status="pending",
            asset_id=request.asset_id,
            workflow_id=request.workflow_id,
            metadata={**dict(request.metadata), "kind": "review"},
        )
    )
    repository.create_review_history_event(
        ReviewHistoryEvent(
            id=f"review-event-{__import__('uuid').uuid4().hex[:8]}",
            review_id=review.id,
            event_type="created",
            to_status=review.status,
            asset_id=review.asset_id,
            metadata={"title": review.title},
        )
    )
    return _build_review_payload(review)


@app.get("/reviews")
def list_reviews(project_id: str | None = None) -> list[dict[str, object]]:
    return [_build_review_payload(review) for review in repository.list_review_sessions(project_id)]


@app.post("/reviews/{review_id}/approve")
def approve_review(review_id: str, request: ReviewDecisionRequest) -> dict[str, object]:
    review = _load_review_or_404(review_id)
    asset = repository.get_asset(request.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    previous_status = review.status
    updated = review.model_copy(
        update={
            "status": "approved",
            "asset_id": request.asset_id,
            "updated_at": __import__('datetime').datetime.now(__import__('datetime').UTC),
            "metadata": {**review.metadata, **dict(request.metadata)},
        }
    )
    repository.update_review_session(updated)
    repository.upsert_review_item(
        ReviewItem(
            id=f"review-item-{request.asset_id}",
            review_id=review_id,
            asset_id=request.asset_id,
            decision="approved",
            comment=request.comment or None,
            metadata=dict(request.metadata),
        )
    )
    repository.create_review_history_event(
        ReviewHistoryEvent(
            id=f"review-event-{__import__('uuid').uuid4().hex[:8]}",
            review_id=review_id,
            event_type="approved",
            comment=request.comment or None,
            from_status=previous_status,
            to_status="approved",
            asset_id=request.asset_id,
            metadata=dict(request.metadata),
        )
    )
    return _build_review_payload(updated)


@app.post("/reviews/{review_id}/reject")
def reject_review(review_id: str, request: ReviewDecisionRequest) -> dict[str, object]:
    review = _load_review_or_404(review_id)
    asset = repository.get_asset(request.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    previous_status = review.status
    updated = review.model_copy(
        update={
            "status": "changes_requested",
            "asset_id": request.asset_id,
            "updated_at": __import__('datetime').datetime.now(__import__('datetime').UTC),
            "metadata": {**review.metadata, **dict(request.metadata)},
        }
    )
    repository.update_review_session(updated)
    repository.upsert_review_item(
        ReviewItem(
            id=f"review-item-{request.asset_id}",
            review_id=review_id,
            asset_id=request.asset_id,
            decision="rejected",
            comment=request.comment or None,
            metadata=dict(request.metadata),
        )
    )
    repository.create_review_history_event(
        ReviewHistoryEvent(
            id=f"review-event-{__import__('uuid').uuid4().hex[:8]}",
            review_id=review_id,
            event_type="rejected",
            comment=request.comment or None,
            from_status=previous_status,
            to_status="changes_requested",
            asset_id=request.asset_id,
            metadata=dict(request.metadata),
        )
    )
    return _build_review_payload(updated)


@app.post("/reviews/{review_id}/comment")
def comment_review(review_id: str, request: ReviewCommentRequest) -> dict[str, object]:
    review = _load_review_or_404(review_id)
    comment = repository.create_review_comment(
        ReviewComment(
            id=f"review-comment-{__import__('uuid').uuid4().hex[:8]}",
            review_id=review_id,
            content=request.content,
            metadata=dict(request.metadata),
        )
    )
    repository.create_review_history_event(
        ReviewHistoryEvent(
            id=f"review-event-{__import__('uuid').uuid4().hex[:8]}",
            review_id=review_id,
            event_type="commented",
            comment=comment.content,
            from_status=review.status,
            to_status=review.status,
            asset_id=review.asset_id,
            metadata=dict(request.metadata),
        )
    )
    return comment.model_dump()


@app.post("/reviews/{review_id}/publish")
def publish_review(review_id: str, request: ReviewPublishRequest) -> dict[str, object]:
    review = _load_review_or_404(review_id)
    source_asset = repository.get_asset(request.asset_id)
    if source_asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if source_asset.project_id != review.project_id:
        raise HTTPException(status_code=400, detail="Asset does not belong to review project")

    published_asset = asset_service.create_asset_version(
        source_asset.id,
        updates={
            "project_id": review.project_id,
            "workflow_id": review.workflow_id,
            "metadata": {
                **(source_asset.metadata or {}),
                "kind": "review-published",
                "review_id": review_id,
                **dict(request.metadata),
            },
            "tags": list({*(source_asset.tags or []), "review-published"}),
            "source_asset_ids": list({*source_asset.source_asset_ids, source_asset.id}),
        },
    )
    if published_asset is None:
        raise HTTPException(status_code=500, detail="Failed to publish review asset")

    previous_status = review.status
    updated = review.model_copy(
        update={
            "status": "published",
            "asset_id": request.asset_id,
            "published_asset_id": published_asset.id,
            "updated_at": __import__('datetime').datetime.now(__import__('datetime').UTC),
            "metadata": {**review.metadata, **dict(request.metadata), "published": True},
        }
    )
    repository.update_review_session(updated)
    repository.create_review_history_event(
        ReviewHistoryEvent(
            id=f"review-event-{__import__('uuid').uuid4().hex[:8]}",
            review_id=review_id,
            event_type="published",
            from_status=previous_status,
            to_status="published",
            asset_id=request.asset_id,
            published_asset_id=published_asset.id,
            metadata=dict(request.metadata),
        )
    )
    return {
        **_build_review_payload(updated),
        "published_asset": published_asset.model_dump(),
    }


@app.get("/reviews/{review_id}/history")
def get_review_history(review_id: str) -> list[dict[str, object]]:
    _load_review_or_404(review_id)
    return [event.model_dump() for event in repository.list_review_history(review_id)]


@app.get("/chat/conversations")
def list_chat_conversations(project_id: str | None = None) -> list[dict[str, object]]:
    return [conversation.model_dump() for conversation in repository.list_chat_conversations(project_id)]


@app.get("/chat/conversation/{conversation_id}")
def get_chat_conversation(conversation_id: str) -> dict[str, object]:
    conversation = repository.get_chat_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = repository.list_chat_messages(conversation_id)
    return {
        **conversation.model_dump(),
        "messages": [message.model_dump() for message in messages],
    }


@app.post("/chat/conversation/{conversation_id}")
def update_chat_conversation(
    conversation_id: str, request: ChatConversationPatchRequest
) -> dict[str, object]:
    conversation = repository.get_chat_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    updated = conversation.model_copy(
        update={
            "title": request.title if request.title is not None else conversation.title,
            "pinned": request.pinned if request.pinned is not None else conversation.pinned,
            "provider_name": request.provider_name if request.provider_name is not None else conversation.provider_name,
            "execution_time_ms": request.execution_time_ms if request.execution_time_ms is not None else conversation.execution_time_ms,
            "tokens": request.tokens if request.tokens is not None else conversation.tokens,
            "workflow_id": request.workflow_id if request.workflow_id is not None else conversation.workflow_id,
            "parent_conversation_id": request.parent_conversation_id if request.parent_conversation_id is not None else conversation.parent_conversation_id,
            "prompt_asset_id": request.prompt_asset_id if request.prompt_asset_id is not None else conversation.prompt_asset_id,
            "response_asset_id": request.response_asset_id if request.response_asset_id is not None else conversation.response_asset_id,
            "metadata": {**conversation.metadata, **request.metadata},
            "updated_at": __import__('datetime').datetime.now(__import__('datetime').UTC),
        }
    )
    repository.update_chat_conversation(updated)
    return updated.model_dump()


@app.post("/chat/message")
def create_chat_message(request: ChatMessageRequest) -> dict[str, object]:
    conversation = repository.get_chat_conversation(request.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    existing_messages = repository.list_chat_messages(request.conversation_id)
    prompt_version = len(existing_messages) + 1
    prompt_asset = asset_service.create_asset_from_request(
        AssetCreate(
            type="text",
            project_id=conversation.project_id,
            workflow_id=conversation.workflow_id,
            uri=f"atlas://chat/{conversation.id}/prompt/{prompt_version}",
            metadata={
                "kind": "prompt",
                "conversation_id": conversation.id,
                "message_version": prompt_version,
                "content": request.content,
                **request.metadata,
            },
        )
    )
    run = orchestrator.create_run(
        RunCreate(
            title=conversation.title,
            description=request.content,
            studio="text",
            project_id=conversation.project_id,
            workflow_id=conversation.workflow_id,
        )
    )
    job = orchestrator.enqueue_job(
        run.id,
        action="text.generate",
        payload={
            "prompt": request.content,
            "conversation_id": conversation.id,
            "prompt_asset_id": prompt_asset.id,
        },
        capability_req={"capability_id": "cap-reasoning", "requirements": {"required_vram_gb": 0}},
    )
    result = runtime.worker.execute_job(job)
    response_asset = None
    if result.get("asset_id"):
        response_asset = repository.get_asset(result["asset_id"])
    if response_asset is None:
        response_asset = asset_service.create_asset_from_request(
            AssetCreate(
                type="text",
                project_id=conversation.project_id,
                workflow_id=conversation.workflow_id,
                run_id=run.id,
                job_id=job.id,
                uri=f"atlas://chat/{conversation.id}/response/{prompt_version + 1}",
                metadata={
                    "kind": "response",
                    "conversation_id": conversation.id,
                    "message_version": prompt_version + 1,
                    "content": f"Generated response for: {request.content}",
                    "provider_name": result.get("provider") or "local-text",
                    **request.metadata,
                },
            )
        )
    else:
        response_asset = asset_service.update_asset(
            response_asset.id,
            {
                "metadata": {
                    **(response_asset.metadata or {}),
                    "kind": "response",
                    "conversation_id": conversation.id,
                    "message_version": prompt_version + 1,
                    "content": response_asset.metadata.get("text")
                    or response_asset.metadata.get("content")
                    or f"Generated response for: {request.content}",
                    "provider_name": result.get("provider") or "local-text",
                }
                if response_asset.metadata is not None
                else {
                    "kind": "response",
                    "conversation_id": conversation.id,
                    "message_version": prompt_version + 1,
                    "content": f"Generated response for: {request.content}",
                    "provider_name": result.get("provider") or "local-text",
                }
            },
        )
    conversation = conversation.model_copy(
        update={
            "prompt_version": prompt_version,
            "response_version": prompt_version,
            "provider_name": result.get("provider") or "local-text",
            "execution_time_ms": request.execution_time_ms,
            "tokens": request.tokens,
            "workflow_id": conversation.workflow_id,
            "prompt_asset_id": prompt_asset.id,
            "response_asset_id": response_asset.id,
            "updated_at": __import__('datetime').datetime.now(__import__('datetime').UTC),
        }
    )
    repository.update_chat_conversation(conversation)
    repository.create_chat_message(
        ChatMessage(
            id=f"message-{__import__('uuid').uuid4().hex[:8]}",
            conversation_id=request.conversation_id,
            version=prompt_version,
            role='user',
            content=request.content,
            asset_id=prompt_asset.id,
            prompt_asset_id=prompt_asset.id,
            response_asset_id=response_asset.id,
            provider_name=conversation.provider_name,
            execution_time_ms=request.execution_time_ms,
            tokens=request.tokens,
            metadata=dict(request.metadata),
        )
    )
    assistant_message = repository.create_chat_message(
        ChatMessage(
            id=f"message-{__import__('uuid').uuid4().hex[:8]}",
            conversation_id=request.conversation_id,
            version=prompt_version + 1,
            role='assistant',
            content=(response_asset.metadata or {}).get('content')
            if response_asset is not None
            else f"Generated response for: {request.content}",
            asset_id=response_asset.id,
            prompt_asset_id=prompt_asset.id,
            response_asset_id=response_asset.id,
            provider_name=conversation.provider_name,
            execution_time_ms=request.execution_time_ms,
            tokens=request.tokens,
            metadata={
                **dict(request.metadata),
                "kind": "response",
            },
        )
    )
    return assistant_message.model_dump()


@app.delete("/chat/conversation/{conversation_id}")
def delete_chat_conversation(conversation_id: str) -> dict[str, object]:
    conversation = repository.get_chat_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    repository.delete_chat_conversation(conversation_id)
    return {"status": "deleted", "conversation_id": conversation_id}


@app.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, object]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.model_dump()


@app.post("/workflows")
def create_workflow(request: WorkflowRequest) -> dict[str, object]:
    capability_request = normalize_capability_request(request.capability_req)
    if registry.get_capability(capability_request.capability_id) is None:
        raise HTTPException(
            status_code=400, detail=f"Unknown capability_id: {capability_request.capability_id}"
        )
    workflow = orchestrator.create_workflow(
        WorkflowCreate(
            project_id=request.project_id,
            name=request.name,
            description=request.description,
            studio=request.studio,
            default_action=request.default_action,
            capability_req=capability_request,
        )
    )
    definition_id = request.id or workflow.id
    workflow = workflow_engine.create_workflow(
        WorkflowDefinition(
            id=definition_id,
            name=request.name,
            project_id=request.project_id or "project-unassigned",
            workflow_id=definition_id,
            nodes=[
                WorkflowNode(
                    id=node.id,
                    action=node.action,
                    payload=dict(node.payload),
                    depends_on=list(node.depends_on),
                    input_asset_ids=list(node.input_asset_ids),
                    output_labels=list(node.output_labels),
                    capability_req=normalize_capability_request(node.capability_req),
                    retry_policy=RetryPolicy(
                        max_retries=node.max_retries,
                        retry_delay_seconds=node.retry_delay_seconds,
                        failure_strategy=(
                            FailureStrategy.CONTINUE
                            if node.failure_strategy == FailureStrategy.CONTINUE.value
                            else FailureStrategy.FAIL_FAST
                        ),
                    ),
                    condition=(
                        Condition(expression=node.condition_expression)
                        if node.condition_expression
                        else None
                    ),
                )
                for node in request.nodes
            ],
        )
    )
    return {
        "id": workflow.id,
        "workflow_id": workflow.id,
        "project_id": workflow.project_id,
        "name": workflow.name,
        "studio": request.studio,
        "default_action": request.default_action,
        "capability_req": capability_request.model_dump(),
        "nodes": [node.model_dump() for node in workflow.nodes],
    }


@app.post("/runs")
def create_run(request: RunRequest) -> dict[str, object]:
    run = orchestrator.create_run(
        RunCreate(
            title=request.title,
            description=request.description,
            studio=request.studio,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            workflow_id=request.workflow_id,
        )
    )
    return {
        "run_id": run.id,
        "status": run.status.value,
        "studio": run.studio,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "workflow_id": run.workflow_id,
    }


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, object]:
    run = repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    jobs = repository.list_jobs_by_run(run_id)
    return {
        "id": run.id,
        "title": run.title,
        "description": run.description,
        "studio": run.studio,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "workflow_id": run.workflow_id,
        "produced_asset_ids": run.produced_asset_ids,
        "status": run.status.value,
        "created_at": run.created_at.isoformat(),
        "job_count": len(jobs),
        "jobs": [
            {
                "id": job.id,
                "action": job.action,
                "status": job.status.value,
                "execution_decision_id": job.execution_decision_id,
                "payload": job.payload,
                "provider_name": job.provider_name,
                "output": job.output,
                "produced_asset_ids": job.produced_asset_ids,
            }
            for job in jobs
        ],
    }


@app.get("/providers")
def providers() -> list[dict[str, object]]:
    return [provider.model_dump() for provider in registry.list_providers()]


@app.get("/actions")
def actions() -> list[dict[str, object]]:
    return [action.model_dump() for action in registry.list_actions()]


@app.get("/commands")
def list_commands() -> list[dict[str, object]]:
    return [
        {
            "id": "c1",
            "label": "Open Mission Control",
            "kind": "navigation",
            "scope": "global",
        },
        {
            "id": "c2",
            "label": "Switch to Research Studio",
            "kind": "studio-action",
            "scope": "project",
        },
        {
            "id": "c3",
            "label": "Open Activity Center",
            "kind": "navigation",
            "scope": "global",
        },
        {
            "id": "c4",
            "label": "Run Publish Checklist",
            "kind": "publish",
            "scope": "project",
        },
    ]


@app.get("/studios")
def list_studios() -> list[dict[str, object]]:
    return [
        {"id": "s1", "name": "Research Studio", "capability": "Research", "kind": "Core"},
        {"id": "s2", "name": "Video Studio", "capability": "Media", "kind": "Core"},
        {"id": "s3", "name": "Image Studio", "capability": "Media", "kind": "Extended"},
        {"id": "s4", "name": "Product Studio", "capability": "Build", "kind": "Core"},
        {"id": "s5", "name": "Publishing Studio", "capability": "Publish", "kind": "Core"},
    ]


@app.get("/capabilities")
def list_capabilities() -> list[dict[str, object]]:
    return [capability.model_dump() for capability in registry.list_capabilities()]


@app.get("/capabilities/{capability_id}")
def get_capability(capability_id: str) -> dict[str, object]:
    capability = registry.get_capability(capability_id)
    if capability is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    return capability.model_dump()


@app.get("/capabilities/{capability_id}/recipes")
def list_capability_recipes(capability_id: str) -> list[dict[str, object]]:
    capability = registry.get_capability(capability_id)
    if capability is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    return [recipe.model_dump() for recipe in registry.list_capability_recipes(capability_id)]


@app.get("/capabilities/{capability_id}/providers")
def list_capability_providers(capability_id: str) -> list[dict[str, object]]:
    capability = registry.get_capability(capability_id)
    if capability is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    return [provider.model_dump() for provider in registry.list_compatible_providers(capability_id)]


@app.get("/capabilities/{capability_id}/executors")
def list_capability_executors(capability_id: str) -> list[str]:
    capability = registry.get_capability(capability_id)
    if capability is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    return registry.list_compatible_executors(capability_id)


@app.post("/capabilities")
def register_capability(request: CapabilitySpecRequest) -> dict[str, object]:
    capability = CapabilitySpec(
        id=request.id,
        name=request.name,
        description=request.description,
        version=request.version,
        supported_provider_kinds=list(request.supported_provider_kinds),
        supported_executor_kinds=list(request.supported_executor_kinds),
        metadata=dict(request.metadata),
    )
    existing = registry.get_capability(capability.id)
    if existing is None:
        registry.register_capability(capability)
        event_bus.publish(
            CapabilityRegistered(capability_id=capability.id, version=capability.version)
        )
    else:
        registry.update_capability(capability)
        event_bus.publish(
            CapabilityUpdated(capability_id=capability.id, version=capability.version)
        )
    return capability.model_dump()


@app.post("/recipes")
def register_recipe(request: RecipeRequest) -> dict[str, object]:
    capability = registry.get_capability(request.capability_id)
    if capability is None:
        raise HTTPException(status_code=404, detail="Capability not found")

    recipe = RecipeSpec(
        id=request.id,
        capability_id=request.capability_id,
        name=request.name,
        description=request.description,
        version=request.version,
        profile=request.profile,
        parameters=dict(request.parameters),
        metadata=dict(request.metadata),
    )
    registry.register_capability_recipe(recipe)
    event_bus.publish(
        RecipeRegistered(
            recipe_id=recipe.id, capability_id=recipe.capability_id, version=recipe.version
        )
    )
    return recipe.model_dump()


@app.post("/capabilities/{capability_id}/recipes/{recipe_id}/select")
def select_recipe(
    capability_id: str, recipe_id: str, request: RecipeSelectionRequest
) -> dict[str, object]:
    capability = registry.get_capability(capability_id)
    if capability is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    recipe = registry.get_capability_recipe(recipe_id)
    if recipe is None or recipe.capability_id != capability_id:
        raise HTTPException(status_code=404, detail="Recipe not found")
    event_bus.publish(
        RecipeSelected(recipe_id=recipe_id, capability_id=capability_id, run_id=request.run_id)
    )
    return {
        "status": "selected",
        "capability_id": capability_id,
        "recipe_id": recipe_id,
        "run_id": request.run_id,
    }


@app.post("/execution-policy/evaluate")
def evaluate_execution_policy(request: ExecutionPolicyEvaluateRequest) -> dict[str, object]:
    capability_request = normalize_capability_request(request.capability_req)
    if registry.get_capability(capability_request.capability_id) is None:
        raise HTTPException(
            status_code=400, detail=f"Unknown capability_id: {capability_request.capability_id}"
        )
    try:
        decision = execution_policy.evaluate(
            capability_request=capability_request,
            runtime_context=request.runtime_context,
            workspace_preferences=dict(request.workspace_preferences),
            project_preferences=dict(request.project_preferences),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return decision.model_dump()


@app.get("/execution-policy/decision/{decision_id}")
def get_execution_policy_decision(decision_id: str) -> dict[str, object]:
    decision = execution_policy.get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Execution decision not found")
    return decision.model_dump()


@app.get("/runs")
def list_runs() -> list[dict[str, object]]:
    runs = repository.list_runs()
    return [
        {
            "id": run.id,
            "title": run.title,
            "description": run.description,
            "studio": run.studio,
            "workspace_id": run.workspace_id,
            "project_id": run.project_id,
            "workflow_id": run.workflow_id,
            "produced_asset_ids": run.produced_asset_ids,
            "status": run.status.value,
        }
        for run in runs
    ]


@app.get("/workflows")
def list_workflows() -> list[dict[str, object]]:
    return [workflow.model_dump() for workflow in workflow_engine.list_workflows()]


@app.get("/workflow/{workflow_id}")
def get_workflow_definition(workflow_id: str) -> dict[str, object]:
    workflow = workflow_engine.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow.model_dump()


@app.post("/workflow/{workflow_id}/execute")
def execute_workflow_definition(workflow_id: str, request: WorkflowExecuteRequest) -> dict[str, object]:
    workflow = workflow_engine.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    try:
        execution = workflow_engine.execute_workflow(workflow_id, request.run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return execution.model_dump()


@app.get("/execution/{execution_id}")
def get_execution(execution_id: str) -> dict[str, object]:
    execution = workflow_engine.get_execution(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution.model_dump()


@app.get("/execution/{execution_id}/timeline")
def get_execution_timeline(execution_id: str) -> list[dict[str, object]]:
    execution = workflow_engine.get_execution(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    try:
        return workflow_engine.get_execution_timeline(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/{run_id}/jobs")
def list_jobs(run_id: str) -> list[dict[str, object]]:
    jobs = repository.list_jobs_by_run(run_id)
    return [
        {
            "id": job.id,
            "run_id": job.run_id,
            "action": job.action,
            "status": job.status.value,
            "execution_decision_id": job.execution_decision_id,
            "payload": job.payload,
            "provider_name": job.provider_name,
            "output": job.output,
            "produced_asset_ids": job.produced_asset_ids,
        }
        for job in jobs
    ]


@app.post("/assets")
def create_asset(request: AssetRequest) -> dict[str, object]:
    asset = asset_service.create_asset_from_request(
        AssetCreate(
            type=request.type,
            project_id=request.project_id,
            workflow_id=request.workflow_id,
            run_id=request.run_id,
            job_id=request.job_id,
            parent_asset_id=request.parent_asset_id,
            version=request.version,
            uri=request.uri,
            mime_type=request.mime_type,
            file_size=request.file_size,
            content_hash=request.content_hash,
            metadata=request.metadata,
            tags=request.tags,
            source_asset_ids=request.source_asset_ids,
        )
    )
    return asset.model_dump()


@app.get("/assets")
def list_assets(
    project_id: str | None = None, run_id: str | None = None, job_id: str | None = None
) -> list[dict[str, object]]:
    if run_id is not None:
        assets = repository.list_assets_by_run(run_id)
    elif job_id is not None:
        assets = repository.list_assets_by_job(job_id)
    else:
        assets = repository.list_assets(project_id=project_id)
    return [asset.model_dump() for asset in assets]


@app.get("/activities")
def list_activities(domain: str | None = None) -> list[dict[str, object]]:
    jobs = repository.list_jobs()
    assets = repository.list_assets()
    activities: list[dict[str, object]] = []

    for job in jobs:
        activities.append(
            {
                "id": job.id,
                "name": job.action,
                "projectId": repository.get_run(job.run_id).project_id if repository.get_run(job.run_id) else "project-unassigned",
                "domain": _job_domain(job.action),
                "state": _job_state(job.status.value),
                "severity": _job_severity(job.status.value),
                "progress": _job_progress(job.status.value),
                "elapsed": "active",
            }
        )

    for asset in assets:
        activities.append(
            {
                "id": f"import-{asset.id}",
                "name": asset.metadata.get("original_filename") or asset.id,
                "projectId": asset.project_id,
                "domain": "uploads",
                "state": "succeeded",
                "severity": "info",
                "progress": 100,
                "elapsed": "completed",
            }
        )

    if domain is not None:
        activities = [item for item in activities if item["domain"] == domain]

    return activities


@app.get("/notifications")
def list_notifications() -> list[dict[str, object]]:
    notifications: list[dict[str, object]] = []
    jobs = repository.list_jobs()
    assets = repository.list_assets()

    for job in jobs:
        if job.status.value == "failed":
            notifications.append(
                {
                    "id": f"job-failed-{job.id}",
                    "title": "Job Failure",
                    "detail": f"{job.action} failed for run {job.run_id}.",
                    "severity": "warning",
                    "pinned": True,
                }
            )

    if assets:
        latest_asset = assets[0]
        notifications.append(
            {
                "id": f"asset-created-{latest_asset.id}",
                "title": "Asset Imported",
                "detail": f"{latest_asset.metadata.get('original_filename') or latest_asset.id} is ready.",
                "severity": "info",
                "pinned": False,
            }
        )

    return notifications


@app.get("/assets/{asset_id}")
def get_asset(asset_id: str) -> dict[str, object]:
    asset = repository.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset.model_dump()


@app.delete("/assets/{asset_id}")
def delete_asset(asset_id: str) -> dict[str, object]:
    asset = repository.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset_service.delete_asset(asset_id)
    return {"status": "deleted", "asset_id": asset_id}


@app.get("/projects/{project_id}/assets")
def list_project_assets(project_id: str) -> list[dict[str, object]]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return [asset.model_dump() for asset in repository.list_assets(project_id=project_id)]


@app.post("/assets/import")
async def import_asset(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    workflow_id: str | None = Form(default=None),
    run_id: str | None = Form(default=None),
    job_id: str | None = Form(default=None),
    asset_type: str | None = Form(default=None),
    tags: str = Form(default="[]"),
) -> dict[str, object]:
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    payload = await file.read()
    resolved_type = asset_type or _deduce_import_asset_type(file.filename or "", file.content_type)
    parsed_tags = _parse_tags(tags)
    asset = asset_service.create_asset_from_request(
        AssetCreate(
            type=resolved_type,
            project_id=project_id,
            workflow_id=workflow_id,
            run_id=run_id,
            job_id=job_id,
            uri=file.filename or "uploaded-asset",
            mime_type=file.content_type,
            file_size=len(payload),
            metadata={
                "original_filename": file.filename,
                "imported_via": "desktop",
            },
            tags=parsed_tags,
            search_index={"filename": file.filename or ""},
        ),
        payload=payload,
    )
    return asset.model_dump()


@app.post("/workflow-engine/workflows")
def create_workflow_definition(request: WorkflowDefinitionRequest) -> dict[str, object]:
    definition = _to_workflow_definition(request)
    created = workflow_engine.create_workflow(definition)
    return created.model_dump()


@app.post("/workflow-engine/workflows/validate")
def validate_workflow_definition(request: WorkflowDefinitionRequest) -> dict[str, object]:
    definition = _to_workflow_definition(request)
    result = workflow_engine.validate_workflow(definition)
    return {
        "valid": result.valid,
        "errors": result.errors,
        "plan": result.plan.model_dump() if result.plan is not None else None,
    }


@app.post("/workflow-engine/workflows/{workflow_definition_id}/execute")
def execute_workflow_definition(
    workflow_definition_id: str, request: WorkflowExecuteRequest
) -> dict[str, object]:
    execution = workflow_engine.execute_workflow(
        workflow_definition_id=workflow_definition_id, run_id=request.run_id
    )
    return execution.model_dump()


@app.post("/workflow/{workflow_id}/execute")
def execute_workflow_api(workflow_id: str) -> dict[str, object]:
    workflow = workflow_engine.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run = orchestrator.create_run(
        RunCreate(
            title=workflow.name,
            description=workflow.name,
            studio="core",
            project_id=workflow.project_id,
            workflow_id=workflow.workflow_id,
        )
    )
    execution = workflow_engine.execute_workflow(workflow_definition_id=workflow_id, run_id=run.id)
    return execution.model_dump()


@app.get("/execution/{execution_id}")
def get_execution(execution_id: str) -> dict[str, object]:
    execution = workflow_engine.get_execution(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution.model_dump()


@app.get("/execution/{execution_id}/timeline")
def get_execution_timeline(execution_id: str) -> list[dict[str, object]]:
    try:
        return workflow_engine.get_execution_timeline(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/workflow-engine/executions/{execution_id}/pause")
def pause_workflow_execution(execution_id: str) -> dict[str, object]:
    try:
        execution = workflow_engine.pause_execution(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return execution.model_dump()


@app.post("/workflow-engine/executions/{execution_id}/resume")
def resume_workflow_execution(execution_id: str) -> dict[str, object]:
    try:
        execution = workflow_engine.resume_execution(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return execution.model_dump()


@app.post("/workflow-engine/executions/{execution_id}/cancel")
def cancel_workflow_execution(execution_id: str) -> dict[str, object]:
    try:
        execution = workflow_engine.cancel_execution(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return execution.model_dump()


@app.get("/workflow-engine/executions/{execution_id}/plan")
def inspect_execution_plan(execution_id: str) -> dict[str, object]:
    try:
        plan = workflow_engine.inspect_execution_plan(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return plan.model_dump()


@app.get("/organizations")
def list_organizations(identity_id: str | None = None) -> list[dict[str, object]]:
    orgs = organization_service.list_organizations(identity_id=identity_id)
    return [org.model_dump(mode="json") for org in orgs]


@app.post("/organizations")
def create_organization(request: OrganizationCreateRequest) -> dict[str, object]:
    try:
        organization = organization_service.create_organization(
            name=request.name,
            slug=request.slug,
            description=request.description,
            branding=request.branding,
            license=request.license,
            actor_id=request.actor_id,
        )
    except OrganizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return organization.model_dump(mode="json")


@app.get("/organizations/{organization_id}")
def get_organization(organization_id: str) -> dict[str, object]:
    organization = organization_service.get_organization(organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    payload = organization.model_dump(mode="json")
    payload["teams"] = [
        t.model_dump(mode="json") for t in organization_service.list_teams(organization_id)
    ]
    payload["members"] = [
        m.model_dump(mode="json") for m in organization_service.list_members(organization_id)
    ]
    payload["roles"] = [
        r.model_dump(mode="json") for r in organization_service.list_roles(organization_id)
    ]
    payload["policy_sets"] = [
        p.model_dump(mode="json")
        for p in organization_service.list_policy_sets(organization_id=organization_id)
    ]
    return payload


@app.put("/organizations/{organization_id}")
def update_organization(
    organization_id: str, request: OrganizationUpdateRequest
) -> dict[str, object]:
    changes = request.model_dump(exclude_unset=True, exclude_none=True, exclude={"actor_id"})
    try:
        organization = organization_service.update_organization(
            organization_id, changes, actor_id=request.actor_id
        )
    except OrganizationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return organization.model_dump(mode="json")


@app.post("/organizations/{organization_id}/members")
def add_organization_member(
    organization_id: str, request: MemberAddRequest
) -> dict[str, object]:
    try:
        membership = organization_service.add_member(
            organization_id=organization_id,
            identity_id=request.identity_id,
            role_ids=request.role_ids,
            team_ids=request.team_ids,
            scope=request.scope,
            scope_id=request.scope_id,
            expires_at=request.expires_at,
            actor_id=request.actor_id,
        )
    except OrganizationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return membership.model_dump(mode="json")


@app.get("/organizations/{organization_id}/members")
def list_organization_members(organization_id: str) -> list[dict[str, object]]:
    return [m.model_dump(mode="json") for m in organization_service.list_members(organization_id)]


@app.put("/organizations/{organization_id}/members/{membership_id}")
def update_organization_member(
    organization_id: str, membership_id: str, request: MembershipUpdateRequest
) -> dict[str, object]:
    changes = request.model_dump(exclude_unset=True, exclude_none=True, exclude={"actor_id"})
    try:
        membership = organization_service.update_membership(
            membership_id, changes, actor_id=request.actor_id
        )
    except OrganizationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return membership.model_dump(mode="json")


@app.delete("/organizations/{organization_id}/members/{membership_id}")
def remove_organization_member(
    organization_id: str, membership_id: str, actor_id: str = "system"
) -> dict[str, object]:
    try:
        organization_service.remove_member(organization_id, membership_id, actor_id=actor_id)
    except OrganizationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"membership_id": membership_id, "removed": True}


@app.get("/organizations/{organization_id}/permissions/{identity_id}")
def resolve_identity_permissions(
    organization_id: str, identity_id: str
) -> dict[str, object]:
    resolution = organization_service.resolve_permissions(identity_id, organization_id)
    return resolution.model_dump(mode="json")


@app.post("/organizations/{organization_id}/workers/{worker_id}")
def assign_worker_to_organization(
    organization_id: str, worker_id: str, request: WorkerAssignRequest | None = None
) -> dict[str, object]:
    target = request.organization_id if request else organization_id
    actor = request.actor_id if request else "system"
    try:
        organization_service.assign_worker(worker_id, target, actor_id=actor)
    except OrganizationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"worker_id": worker_id, "organization_id": target}


@app.get("/roles")
def list_roles(organization_id: str | None = None) -> list[dict[str, object]]:
    return [r.model_dump(mode="json") for r in organization_service.list_roles(organization_id)]


@app.post("/roles")
def create_role(request: RoleCreateRequest) -> dict[str, object]:
    role = organization_service.create_role(
        name=request.name,
        permissions=request.permissions,
        organization_id=request.organization_id,
        description=request.description,
        actor_id=request.actor_id,
    )
    return role.model_dump(mode="json")


@app.put("/roles/{role_id}")
def update_role(role_id: str, request: RoleUpdateRequest) -> dict[str, object]:
    try:
        role = organization_service.update_role(
            role_id, request.permissions, actor_id=request.actor_id
        )
    except OrganizationError as exc:
        status = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return role.model_dump(mode="json")


@app.get("/permissions")
def list_permissions() -> list[dict[str, str]]:
    return organization_service.list_permissions()


@app.get("/teams")
def list_teams(organization_id: str | None = None) -> list[dict[str, object]]:
    return [t.model_dump(mode="json") for t in organization_service.list_teams(organization_id)]


@app.post("/teams")
def create_team(request: TeamCreateRequest) -> dict[str, object]:
    try:
        team = organization_service.create_team(
            organization_id=request.organization_id,
            name=request.name,
            kind=request.kind,
            description=request.description,
            actor_id=request.actor_id,
        )
    except OrganizationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return team.model_dump(mode="json")


@app.get("/policies")
def list_policies(
    organization_id: str | None = None, domain: PolicyDomain | None = None
) -> list[dict[str, object]]:
    policy_sets = organization_service.list_policy_sets(
        organization_id=organization_id, domain=domain
    )
    return [p.model_dump(mode="json") for p in policy_sets]


@app.put("/policies")
def upsert_policy(request: PolicySetRequest) -> dict[str, object]:
    payload = request.model_dump(exclude={"actor_id", "id"})
    policy_set = PolicySet(**payload) if request.id is None else PolicySet(id=request.id, **payload)
    stored = organization_service.upsert_policy_set(policy_set, actor_id=request.actor_id)
    return stored.model_dump(mode="json")


@app.get("/policies/resolve")
def resolve_policy(
    organization_id: str,
    domain: PolicyDomain,
    workspace_id: str | None = None,
    project_id: str | None = None,
    object_id: str | None = None,
) -> dict[str, object]:
    resolved = organization_service.resolve_policy(
        domain=domain,
        organization_id=organization_id,
        workspace_id=workspace_id,
        project_id=project_id,
        object_id=object_id,
    )
    return resolved.model_dump(mode="json")


@app.get("/audit")
def list_audit(
    organization_id: str | None = None,
    action: AuditAction | None = None,
    actor_id: str | None = None,
    target_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, object]]:
    records = audit_service.list_records(
        organization_id=organization_id,
        action=action,
        actor_id=actor_id,
        target_id=target_id,
        limit=limit,
    )
    return [r.model_dump(mode="json") for r in records]


@app.get("/audit/{audit_id}")
def get_audit_record(audit_id: str) -> dict[str, object]:
    record = audit_service.get(audit_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Audit record not found")
    return record.model_dump(mode="json")


@app.get("/identities")
def list_identities() -> list[dict[str, object]]:
    return [i.model_dump(mode="json") for i in identity_service.list_identities()]


@app.post("/identities")
def create_identity(request: IdentityCreateRequest) -> dict[str, object]:
    identity = identity_service.create_identity(
        subject=request.subject,
        display_name=request.display_name,
        email=request.email,
        provider=request.provider,
    )
    return identity.model_dump(mode="json")


@app.get("/identity-providers")
def list_identity_providers() -> list[dict[str, object]]:
    return identity_service.providers()


@app.get("/workers")
def list_workers(status: WorkerState | None = None) -> list[dict[str, object]]:
    return [w.model_dump(mode="json") for w in worker_registry.list_workers(status=status)]


@app.post("/workers/register")
def register_worker(request: WorkerRegisterRequest) -> dict[str, object]:
    worker = worker_registry.register(
        WorkerRegistration(
            hostname=request.hostname,
            display_name=request.display_name,
            platform=request.platform,
            resources=request.resources,
            capabilities=list(request.capabilities),
            max_concurrency=request.max_concurrency,
            version=request.version,
            tags=list(request.tags),
            metadata=dict(request.metadata),
            worker_id=request.worker_id,
        )
    )
    return worker.model_dump(mode="json")


@app.post("/workers/heartbeat")
def worker_heartbeat(request: WorkerHeartbeatRequest) -> dict[str, object]:
    try:
        worker = heartbeat_service.record(
            HeartbeatReport(
                worker_id=request.worker_id,
                status=request.status,
                current_load=request.current_load,
                metrics=request.metrics,
                metadata=dict(request.metadata),
            )
        )
    except WorkerRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return worker.model_dump(mode="json")


@app.get("/workers/{worker_id}")
def get_worker(worker_id: str) -> dict[str, object]:
    worker = worker_registry.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    payload = worker.model_dump(mode="json")
    payload["reservations"] = [
        r.model_dump(mode="json") for r in lease_manager.list_active_reservations(worker_id)
    ]
    payload["leases"] = [
        lease.model_dump(mode="json") for lease in lease_manager.list_active_leases(worker_id)
    ]
    payload["heartbeats"] = [
        hb.model_dump(mode="json") for hb in heartbeat_service.history(worker_id, limit=20)
    ]
    payload["executions"] = [
        e.model_dump(mode="json") for e in repository.list_executions_by_worker(worker_id)
    ]
    return payload


@app.post("/workers/{worker_id}/pause")
def pause_worker(worker_id: str, request: WorkerActionRequest | None = None) -> dict[str, object]:
    return _worker_action(worker_registry.pause, worker_id, request)


@app.post("/workers/{worker_id}/resume")
def resume_worker(worker_id: str, request: WorkerActionRequest | None = None) -> dict[str, object]:
    return _worker_action(worker_registry.resume, worker_id, request)


@app.post("/workers/{worker_id}/drain")
def drain_worker(worker_id: str, request: WorkerActionRequest | None = None) -> dict[str, object]:
    return _worker_action(worker_registry.drain, worker_id, request)


@app.get("/cluster")
def get_cluster() -> dict[str, object]:
    return cluster_state.snapshot().model_dump(mode="json")


@app.get("/cluster/health")
def get_cluster_health() -> dict[str, object]:
    return cluster_state.health().model_dump(mode="json")


@app.get("/cluster/load")
def get_cluster_load() -> dict[str, object]:
    return cluster_state.load().model_dump(mode="json")


@app.get("/cluster/reservations")
def list_cluster_reservations(worker_id: str | None = None) -> list[dict[str, object]]:
    return [
        r.model_dump(mode="json") for r in repository.list_reservations(worker_id=worker_id)
    ]


@app.get("/cluster/leases")
def list_cluster_leases(worker_id: str | None = None) -> list[dict[str, object]]:
    return [lease.model_dump(mode="json") for lease in repository.list_leases(worker_id=worker_id)]


@app.get("/cluster/waiting-placement")
def list_waiting_placement() -> list[dict[str, object]]:
    return [e.model_dump(mode="json") for e in agent_runtime.list_waiting_placement()]


@app.post("/cluster/sweep")
def sweep_cluster() -> dict[str, object]:
    """Runs the failure detectors and recovers anything stranded. Idempotent."""
    offline = heartbeat_service.detect_timeouts()
    expired = lease_manager.expire_due()
    recovered = [
        agent_runtime.recover_execution(lease.execution_id, reason="lease expired").execution_id
        for lease in expired
    ]
    return {
        "workers_marked_offline": [w.id for w in offline],
        "leases_expired": [lease.id for lease in expired],
        "executions_recovered": recovered,
    }


@app.post("/cluster/executions/{execution_id}/recover")
def recover_execution(execution_id: str, reason: str = "manual intervention") -> dict[str, object]:
    try:
        execution = agent_runtime.recover_execution(execution_id, reason=reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return execution.model_dump(mode="json")


@app.post("/cluster/executions/{execution_id}/retry-placement")
def retry_placement(execution_id: str) -> dict[str, object]:
    try:
        execution = agent_runtime.resume_after_placement(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return execution.model_dump(mode="json")


def _worker_action(
    operation: object, worker_id: str, request: WorkerActionRequest | None
) -> dict[str, object]:
    actor = request.actor if request else "system"
    try:
        worker = operation(worker_id, actor)  # type: ignore[operator]
    except WorkerRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return worker.model_dump(mode="json")


@app.post("/approvals")
def create_approval(request: ApprovalCreateRequest) -> dict[str, object]:
    context = ApprovalContext(
        action=request.action,
        scopes=list(request.scopes),
        estimated_cost=request.estimated_cost,
        project_id=request.project_id,
        workspace_id=request.workspace_id,
        agent_id=request.agent_id,
        execution_id=request.execution_id,
        schedule_id=request.schedule_id,
        entry_id=request.entry_id,
        requested_by=request.requested_by,
        payload=dict(request.payload),
    )
    approval = approval_service.create_request(
        title=request.title,
        context=context,
        priority=request.priority,
        run_id=request.run_id,
        job_id=request.job_id,
        asset_id=request.asset_id,
        metadata=dict(request.metadata),
    )
    return approval.model_dump(mode="json")


@app.get("/approvals")
def list_approvals(
    state: ApprovalState | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    pending_only: bool = False,
) -> list[dict[str, object]]:
    if pending_only:
        approvals = approval_service.list_pending(
            project_id=project_id, workspace_id=workspace_id
        )
    else:
        approvals = approval_service.list_requests(
            state=state, project_id=project_id, workspace_id=workspace_id
        )
    return [approval.model_dump(mode="json") for approval in approvals]


@app.get("/approvals/history")
def list_approval_history(approval_id: str | None = None) -> list[dict[str, object]]:
    events = approval_service.list_history(approval_id=approval_id)
    return [event.model_dump(mode="json") for event in events]


@app.get("/approvals/waiting-executions")
def list_executions_waiting_approval() -> list[dict[str, object]]:
    return [
        execution.model_dump(mode="json")
        for execution in agent_runtime.list_waiting_approval()
    ]


@app.get("/approvals/{approval_id}")
def get_approval(approval_id: str) -> dict[str, object]:
    approval = approval_service.get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return approval.model_dump(mode="json")


@app.post("/approvals/{approval_id}/approve")
def approve_approval(approval_id: str, request: ApprovalDecisionRequest) -> dict[str, object]:
    return _decide(approval_service.approve, approval_id, request)


@app.post("/approvals/{approval_id}/reject")
def reject_approval(approval_id: str, request: ApprovalDecisionRequest) -> dict[str, object]:
    return _decide(approval_service.reject, approval_id, request)


@app.post("/approvals/{approval_id}/request-changes")
def request_changes_approval(
    approval_id: str, request: ApprovalDecisionRequest
) -> dict[str, object]:
    return _decide(approval_service.request_changes, approval_id, request)


@app.post("/approvals/{approval_id}/cancel")
def cancel_approval(approval_id: str, request: ApprovalDecisionRequest) -> dict[str, object]:
    return _decide(approval_service.cancel, approval_id, request)


@app.post("/approvals/{approval_id}/view")
def view_approval(approval_id: str, request: ApprovalViewRequest) -> dict[str, object]:
    try:
        approval = approval_service.mark_viewed(approval_id, request.actor)
    except ApprovalError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return approval.model_dump(mode="json")


@app.post("/approvals/{approval_id}/escalate")
def escalate_approval(approval_id: str, request: ApprovalEscalateRequest) -> dict[str, object]:
    try:
        approval = approval_service.escalate(approval_id, request.actor, request.escalated_to)
    except ApprovalError as exc:
        raise HTTPException(status_code=_approval_status(exc), detail=str(exc)) from exc
    return approval.model_dump(mode="json")


@app.post("/approvals/{approval_id}/resume-execution")
def resume_execution_after_approval(approval_id: str) -> dict[str, object]:
    approval = approval_service.get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.state is not ApprovalState.APPROVED:
        raise HTTPException(
            status_code=409,
            detail=f"Approval is {approval.state.value}; execution may not resume",
        )
    if not approval.execution_id:
        raise HTTPException(status_code=409, detail="Approval has no linked execution")
    try:
        execution = agent_runtime.resume_after_approval(approval.execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return execution.model_dump(mode="json")


@app.get("/approval-policies")
def list_approval_policies(
    project_id: str | None = None, workspace_id: str | None = None
) -> list[dict[str, object]]:
    policies = approval_service.list_policies(
        project_id=project_id, workspace_id=workspace_id
    )
    return [policy.model_dump(mode="json") for policy in policies]


@app.put("/approval-policies")
def upsert_approval_policy(request: ApprovalPolicyRequest) -> dict[str, object]:
    payload = request.model_dump(exclude_none=True)
    payload.pop("id", None)
    policy = ApprovalPolicy(**payload) if request.id is None else ApprovalPolicy(
        id=request.id, **payload
    )
    return approval_service.upsert_policy(policy).model_dump(mode="json")


def _decide(
    operation: object, approval_id: str, request: ApprovalDecisionRequest
) -> dict[str, object]:
    try:
        approval = operation(approval_id, request.actor, request.comment)  # type: ignore[operator]
    except ApprovalError as exc:
        raise HTTPException(status_code=_approval_status(exc), detail=str(exc)) from exc
    return approval.model_dump(mode="json")


def _approval_status(exc: ApprovalError) -> int:
    if isinstance(exc, SelfApprovalError):
        return 403
    if "not found" in str(exc):
        return 404
    return 409


@app.get("/automation")
def list_automation_rules(
    project_id: str | None = None, workspace_id: str | None = None
) -> list[dict[str, object]]:
    rules = automation_engine.list_rules(project_id=project_id, workspace_id=workspace_id)
    return [rule.model_dump(mode="json") for rule in rules]


@app.post("/automation")
def create_automation_rule(request: AutomationRuleRequest) -> dict[str, object]:
    try:
        rule = automation_engine.create_rule(
            name=request.name,
            description=request.description,
            trigger=request.trigger,
            conditions=request.conditions,
            actions=request.actions,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            schedule=request.schedule,
            priority=request.priority,
            dry_run=request.dry_run,
            actor=request.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return rule.model_dump(mode="json")


@app.get("/automation/runs")
def list_automation_runs(rule_id: str | None = None) -> list[dict[str, object]]:
    return [run.model_dump(mode="json") for run in automation_engine.list_runs(rule_id=rule_id)]


@app.get("/automation/logs")
def list_automation_logs(
    run_id: str | None = None, rule_id: str | None = None
) -> list[dict[str, object]]:
    logs = automation_engine.list_logs(run_id=run_id, rule_id=rule_id)
    return [log.model_dump(mode="json") for log in logs]


@app.get("/automation/conflicts")
def list_automation_conflicts(
    project_id: str | None = None, workspace_id: str | None = None
) -> list[dict[str, object]]:
    return automation_engine.detect_conflicts(project_id=project_id, workspace_id=workspace_id)


@app.get("/automation/{rule_id}")
def get_automation_rule(rule_id: str) -> dict[str, object]:
    rule = automation_engine.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Automation rule not found")
    return rule.model_dump(mode="json")


@app.put("/automation/{rule_id}")
def update_automation_rule(rule_id: str, request: AutomationRuleUpdateRequest) -> dict[str, object]:
    changes = request.model_dump(exclude_unset=True, exclude={"actor"})
    try:
        rule = automation_engine.update_rule(rule_id, changes, actor=request.actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return rule.model_dump(mode="json")


@app.delete("/automation/{rule_id}")
def delete_automation_rule(rule_id: str, actor: str = "system") -> dict[str, object]:
    try:
        automation_engine.delete_rule(rule_id, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"rule_id": rule_id, "deleted": True}


@app.post("/automation/{rule_id}/enable")
def enable_automation_rule(rule_id: str, actor: str = "system") -> dict[str, object]:
    try:
        rule = automation_engine.enable_rule(rule_id, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return rule.model_dump(mode="json")


@app.post("/automation/{rule_id}/disable")
def disable_automation_rule(rule_id: str, actor: str = "system") -> dict[str, object]:
    try:
        rule = automation_engine.disable_rule(rule_id, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return rule.model_dump(mode="json")


@app.post("/automation/{rule_id}/run")
def run_automation_rule(rule_id: str, request: AutomationRunRequest) -> dict[str, object]:
    try:
        run = automation_engine.run_rule(
            rule_id,
            trigger_data=request.trigger_data,
            agent_id=request.agent_id,
            actor=request.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return run.model_dump(mode="json")


@app.post("/automation/{rule_id}/dry-run")
def dry_run_automation_rule(rule_id: str, request: AutomationRunRequest) -> dict[str, object]:
    try:
        run = automation_engine.run_rule(
            rule_id,
            trigger_data=request.trigger_data,
            agent_id=request.agent_id,
            actor=request.actor,
            dry_run=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return run.model_dump(mode="json")


@app.get("/automation/{rule_id}/history")
def get_automation_history(rule_id: str) -> list[dict[str, object]]:
    if automation_engine.get_rule(rule_id) is None:
        raise HTTPException(status_code=404, detail="Automation rule not found")
    return [run.model_dump(mode="json") for run in automation_engine.list_runs(rule_id=rule_id)]


@app.get("/automation/{rule_id}/state")
def get_automation_state(rule_id: str) -> dict[str, object]:
    try:
        state = automation_engine.get_state(rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return state.model_dump(mode="json")


def _to_workflow_definition(request: WorkflowDefinitionRequest) -> WorkflowDefinition:
    nodes: list[WorkflowNode] = []
    for item in request.nodes:
        failure_strategy = FailureStrategy.FAIL_FAST
        if item.failure_strategy == FailureStrategy.CONTINUE.value:
            failure_strategy = FailureStrategy.CONTINUE
        nodes.append(
            WorkflowNode(
                id=item.id,
                action=item.action,
                payload=dict(item.payload),
                depends_on=list(item.depends_on),
                input_asset_ids=list(item.input_asset_ids),
                output_labels=list(item.output_labels),
                capability_req=normalize_capability_request(item.capability_req),
                retry_policy=RetryPolicy(
                    max_retries=item.max_retries,
                    retry_delay_seconds=item.retry_delay_seconds,
                    failure_strategy=failure_strategy,
                ),
                condition=(
                    Condition(expression=item.condition_expression)
                    if item.condition_expression
                    else None
                ),
            )
        )
    return WorkflowDefinition(
        id=request.id,
        name=request.name,
        project_id=request.project_id,
        workflow_id=request.workflow_id,
        nodes=nodes,
    )


def _parse_tags(tags: str) -> list[str]:
    try:
        parsed = __import__("json").loads(tags)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except Exception:
        pass
    return []


def _deduce_import_asset_type(filename: str, mime_type: str | None) -> str:
    lower_name = filename.lower()
    suffix = Path(lower_name).suffix
    if mime_type and mime_type.startswith("image/"):
        return "image"
    if suffix in {".md", ".txt", ".rtf"}:
        return "text"
    if suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".toml", ".rs", ".go"}:
        return "code"
    if suffix in {".pdf", ".doc", ".docx"}:
        return "document"
    return "document"


def _job_domain(action: str) -> str:
    if action.startswith("image."):
        return "rendering"
    if action.startswith("text."):
        return "research"
    if action.startswith("code."):
        return "agent"
    return "uploads"


def _job_state(status: str) -> str:
    return {
        "queued": "queued",
        "running": "running",
        "paused": "blocked",
        "failed": "failed_recoverable",
        "completed": "succeeded",
        "cancelled": "canceled",
    }.get(status, "queued")


def _job_severity(status: str) -> str:
    return {
        "failed": "warning",
        "paused": "attention",
        "running": "info",
        "completed": "info",
        "queued": "info",
        "cancelled": "warning",
    }.get(status, "info")


def _job_progress(status: str) -> int:
    return {
        "queued": 5,
        "running": 50,
        "paused": 50,
        "failed": 100,
        "completed": 100,
        "cancelled": 100,
    }.get(status, 0)
