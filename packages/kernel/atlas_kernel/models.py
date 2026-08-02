from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActionSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    name: str
    description: str
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")


class ProviderSpec(BaseModel):
    name: str
    kind: str
    is_local: bool = False
    cost_per_unit: float = 0.0
    p50_latency_ms: int = 0
    quality_score: float = 0.0
    vram_gb: int = 0


class ExecutorSpec(BaseModel):
    id: str
    kind: str
    is_local: bool = True
    health: str = "healthy"
    max_vram_gb: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelSpec(BaseModel):
    id: str
    provider_id: str
    capability_ids: list[str] = Field(default_factory=list)
    quality_score: float = 0.0
    latency_ms: int = 0
    cost_per_unit: float = 0.0
    supports_streaming: bool = False
    commercial_use: bool = True
    private_execution: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


def _legacy_kind_to_capability_id(kind: str) -> str:
    normalized = kind.strip().lower()
    if normalized == "llm":
        return "cap-reasoning"
    if normalized == "code":
        return "cap-code-generation"
    if normalized == "image":
        return "cap-image-generation"
    return f"cap-{normalized}"


class CapabilityRequest(BaseModel):
    capability_id: str = "cap-image-generation"
    recipe_id: str | None = None
    requirements: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_requirements(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        if "capability_id" in value or "requirements" in value or "recipe_id" in value:
            return value

        if "kind" in value or "required_vram_gb" in value:
            kind = str(value.get("kind", "image"))
            requirements = {k: v for k, v in value.items() if k != "kind"}
            return {
                "capability_id": _legacy_kind_to_capability_id(kind),
                "requirements": requirements,
            }

        return value


def normalize_capability_request(
    value: CapabilityRequest | dict[str, Any] | None,
    default_capability_id: str = "cap-image-generation",
) -> CapabilityRequest:
    if isinstance(value, CapabilityRequest):
        return value
    if isinstance(value, dict):
        request = CapabilityRequest.model_validate(value)
        if not request.capability_id:
            request.capability_id = default_capability_id
        return request
    return CapabilityRequest(capability_id=default_capability_id)


class CapabilitySpec(BaseModel):
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    supported_provider_kinds: list[str] = Field(default_factory=list)
    supported_executor_kinds: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecipeSpec(BaseModel):
    id: str
    capability_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    profile: str = "default"
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeContext(BaseModel):
    available_gpu_vram_gb: int = 0
    cpu_available: float = 1.0
    memory_available_gb: int = 0
    queue_length: int = 0
    offline_mode: bool = False
    cloud_available: bool = True
    provider_availability: dict[str, bool] = Field(default_factory=dict)
    executor_health: dict[str, str] = Field(default_factory=dict)
    workspace_defaults: dict[str, Any] = Field(default_factory=dict)
    project_defaults: dict[str, Any] = Field(default_factory=dict)
    current_load: float = 0.0


class ExecutionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    capability_id: str
    recipe_id: str | None = None
    executor_id: str
    provider_id: str
    model_id: str | None = None
    reason: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkspaceCreate(BaseModel):
    name: str
    description: str = ""


class Workspace(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectCreate(BaseModel):
    workspace_id: str | None = None
    name: str
    description: str = ""


class Project(BaseModel):
    id: str
    workspace_id: str | None = None
    name: str
    description: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatConversationCreate(BaseModel):
    project_id: str
    title: str
    pinned: bool = False
    parent_conversation_id: str | None = None
    workflow_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatConversation(BaseModel):
    id: str
    project_id: str
    title: str
    pinned: bool = False
    prompt_version: int = 0
    response_version: int = 0
    provider_name: str | None = None
    execution_time_ms: int | None = None
    tokens: int | None = None
    workflow_id: str | None = None
    parent_conversation_id: str | None = None
    prompt_asset_id: str | None = None
    response_asset_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatMessageCreate(BaseModel):
    conversation_id: str
    role: str
    content: str
    asset_id: str | None = None
    prompt_asset_id: str | None = None
    response_asset_id: str | None = None
    provider_name: str | None = None
    execution_time_ms: int | None = None
    tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    id: str
    conversation_id: str
    version: int
    role: str
    content: str
    asset_id: str | None = None
    prompt_asset_id: str | None = None
    response_asset_id: str | None = None
    provider_name: str | None = None
    execution_time_ms: int | None = None
    tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResearchSessionCreate(BaseModel):
    project_id: str
    title: str
    question: str
    conversation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchSession(BaseModel):
    id: str
    project_id: str
    title: str
    question: str
    status: str = "active"
    conversation_id: str | None = None
    collection_asset_id: str | None = None
    report_asset_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResearchSearchResult(BaseModel):
    id: str
    title: str
    url: str
    provider: str
    author: str | None = None
    language: str | None = None
    content_type: str | None = None
    trust_score: float | None = None
    hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchGraph(BaseModel):
    project_id: str
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RelationshipType(StrEnum):
    CREATED_BY = "created_by"
    GENERATED_FROM = "generated_from"
    DERIVED_FROM = "derived_from"
    USES = "uses"
    CONTAINS = "contains"
    REFERENCES = "references"
    BELONGS_TO = "belongs_to"
    DEPENDS_ON = "depends_on"
    REVIEWED_BY = "reviewed_by"
    APPROVED_BY = "approved_by"
    EXECUTED_BY = "executed_by"
    GENERATED_FOR = "generated_for"
    VERSION_OF = "version_of"
    CHILD_OF = "child_of"
    PARENT_OF = "parent_of"
    COLLABORATES_WITH = "collaborates_with"
    MENTIONS = "mentions"
    LINKED_TO = "linked_to"


class NodeReference(BaseModel):
    node_id: str
    node_type: str


class EdgeReference(BaseModel):
    edge_id: str
    relationship: RelationshipType
    from_node: str
    to_node: str


class KnowledgeNode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    node_type: str
    label: str
    project_id: str | None = None
    workspace_id: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    archived: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeEdge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    relationship: RelationshipType
    from_node: str
    to_node: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GraphSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    scope_type: str
    scope_id: str
    node_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeGraph(BaseModel):
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)


class ContextBundle(BaseModel):
    project: dict[str, Any] = Field(default_factory=dict)
    recent_chats: list[dict[str, Any]] = Field(default_factory=list)
    related_assets: list[dict[str, Any]] = Field(default_factory=list)
    research_findings: list[dict[str, Any]] = Field(default_factory=list)
    reviews: list[dict[str, Any]] = Field(default_factory=list)
    agent_history: list[dict[str, Any]] = Field(default_factory=list)
    workflow_history: list[dict[str, Any]] = Field(default_factory=list)
    execution_history: list[dict[str, Any]] = Field(default_factory=list)
    referenced_images: list[dict[str, Any]] = Field(default_factory=list)
    referenced_reports: list[dict[str, Any]] = Field(default_factory=list)
    graph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)


class ReviewSessionCreate(BaseModel):
    project_id: str
    title: str
    asset_id: str | None = None
    workflow_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewSession(BaseModel):
    id: str
    project_id: str
    title: str
    status: str = "pending"
    asset_id: str | None = None
    published_asset_id: str | None = None
    workflow_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewItem(BaseModel):
    id: str
    review_id: str
    asset_id: str
    decision: str = "pending"
    comment: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewComment(BaseModel):
    id: str
    review_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewHistoryEvent(BaseModel):
    id: str
    review_id: str
    event_type: str
    actor: str = "system"
    comment: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    asset_id: str | None = None
    published_asset_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowCreate(BaseModel):
    project_id: str | None = None
    name: str
    description: str = ""
    studio: str = "core"
    default_action: str | None = None
    capability_req: CapabilityRequest = Field(default_factory=CapabilityRequest)


class Workflow(BaseModel):
    id: str
    project_id: str | None = None
    name: str
    description: str
    studio: str
    default_action: str | None = None
    capability_req: CapabilityRequest = Field(default_factory=CapabilityRequest)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AssetCreate(BaseModel):
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
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    source_asset_ids: list[str] = Field(default_factory=list)
    thumbnail_uri: str | None = None
    preview_uri: str | None = None
    search_index: dict[str, Any] | None = None
    vector_index: dict[str, Any] | None = None
    embeddings: list[float] | None = None
    ocr_text: str | None = None
    transcript: str | None = None
    ai_summary: str | None = None


class Asset(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
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
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    source_asset_ids: list[str] = Field(default_factory=list)
    derived_asset_ids: list[str] = Field(default_factory=list)
    thumbnail_uri: str | None = None
    preview_uri: str | None = None
    search_index: dict[str, Any] | None = None
    vector_index: dict[str, Any] | None = None
    embeddings: list[float] | None = None
    ocr_text: str | None = None
    transcript: str | None = None
    ai_summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunCreate(BaseModel):
    title: str
    description: str = ""
    studio: str = "core"
    workspace_id: str | None = None
    project_id: str | None = None
    workflow_id: str | None = None


class Run(BaseModel):
    id: str
    title: str
    description: str
    studio: str
    workspace_id: str | None = None
    project_id: str | None = None
    workflow_id: str | None = None
    produced_asset_ids: list[str] = Field(default_factory=list)
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Step(BaseModel):
    id: str
    run_id: str
    action: str
    status: StepStatus = StepStatus.PENDING
    payload: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Job(BaseModel):
    id: str
    run_id: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    priority: int = 0
    capability_req: CapabilityRequest = Field(default_factory=CapabilityRequest)
    execution_decision_id: str | None = None
    provider_name: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    produced_asset_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutomationTriggerType(StrEnum):
    MANUAL = "manual"
    TIMER = "timer"
    CRON = "cron"
    ASSET_IMPORTED = "asset_imported"
    ASSET_UPDATED = "asset_updated"
    ASSET_PUBLISHED = "asset_published"
    REVIEW_APPROVED = "review_approved"
    REVIEW_REJECTED = "review_rejected"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    AGENT_COMPLETED = "agent_completed"
    PROJECT_CREATED = "project_created"
    PROJECT_OPENED = "project_opened"
    RESEARCH_COMPLETED = "research_completed"
    IMAGE_GENERATED = "image_generated"
    VIDEO_GENERATED = "video_generated"


class AutomationTrigger(BaseModel):
    type: AutomationTriggerType
    timer_seconds: int | None = None
    cron_expression: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AutomationCondition(BaseModel):
    type: str
    operator: str
    value: Any
    metadata: dict[str, Any] = Field(default_factory=dict)


class AutomationAction(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AutomationRuleCreate(BaseModel):
    name: str
    description: str
    trigger: AutomationTrigger
    conditions: list[AutomationCondition] = Field(default_factory=list)
    actions: list[AutomationAction] = Field(default_factory=list)
    schedule: dict[str, Any] | None = None
    priority: int = 0
    dry_run: bool = False


class AutomationRule(BaseModel):
    id: str
    project_id: str | None = None
    workspace_id: str | None = None
    name: str
    description: str
    trigger: AutomationTrigger
    conditions: list[AutomationCondition] = Field(default_factory=list)
    actions: list[AutomationAction] = Field(default_factory=list)
    schedule: dict[str, Any] | None = None
    priority: int = 0
    enabled: bool = True
    dry_run: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    disabled_at: datetime | None = None


class AutomationRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AutomationRun(BaseModel):
    id: str
    rule_id: str
    triggered_by: str
    status: AutomationRunStatus
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: int | None = None
    trigger_data: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    retries: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutomationLogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class AutomationLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str | None = None
    rule_id: str
    level: AutomationLogLevel = AutomationLogLevel.INFO
    message: str
    actor: str = "system"
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutomationSchedule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    rule_id: str
    schedule_id: str | None = None
    next_run: datetime | None = None
    last_run: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutomationState(BaseModel):
    """Live evaluation state of a rule, derived from its runs."""

    rule_id: str
    enabled: bool = True
    last_run_id: str | None = None
    last_status: AutomationRunStatus | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    total_runs: int = 0
    failure_count: int = 0
