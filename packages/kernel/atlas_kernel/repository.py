from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from .agents.models import (
    Agent,
    AgentAssignment,
    AgentAssignmentStatus,
    AgentConversation,
    AgentMailbox,
    AgentMemoryReference,
    AgentMessage,
    AgentMessageType,
    AgentPermission,
    AgentRole,
    AgentStatus,
    AgentTeam,
    AgentTeamStatus,
)
from .agents.schedule_models import (
    ExecutionSchedule,
    ResumeToken,
    RuntimeExecutionRecord,
    RuntimeExecutionStatus,
    RuntimeRetryPolicy,
    ScheduleQueueEntry,
    SchedulerPriority,
)
from .approval.models import (
    ApprovalCondition,
    ApprovalDecision,
    ApprovalHistoryEvent,
    ApprovalPolicy,
    ApprovalPolicyMode,
    ApprovalRequest,
    ApprovalScope,
    ApprovalState,
)
from .cluster.models import (
    ExecutionLease,
    ExecutionReservation,
    LeaseState,
    ReservationState,
    WorkerHeartbeat,
    WorkerMetrics,
    WorkerNode,
    WorkerResources,
    WorkerState,
)
from .db import SessionLocal, init_db
from .models import (
    Asset,
    AutomationAction,
    AutomationCondition,
    AutomationLog,
    AutomationLogLevel,
    AutomationRule,
    AutomationRun,
    AutomationRunStatus,
    AutomationSchedule,
    AutomationTrigger,
    ChatConversation,
    ChatMessage,
    ExecutionDecision,
    GraphSnapshot,
    Job,
    JobStatus,
    KnowledgeEdge,
    KnowledgeNode,
    Project,
    RelationshipType,
    ResearchGraph,
    ResearchSession,
    ReviewComment,
    ReviewHistoryEvent,
    ReviewItem,
    ReviewSession,
    Run,
    Step,
    Workflow,
    Workspace,
    normalize_capability_request,
)
from .organization.models import (
    AuditAction,
    AuditRecord,
    Branding,
    Identity,
    IdentityProviderKind,
    License,
    Membership,
    MembershipScope,
    Organization,
    Permission,
    PolicyDomain,
    PolicyScopeKind,
    PolicySet,
    Role,
    Team,
    TeamKind,
)


class AtlasRepository:
    def __init__(self) -> None:
        init_db()

    def create_workspace(self, workspace: Workspace) -> Workspace:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_workspaces (id, name, description, created_at)
                VALUES (:id, :name, :description, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": workspace.id,
                    "name": workspace.name,
                    "description": workspace.description,
                    "created_at": workspace.created_at,
                },
            )
            session.commit()
        return workspace

    def create_project(self, project: Project) -> Project:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_projects (id, workspace_id, name, description, created_at)
                VALUES (:id, :workspace_id, :name, :description, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": project.id,
                    "workspace_id": project.workspace_id,
                    "name": project.name,
                    "description": project.description,
                    "created_at": project.created_at,
                },
            )
            session.commit()
        return project

    def get_project(self, project_id: str) -> Project | None:
        with SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT id, workspace_id, name, description, created_at FROM atlas_projects WHERE id = :project_id"
                ),
                {"project_id": project_id},
            ).fetchone()
        if row is None:
            return None
        return Project(
            id=row[0],
            workspace_id=row[1],
            name=row[2],
            description=row[3],
            created_at=row[4],
        )

    def list_projects(self, workspace_id: str | None = None) -> list[Project]:
        with SessionLocal() as session:
            if workspace_id is None:
                rows = session.execute(
                    text(
                        "SELECT id, workspace_id, name, description, created_at FROM atlas_projects ORDER BY created_at DESC"
                    )
                ).fetchall()
            else:
                rows = session.execute(
                    text(
                        "SELECT id, workspace_id, name, description, created_at FROM atlas_projects WHERE workspace_id = :workspace_id ORDER BY created_at DESC"
                    ),
                    {"workspace_id": workspace_id},
                ).fetchall()
        return [
            Project(
                id=row[0],
                workspace_id=row[1],
                name=row[2],
                description=row[3],
                created_at=row[4],
            )
            for row in rows
        ]

    def create_chat_conversation(self, conversation: ChatConversation) -> ChatConversation:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_chat_conversations (
                    id, project_id, title, pinned, prompt_version, response_version,
                    provider_name, execution_time_ms, tokens, workflow_id,
                    parent_conversation_id, prompt_asset_id, response_asset_id,
                    metadata, created_at, updated_at, deleted_at
                )
                VALUES (
                    :id, :project_id, :title, :pinned, :prompt_version, :response_version,
                    :provider_name, :execution_time_ms, :tokens, :workflow_id,
                    :parent_conversation_id, :prompt_asset_id, :response_asset_id,
                    :metadata, :created_at, :updated_at, NULL
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": conversation.id,
                    "project_id": conversation.project_id,
                    "title": conversation.title,
                    "pinned": conversation.pinned,
                    "prompt_version": conversation.prompt_version,
                    "response_version": conversation.response_version,
                    "provider_name": conversation.provider_name,
                    "execution_time_ms": conversation.execution_time_ms,
                    "tokens": conversation.tokens,
                    "workflow_id": conversation.workflow_id,
                    "parent_conversation_id": conversation.parent_conversation_id,
                    "prompt_asset_id": conversation.prompt_asset_id,
                    "response_asset_id": conversation.response_asset_id,
                    "metadata": json.dumps(conversation.metadata),
                    "created_at": conversation.created_at,
                    "updated_at": conversation.updated_at,
                },
            )
            session.commit()
        return conversation

    def update_chat_conversation(self, conversation: ChatConversation) -> ChatConversation:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_chat_conversations
                SET title = :title,
                    pinned = :pinned,
                    prompt_version = :prompt_version,
                    response_version = :response_version,
                    provider_name = :provider_name,
                    execution_time_ms = :execution_time_ms,
                    tokens = :tokens,
                    workflow_id = :workflow_id,
                    parent_conversation_id = :parent_conversation_id,
                    prompt_asset_id = :prompt_asset_id,
                    response_asset_id = :response_asset_id,
                    metadata = :metadata,
                    updated_at = :updated_at
                WHERE id = :id
                """),
                {
                    "id": conversation.id,
                    "title": conversation.title,
                    "pinned": conversation.pinned,
                    "prompt_version": conversation.prompt_version,
                    "response_version": conversation.response_version,
                    "provider_name": conversation.provider_name,
                    "execution_time_ms": conversation.execution_time_ms,
                    "tokens": conversation.tokens,
                    "workflow_id": conversation.workflow_id,
                    "parent_conversation_id": conversation.parent_conversation_id,
                    "prompt_asset_id": conversation.prompt_asset_id,
                    "response_asset_id": conversation.response_asset_id,
                    "metadata": json.dumps(conversation.metadata),
                    "updated_at": conversation.updated_at,
                },
            )
            session.commit()
        return conversation

    def get_chat_conversation(self, conversation_id: str) -> ChatConversation | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT id, project_id, title, pinned, prompt_version, response_version,
                       provider_name, execution_time_ms, tokens, workflow_id,
                       parent_conversation_id, prompt_asset_id, response_asset_id,
                       metadata, created_at, updated_at
                FROM atlas_chat_conversations
                WHERE id = :conversation_id AND deleted_at IS NULL
                """),
                {"conversation_id": conversation_id},
            ).fetchone()
        if row is None:
            return None
        return ChatConversation(
            id=row[0],
            project_id=row[1],
            title=row[2],
            pinned=row[3],
            prompt_version=row[4],
            response_version=row[5],
            provider_name=row[6],
            execution_time_ms=row[7],
            tokens=row[8],
            workflow_id=row[9],
            parent_conversation_id=row[10],
            prompt_asset_id=row[11],
            response_asset_id=row[12],
            metadata=(
                row[13] if isinstance(row[13], dict) else json.loads(row[13]) if row[13] else {}
            ),
            created_at=row[14],
            updated_at=row[15],
        )

    def list_chat_conversations(self, project_id: str | None = None) -> list[ChatConversation]:
        with SessionLocal() as session:
            if project_id is None:
                rows = session.execute(
                    text("""
                    SELECT id, project_id, title, pinned, prompt_version, response_version,
                           provider_name, execution_time_ms, tokens, workflow_id,
                           parent_conversation_id, prompt_asset_id, response_asset_id,
                           metadata, created_at, updated_at
                    FROM atlas_chat_conversations
                    WHERE deleted_at IS NULL
                    ORDER BY pinned DESC, updated_at DESC
                    """)
                ).fetchall()
            else:
                rows = session.execute(
                    text("""
                    SELECT id, project_id, title, pinned, prompt_version, response_version,
                           provider_name, execution_time_ms, tokens, workflow_id,
                           parent_conversation_id, prompt_asset_id, response_asset_id,
                           metadata, created_at, updated_at
                    FROM atlas_chat_conversations
                    WHERE project_id = :project_id AND deleted_at IS NULL
                    ORDER BY pinned DESC, updated_at DESC
                    """),
                    {"project_id": project_id},
                ).fetchall()
        return [
            ChatConversation(
                id=row[0],
                project_id=row[1],
                title=row[2],
                pinned=row[3],
                prompt_version=row[4],
                response_version=row[5],
                provider_name=row[6],
                execution_time_ms=row[7],
                tokens=row[8],
                workflow_id=row[9],
                parent_conversation_id=row[10],
                prompt_asset_id=row[11],
                response_asset_id=row[12],
                metadata=(
                    row[13] if isinstance(row[13], dict) else json.loads(row[13]) if row[13] else {}
                ),
                created_at=row[14],
                updated_at=row[15],
            )
            for row in rows
        ]

    def delete_chat_conversation(self, conversation_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                text(
                    "UPDATE atlas_chat_conversations SET deleted_at = now() WHERE id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            )
            session.execute(
                text(
                    "UPDATE atlas_chat_messages SET deleted_at = now() WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            )
            session.commit()

    def create_research_session(self, session_record: ResearchSession) -> ResearchSession:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_research_sessions (
                    id, project_id, title, question, status, conversation_id,
                    collection_asset_id, report_asset_id, metadata, created_at, updated_at, deleted_at
                )
                VALUES (
                    :id, :project_id, :title, :question, :status, :conversation_id,
                    :collection_asset_id, :report_asset_id, :metadata, :created_at, :updated_at, NULL
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": session_record.id,
                    "project_id": session_record.project_id,
                    "title": session_record.title,
                    "question": session_record.question,
                    "status": session_record.status,
                    "conversation_id": session_record.conversation_id,
                    "collection_asset_id": session_record.collection_asset_id,
                    "report_asset_id": session_record.report_asset_id,
                    "metadata": json.dumps(session_record.metadata),
                    "created_at": session_record.created_at,
                    "updated_at": session_record.updated_at,
                },
            )
            session.commit()
        return session_record

    def update_research_session(self, session_record: ResearchSession) -> ResearchSession:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_research_sessions
                SET title = :title,
                    question = :question,
                    status = :status,
                    conversation_id = :conversation_id,
                    collection_asset_id = :collection_asset_id,
                    report_asset_id = :report_asset_id,
                    metadata = :metadata,
                    updated_at = :updated_at
                WHERE id = :id
                """),
                {
                    "id": session_record.id,
                    "title": session_record.title,
                    "question": session_record.question,
                    "status": session_record.status,
                    "conversation_id": session_record.conversation_id,
                    "collection_asset_id": session_record.collection_asset_id,
                    "report_asset_id": session_record.report_asset_id,
                    "metadata": json.dumps(session_record.metadata),
                    "updated_at": session_record.updated_at,
                },
            )
            session.commit()
        return session_record

    def get_research_session(self, session_id: str) -> ResearchSession | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT id, project_id, title, question, status, conversation_id,
                       collection_asset_id, report_asset_id, metadata, created_at, updated_at
                FROM atlas_research_sessions
                WHERE id = :session_id AND deleted_at IS NULL
                """),
                {"session_id": session_id},
            ).fetchone()
        if row is None:
            return None
        return ResearchSession(
            id=row[0],
            project_id=row[1],
            title=row[2],
            question=row[3],
            status=row[4],
            conversation_id=row[5],
            collection_asset_id=row[6],
            report_asset_id=row[7],
            metadata=row[8] if isinstance(row[8], dict) else json.loads(row[8]) if row[8] else {},
            created_at=row[9],
            updated_at=row[10],
        )

    def list_research_sessions(self, project_id: str | None = None) -> list[ResearchSession]:
        with SessionLocal() as session:
            if project_id is None:
                rows = session.execute(
                    text("""
                    SELECT id, project_id, title, question, status, conversation_id,
                           collection_asset_id, report_asset_id, metadata, created_at, updated_at
                    FROM atlas_research_sessions
                    WHERE deleted_at IS NULL
                    ORDER BY updated_at DESC
                    """)
                ).fetchall()
            else:
                rows = session.execute(
                    text("""
                    SELECT id, project_id, title, question, status, conversation_id,
                           collection_asset_id, report_asset_id, metadata, created_at, updated_at
                    FROM atlas_research_sessions
                    WHERE project_id = :project_id AND deleted_at IS NULL
                    ORDER BY updated_at DESC
                    """),
                    {"project_id": project_id},
                ).fetchall()
        return [
            ResearchSession(
                id=row[0],
                project_id=row[1],
                title=row[2],
                question=row[3],
                status=row[4],
                conversation_id=row[5],
                collection_asset_id=row[6],
                report_asset_id=row[7],
                metadata=(
                    row[8] if isinstance(row[8], dict) else json.loads(row[8]) if row[8] else {}
                ),
                created_at=row[9],
                updated_at=row[10],
            )
            for row in rows
        ]

    def save_research_graph(self, graph: ResearchGraph) -> ResearchGraph:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_research_graphs (project_id, nodes, edges, updated_at)
                VALUES (:project_id, :nodes, :edges, :updated_at)
                ON CONFLICT (project_id)
                DO UPDATE SET nodes = :nodes, edges = :edges, updated_at = :updated_at
                """),
                {
                    "project_id": graph.project_id,
                    "nodes": json.dumps(graph.nodes),
                    "edges": json.dumps(graph.edges),
                    "updated_at": graph.updated_at,
                },
            )
            session.commit()
        return graph

    def get_research_graph(self, project_id: str) -> ResearchGraph:
        with SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT project_id, nodes, edges, updated_at FROM atlas_research_graphs WHERE project_id = :project_id"
                ),
                {"project_id": project_id},
            ).fetchone()
        if row is None:
            return ResearchGraph(project_id=project_id)
        return ResearchGraph(
            project_id=row[0],
            nodes=row[1] if isinstance(row[1], list) else json.loads(row[1]) if row[1] else [],
            edges=row[2] if isinstance(row[2], list) else json.loads(row[2]) if row[2] else [],
            updated_at=row[3],
        )

    def create_review_session(self, review: ReviewSession) -> ReviewSession:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_review_sessions (
                    id, project_id, title, status, asset_id, published_asset_id,
                    workflow_id, metadata, created_at, updated_at, deleted_at
                )
                VALUES (
                    :id, :project_id, :title, :status, :asset_id, :published_asset_id,
                    :workflow_id, :metadata, :created_at, :updated_at, NULL
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": review.id,
                    "project_id": review.project_id,
                    "title": review.title,
                    "status": review.status,
                    "asset_id": review.asset_id,
                    "published_asset_id": review.published_asset_id,
                    "workflow_id": review.workflow_id,
                    "metadata": json.dumps(review.metadata),
                    "created_at": review.created_at,
                    "updated_at": review.updated_at,
                },
            )
            session.commit()
        return review

    def update_review_session(self, review: ReviewSession) -> ReviewSession:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_review_sessions
                SET title = :title,
                    status = :status,
                    asset_id = :asset_id,
                    published_asset_id = :published_asset_id,
                    workflow_id = :workflow_id,
                    metadata = :metadata,
                    updated_at = :updated_at
                WHERE id = :id
                """),
                {
                    "id": review.id,
                    "title": review.title,
                    "status": review.status,
                    "asset_id": review.asset_id,
                    "published_asset_id": review.published_asset_id,
                    "workflow_id": review.workflow_id,
                    "metadata": json.dumps(review.metadata),
                    "updated_at": review.updated_at,
                },
            )
            session.commit()
        return review

    def get_review_session(self, review_id: str) -> ReviewSession | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT id, project_id, title, status, asset_id, published_asset_id,
                       workflow_id, metadata, created_at, updated_at
                FROM atlas_review_sessions
                WHERE id = :review_id AND deleted_at IS NULL
                """),
                {"review_id": review_id},
            ).fetchone()
        if row is None:
            return None
        return ReviewSession(
            id=row[0],
            project_id=row[1],
            title=row[2],
            status=row[3],
            asset_id=row[4],
            published_asset_id=row[5],
            workflow_id=row[6],
            metadata=row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {},
            created_at=row[8],
            updated_at=row[9],
        )

    def list_review_sessions(self, project_id: str | None = None) -> list[ReviewSession]:
        with SessionLocal() as session:
            if project_id is None:
                rows = session.execute(
                    text("""
                    SELECT id, project_id, title, status, asset_id, published_asset_id,
                           workflow_id, metadata, created_at, updated_at
                    FROM atlas_review_sessions
                    WHERE deleted_at IS NULL
                    ORDER BY updated_at DESC
                    """)
                ).fetchall()
            else:
                rows = session.execute(
                    text("""
                    SELECT id, project_id, title, status, asset_id, published_asset_id,
                           workflow_id, metadata, created_at, updated_at
                    FROM atlas_review_sessions
                    WHERE project_id = :project_id AND deleted_at IS NULL
                    ORDER BY updated_at DESC
                    """),
                    {"project_id": project_id},
                ).fetchall()
        return [
            ReviewSession(
                id=row[0],
                project_id=row[1],
                title=row[2],
                status=row[3],
                asset_id=row[4],
                published_asset_id=row[5],
                workflow_id=row[6],
                metadata=(
                    row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {}
                ),
                created_at=row[8],
                updated_at=row[9],
            )
            for row in rows
        ]

    def upsert_review_item(self, item: ReviewItem) -> ReviewItem:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_review_items (
                    id, review_id, asset_id, decision, comment, metadata,
                    created_at, updated_at, deleted_at
                )
                VALUES (
                    :id, :review_id, :asset_id, :decision, :comment, :metadata,
                    :created_at, :updated_at, NULL
                )
                ON CONFLICT (id)
                DO UPDATE SET
                    decision = EXCLUDED.decision,
                    comment = EXCLUDED.comment,
                    metadata = EXCLUDED.metadata,
                    updated_at = EXCLUDED.updated_at,
                    deleted_at = NULL
                """),
                {
                    "id": item.id,
                    "review_id": item.review_id,
                    "asset_id": item.asset_id,
                    "decision": item.decision,
                    "comment": item.comment,
                    "metadata": json.dumps(item.metadata),
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                },
            )
            session.commit()
        return item

    def list_review_items(self, review_id: str) -> list[ReviewItem]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT id, review_id, asset_id, decision, comment, metadata, created_at, updated_at
                FROM atlas_review_items
                WHERE review_id = :review_id AND deleted_at IS NULL
                ORDER BY created_at ASC
                """),
                {"review_id": review_id},
            ).fetchall()
        return [
            ReviewItem(
                id=row[0],
                review_id=row[1],
                asset_id=row[2],
                decision=row[3],
                comment=row[4],
                metadata=(
                    row[5] if isinstance(row[5], dict) else json.loads(row[5]) if row[5] else {}
                ),
                created_at=row[6],
                updated_at=row[7],
            )
            for row in rows
        ]

    def create_review_comment(self, comment: ReviewComment) -> ReviewComment:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_review_comments (
                    id, review_id, content, metadata, created_at, deleted_at
                )
                VALUES (
                    :id, :review_id, :content, :metadata, :created_at, NULL
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": comment.id,
                    "review_id": comment.review_id,
                    "content": comment.content,
                    "metadata": json.dumps(comment.metadata),
                    "created_at": comment.created_at,
                },
            )
            session.commit()
        return comment

    def list_review_comments(self, review_id: str) -> list[ReviewComment]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT id, review_id, content, metadata, created_at
                FROM atlas_review_comments
                WHERE review_id = :review_id AND deleted_at IS NULL
                ORDER BY created_at ASC
                """),
                {"review_id": review_id},
            ).fetchall()
        return [
            ReviewComment(
                id=row[0],
                review_id=row[1],
                content=row[2],
                metadata=(
                    row[3] if isinstance(row[3], dict) else json.loads(row[3]) if row[3] else {}
                ),
                created_at=row[4],
            )
            for row in rows
        ]

    def create_review_history_event(self, event: ReviewHistoryEvent) -> ReviewHistoryEvent:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_review_history (
                    id, review_id, event_type, actor, comment, from_status, to_status,
                    asset_id, published_asset_id, metadata, created_at
                )
                VALUES (
                    :id, :review_id, :event_type, :actor, :comment, :from_status, :to_status,
                    :asset_id, :published_asset_id, :metadata, :created_at
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": event.id,
                    "review_id": event.review_id,
                    "event_type": event.event_type,
                    "actor": event.actor,
                    "comment": event.comment,
                    "from_status": event.from_status,
                    "to_status": event.to_status,
                    "asset_id": event.asset_id,
                    "published_asset_id": event.published_asset_id,
                    "metadata": json.dumps(event.metadata),
                    "created_at": event.created_at,
                },
            )
            session.commit()
        return event

    def list_review_history(self, review_id: str) -> list[ReviewHistoryEvent]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT id, review_id, event_type, actor, comment, from_status, to_status,
                       asset_id, published_asset_id, metadata, created_at
                FROM atlas_review_history
                WHERE review_id = :review_id
                ORDER BY created_at ASC
                """),
                {"review_id": review_id},
            ).fetchall()
        return [
            ReviewHistoryEvent(
                id=row[0],
                review_id=row[1],
                event_type=row[2],
                actor=row[3],
                comment=row[4],
                from_status=row[5],
                to_status=row[6],
                asset_id=row[7],
                published_asset_id=row[8],
                metadata=(
                    row[9] if isinstance(row[9], dict) else json.loads(row[9]) if row[9] else {}
                ),
                created_at=row[10],
            )
            for row in rows
        ]

    def create_chat_message(self, message: ChatMessage) -> ChatMessage:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_chat_messages (
                    id, conversation_id, version, role, content, asset_id,
                    prompt_asset_id, response_asset_id, provider_name,
                    execution_time_ms, tokens, metadata, created_at, deleted_at
                )
                VALUES (
                    :id, :conversation_id, :version, :role, :content, :asset_id,
                    :prompt_asset_id, :response_asset_id, :provider_name,
                    :execution_time_ms, :tokens, :metadata, :created_at, NULL
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": message.id,
                    "conversation_id": message.conversation_id,
                    "version": message.version,
                    "role": message.role,
                    "content": message.content,
                    "asset_id": message.asset_id,
                    "prompt_asset_id": message.prompt_asset_id,
                    "response_asset_id": message.response_asset_id,
                    "provider_name": message.provider_name,
                    "execution_time_ms": message.execution_time_ms,
                    "tokens": message.tokens,
                    "metadata": json.dumps(message.metadata),
                    "created_at": message.created_at,
                },
            )
            session.commit()
        return message

    def list_chat_messages(self, conversation_id: str) -> list[ChatMessage]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT id, conversation_id, version, role, content, asset_id,
                       prompt_asset_id, response_asset_id, provider_name,
                       execution_time_ms, tokens, metadata, created_at
                FROM atlas_chat_messages
                WHERE conversation_id = :conversation_id AND deleted_at IS NULL
                ORDER BY version ASC, created_at ASC
                """),
                {"conversation_id": conversation_id},
            ).fetchall()
        return [
            ChatMessage(
                id=row[0],
                conversation_id=row[1],
                version=row[2],
                role=row[3],
                content=row[4],
                asset_id=row[5],
                prompt_asset_id=row[6],
                response_asset_id=row[7],
                provider_name=row[8],
                execution_time_ms=row[9],
                tokens=row[10],
                metadata=(
                    row[11] if isinstance(row[11], dict) else json.loads(row[11]) if row[11] else {}
                ),
                created_at=row[12],
            )
            for row in rows
        ]

    def create_workflow(self, workflow: Workflow) -> Workflow:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_workflows (id, project_id, name, description, studio, default_action, capability_req, created_at)
                VALUES (:id, :project_id, :name, :description, :studio, :default_action, :capability_req, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": workflow.id,
                    "project_id": workflow.project_id,
                    "name": workflow.name,
                    "description": workflow.description,
                    "studio": workflow.studio,
                    "default_action": workflow.default_action,
                    "capability_req": json.dumps(workflow.capability_req.model_dump()),
                    "created_at": workflow.created_at,
                },
            )
            session.commit()
        return workflow

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        with SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT id, project_id, name, description, studio, default_action, capability_req, created_at FROM atlas_workflows WHERE id = :workflow_id"
                ),
                {"workflow_id": workflow_id},
            ).fetchone()
        if row is None:
            return None
        return Workflow(
            id=row[0],
            project_id=row[1],
            name=row[2],
            description=row[3],
            studio=row[4],
            default_action=row[5],
            capability_req=normalize_capability_request(
                row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {}
            ),
            created_at=row[7],
        )

    def list_workflows(self, project_id: str | None = None) -> list[Workflow]:
        with SessionLocal() as session:
            if project_id is None:
                rows = session.execute(
                    text(
                        "SELECT id, project_id, name, description, studio, default_action, capability_req, created_at FROM atlas_workflows ORDER BY created_at DESC"
                    )
                ).fetchall()
            else:
                rows = session.execute(
                    text(
                        "SELECT id, project_id, name, description, studio, default_action, capability_req, created_at FROM atlas_workflows WHERE project_id = :project_id ORDER BY created_at DESC"
                    ),
                    {"project_id": project_id},
                ).fetchall()
        return [
            Workflow(
                id=row[0],
                project_id=row[1],
                name=row[2],
                description=row[3],
                studio=row[4],
                default_action=row[5],
                capability_req=normalize_capability_request(
                    row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {}
                ),
                created_at=row[7],
            )
            for row in rows
        ]

    def create_run(self, run: Run) -> Run:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_runs (id, title, description, studio, workspace_id, project_id, workflow_id, produced_asset_ids, status, created_at)
                VALUES (:id, :title, :description, :studio, :workspace_id, :project_id, :workflow_id, :produced_asset_ids, :status, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": run.id,
                    "title": run.title,
                    "description": run.description,
                    "studio": run.studio,
                    "workspace_id": run.workspace_id,
                    "project_id": run.project_id,
                    "workflow_id": run.workflow_id,
                    "produced_asset_ids": json.dumps(run.produced_asset_ids),
                    "status": run.status.value,
                    "created_at": run.created_at,
                },
            )
            session.commit()
        return run

    def create_step(self, step: Step) -> Step:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_steps (id, run_id, action, status, payload, depends_on, created_at)
                VALUES (:id, :run_id, :action, :status, :payload, :depends_on, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": step.id,
                    "run_id": step.run_id,
                    "action": step.action,
                    "status": step.status.value,
                    "payload": json.dumps(step.payload),
                    "depends_on": json.dumps(step.depends_on),
                    "created_at": step.created_at,
                },
            )
            session.commit()
        return step

    def create_job(self, job: Job) -> Job:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_jobs (id, run_id, action, payload, status, attempts, priority, capability_req, execution_decision_id, provider_name, output, produced_asset_ids, created_at)
                VALUES (:id, :run_id, :action, :payload, :status, :attempts, :priority, :capability_req, :execution_decision_id, :provider_name, :output, :produced_asset_ids, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": job.id,
                    "run_id": job.run_id,
                    "action": job.action,
                    "payload": json.dumps(job.payload),
                    "status": job.status.value,
                    "attempts": job.attempts,
                    "priority": job.priority,
                    "capability_req": json.dumps(job.capability_req.model_dump()),
                    "execution_decision_id": job.execution_decision_id,
                    "provider_name": job.provider_name,
                    "output": json.dumps(job.output),
                    "produced_asset_ids": json.dumps(job.produced_asset_ids),
                    "created_at": job.created_at,
                },
            )
            session.commit()
        return job

    def create_asset(self, asset: Asset) -> Asset:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_assets (
                    id,
                    project_id,
                    workflow_id,
                    run_id,
                    job_id,
                    parent_asset_id,
                    version,
                    type,
                    uri,
                    mime_type,
                    file_size,
                    content_hash,
                    metadata,
                    tags,
                    source_asset_ids,
                    thumbnail_uri,
                    preview_uri,
                    search_index,
                    vector_index,
                    embeddings,
                    ocr_text,
                    transcript,
                    ai_summary,
                    created_at,
                    updated_at,
                    deleted_at
                )
                VALUES (
                    :id,
                    :project_id,
                    :workflow_id,
                    :run_id,
                    :job_id,
                    :parent_asset_id,
                    :version,
                    :type,
                    :uri,
                    :mime_type,
                    :file_size,
                    :content_hash,
                    :metadata,
                    :tags,
                    :source_asset_ids,
                    :thumbnail_uri,
                    :preview_uri,
                    :search_index,
                    :vector_index,
                    :embeddings,
                    :ocr_text,
                    :transcript,
                    :ai_summary,
                    :created_at,
                    :updated_at,
                    NULL
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": asset.id,
                    "project_id": asset.project_id,
                    "workflow_id": asset.workflow_id,
                    "run_id": asset.run_id,
                    "job_id": asset.job_id,
                    "parent_asset_id": asset.parent_asset_id,
                    "version": asset.version,
                    "type": asset.type,
                    "uri": asset.uri,
                    "mime_type": asset.mime_type,
                    "file_size": asset.file_size,
                    "content_hash": asset.content_hash,
                    "metadata": json.dumps(asset.metadata),
                    "tags": json.dumps(asset.tags),
                    "source_asset_ids": json.dumps(asset.source_asset_ids),
                    "thumbnail_uri": asset.thumbnail_uri,
                    "preview_uri": asset.preview_uri,
                    "search_index": json.dumps(asset.search_index),
                    "vector_index": json.dumps(asset.vector_index),
                    "embeddings": json.dumps(asset.embeddings),
                    "ocr_text": asset.ocr_text,
                    "transcript": asset.transcript,
                    "ai_summary": asset.ai_summary,
                    "created_at": asset.created_at,
                    "updated_at": asset.updated_at,
                },
            )
            session.commit()
        return asset

    def create_execution_decision(self, decision: ExecutionDecision) -> ExecutionDecision:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_execution_decisions (
                    decision_id, capability_id, recipe_id, executor_id, provider_id,
                    model_id, reason, confidence, timestamp
                )
                VALUES (
                    :decision_id, :capability_id, :recipe_id, :executor_id, :provider_id,
                    :model_id, :reason, :confidence, :timestamp
                )
                ON CONFLICT (decision_id) DO NOTHING
                """),
                {
                    "decision_id": decision.decision_id,
                    "capability_id": decision.capability_id,
                    "recipe_id": decision.recipe_id,
                    "executor_id": decision.executor_id,
                    "provider_id": decision.provider_id,
                    "model_id": decision.model_id,
                    "reason": json.dumps(decision.reason),
                    "confidence": decision.confidence,
                    "timestamp": decision.timestamp,
                },
            )
            session.commit()
        return decision

    def create_agent(self, agent: Agent) -> Agent:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_agents (
                    id, name, description, role, workspace_id, project_id,
                    capabilities, status, memory_id, permission_set,
                    created_at, updated_at, deleted_at
                )
                VALUES (
                    :id, :name, :description, :role, :workspace_id, :project_id,
                    :capabilities, :status, :memory_id, :permission_set,
                    :created_at, :updated_at, NULL
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": agent.id,
                    "name": agent.name,
                    "description": agent.description,
                    "role": agent.role,
                    "workspace_id": agent.workspace_id,
                    "project_id": agent.project_id,
                    "capabilities": json.dumps(agent.capabilities),
                    "status": agent.status.value,
                    "memory_id": agent.memory_id,
                    "permission_set": json.dumps(
                        [permission.value for permission in agent.permission_set]
                    ),
                    "created_at": agent.created_at,
                    "updated_at": agent.updated_at,
                },
            )
            session.commit()
        return agent

    def update_agent(self, agent: Agent) -> Agent:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_agents
                SET name = :name,
                    description = :description,
                    role = :role,
                    workspace_id = :workspace_id,
                    project_id = :project_id,
                    capabilities = :capabilities,
                    status = :status,
                    memory_id = :memory_id,
                    permission_set = :permission_set,
                    updated_at = :updated_at
                WHERE id = :id
                """),
                {
                    "id": agent.id,
                    "name": agent.name,
                    "description": agent.description,
                    "role": agent.role,
                    "workspace_id": agent.workspace_id,
                    "project_id": agent.project_id,
                    "capabilities": json.dumps(agent.capabilities),
                    "status": agent.status.value,
                    "memory_id": agent.memory_id,
                    "permission_set": json.dumps(
                        [permission.value for permission in agent.permission_set]
                    ),
                    "updated_at": agent.updated_at,
                },
            )
            session.commit()
        return agent

    def get_agent(self, agent_id: str) -> Agent | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT id, name, description, role, workspace_id, project_id,
                       capabilities, status, memory_id, permission_set,
                       created_at, updated_at
                FROM atlas_agents
                WHERE id = :agent_id AND deleted_at IS NULL
                """),
                {"agent_id": agent_id},
            ).fetchone()
        if row is None:
            return None
        return Agent(
            id=row[0],
            name=row[1],
            description=row[2],
            role=row[3],
            workspace_id=row[4],
            project_id=row[5],
            capabilities=(
                row[6] if isinstance(row[6], list) else json.loads(row[6]) if row[6] else []
            ),
            status=AgentStatus(row[7]),
            memory_id=row[8],
            permission_set=[
                AgentPermission(value)
                for value in (
                    row[9] if isinstance(row[9], list) else json.loads(row[9]) if row[9] else []
                )
            ],
            created_at=row[10],
            updated_at=row[11],
        )

    def list_agents(self, project_id: str | None = None) -> list[Agent]:
        with SessionLocal() as session:
            if project_id is None:
                rows = session.execute(
                    text("""
                    SELECT id, name, description, role, workspace_id, project_id,
                           capabilities, status, memory_id, permission_set,
                           created_at, updated_at
                    FROM atlas_agents
                    WHERE deleted_at IS NULL
                    ORDER BY created_at DESC
                    """)
                ).fetchall()
            else:
                rows = session.execute(
                    text("""
                    SELECT id, name, description, role, workspace_id, project_id,
                           capabilities, status, memory_id, permission_set,
                           created_at, updated_at
                    FROM atlas_agents
                    WHERE project_id = :project_id AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    """),
                    {"project_id": project_id},
                ).fetchall()
        return [
            Agent(
                id=row[0],
                name=row[1],
                description=row[2],
                role=row[3],
                workspace_id=row[4],
                project_id=row[5],
                capabilities=(
                    row[6] if isinstance(row[6], list) else json.loads(row[6]) if row[6] else []
                ),
                status=AgentStatus(row[7]),
                memory_id=row[8],
                permission_set=[
                    AgentPermission(value)
                    for value in (
                        row[9] if isinstance(row[9], list) else json.loads(row[9]) if row[9] else []
                    )
                ],
                created_at=row[10],
                updated_at=row[11],
            )
            for row in rows
        ]

    def delete_agent(self, agent_id: str) -> bool:
        with SessionLocal() as session:
            result = session.execute(
                text(
                    "UPDATE atlas_agents SET deleted_at = now() WHERE id = :agent_id AND deleted_at IS NULL"
                ),
                {"agent_id": agent_id},
            )
            session.commit()
            return bool(getattr(result, "rowcount", 0) > 0)

    def create_agent_memory_reference(
        self, reference: AgentMemoryReference
    ) -> AgentMemoryReference:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_agent_memory_references (
                    id, memory_id, agent_id, kind, asset_id, created_at
                )
                VALUES (
                    :id, :memory_id, :agent_id, :kind, :asset_id, :created_at
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": reference.id,
                    "memory_id": reference.memory_id,
                    "agent_id": reference.agent_id,
                    "kind": reference.kind,
                    "asset_id": reference.asset_id,
                    "created_at": reference.created_at,
                },
            )
            session.commit()
        return reference

    def create_agent_team(self, team: AgentTeam) -> AgentTeam:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_agent_teams (
                    id, name, project_id, workspace_id, status, conversation_ids, created_at, updated_at
                ) VALUES (
                    :id, :name, :project_id, :workspace_id, :status, :conversation_ids, :created_at, :updated_at
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": team.id,
                    "name": team.name,
                    "project_id": team.project_id,
                    "workspace_id": team.workspace_id,
                    "status": team.status.value,
                    "conversation_ids": json.dumps(team.conversation_ids),
                    "created_at": team.created_at,
                    "updated_at": team.updated_at,
                },
            )
            session.commit()
        return team

    def update_agent_team(self, team: AgentTeam) -> AgentTeam:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_agent_teams
                SET name = :name,
                    project_id = :project_id,
                    workspace_id = :workspace_id,
                    status = :status,
                    conversation_ids = :conversation_ids,
                    updated_at = :updated_at
                WHERE id = :id
                """),
                {
                    "id": team.id,
                    "name": team.name,
                    "project_id": team.project_id,
                    "workspace_id": team.workspace_id,
                    "status": team.status.value,
                    "conversation_ids": json.dumps(team.conversation_ids),
                    "updated_at": team.updated_at,
                },
            )
            session.commit()
        return team

    def get_agent_team(self, team_id: str) -> AgentTeam | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT id, name, project_id, workspace_id, status, conversation_ids, created_at, updated_at
                FROM atlas_agent_teams
                WHERE id = :team_id
                """),
                {"team_id": team_id},
            ).fetchone()
        if row is None:
            return None
        assignments = self.list_agent_assignments(team_id)
        return AgentTeam(
            id=row[0],
            name=row[1],
            project_id=row[2],
            workspace_id=row[3],
            status=AgentTeamStatus(row[4]),
            assignments=assignments,
            conversation_ids=(
                row[5] if isinstance(row[5], list) else json.loads(row[5]) if row[5] else []
            ),
            created_at=row[6],
            updated_at=row[7],
        )

    def create_agent_assignment(self, assignment: AgentAssignment) -> AgentAssignment:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_agent_assignments (
                    id, team_id, agent_id, role, title, status, capabilities, allowed_actions,
                    permissions, resource_limits, action, payload, dependencies, mailbox_id,
                    schedule_id, runtime_execution_id, result_asset_id, error, created_at, updated_at
                ) VALUES (
                    :id, :team_id, :agent_id, :role, :title, :status, :capabilities, :allowed_actions,
                    :permissions, :resource_limits, :action, :payload, :dependencies, :mailbox_id,
                    :schedule_id, :runtime_execution_id, :result_asset_id, :error, :created_at, :updated_at
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": assignment.id,
                    "team_id": assignment.team_id,
                    "agent_id": assignment.agent_id,
                    "role": assignment.role.value,
                    "title": assignment.title,
                    "status": assignment.status.value,
                    "capabilities": json.dumps(assignment.capabilities),
                    "allowed_actions": json.dumps(assignment.allowed_actions),
                    "permissions": json.dumps(
                        [permission.value for permission in assignment.permissions]
                    ),
                    "resource_limits": json.dumps(assignment.resource_limits),
                    "action": assignment.action,
                    "payload": json.dumps(assignment.payload, default=_json_value),
                    "dependencies": json.dumps(assignment.dependencies),
                    "mailbox_id": assignment.mailbox_id,
                    "schedule_id": assignment.schedule_id,
                    "runtime_execution_id": assignment.runtime_execution_id,
                    "result_asset_id": assignment.result_asset_id,
                    "error": assignment.error,
                    "created_at": assignment.created_at,
                    "updated_at": assignment.updated_at,
                },
            )
            session.commit()
        return assignment

    def update_agent_assignment(self, assignment: AgentAssignment) -> AgentAssignment:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_agent_assignments
                SET status = :status,
                    capabilities = :capabilities,
                    allowed_actions = :allowed_actions,
                    permissions = :permissions,
                    resource_limits = :resource_limits,
                    action = :action,
                    payload = :payload,
                    dependencies = :dependencies,
                    mailbox_id = :mailbox_id,
                    schedule_id = :schedule_id,
                    runtime_execution_id = :runtime_execution_id,
                    result_asset_id = :result_asset_id,
                    error = :error,
                    updated_at = :updated_at
                WHERE id = :id
                """),
                {
                    "id": assignment.id,
                    "status": assignment.status.value,
                    "capabilities": json.dumps(assignment.capabilities),
                    "allowed_actions": json.dumps(assignment.allowed_actions),
                    "permissions": json.dumps(
                        [permission.value for permission in assignment.permissions]
                    ),
                    "resource_limits": json.dumps(assignment.resource_limits),
                    "action": assignment.action,
                    "payload": json.dumps(assignment.payload, default=_json_value),
                    "dependencies": json.dumps(assignment.dependencies),
                    "mailbox_id": assignment.mailbox_id,
                    "schedule_id": assignment.schedule_id,
                    "runtime_execution_id": assignment.runtime_execution_id,
                    "result_asset_id": assignment.result_asset_id,
                    "error": assignment.error,
                    "updated_at": assignment.updated_at,
                },
            )
            session.commit()
        return assignment

    def list_agent_assignments(self, team_id: str) -> list[AgentAssignment]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT id, team_id, agent_id, role, title, status, capabilities, allowed_actions,
                       permissions, resource_limits, action, payload, dependencies, mailbox_id,
                       schedule_id, runtime_execution_id, result_asset_id, error, created_at, updated_at
                FROM atlas_agent_assignments
                WHERE team_id = :team_id
                ORDER BY created_at ASC
                """),
                {"team_id": team_id},
            ).fetchall()
        return [self._row_to_agent_assignment(row) for row in rows]

    def get_agent_mailbox(self, agent_id: str) -> AgentMailbox:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT agent_id, pending_messages, history
                FROM atlas_agent_mailboxes
                WHERE agent_id = :agent_id
                """),
                {"agent_id": agent_id},
            ).fetchone()
        if row is None:
            mailbox = AgentMailbox(agent_id=agent_id)
            return self.update_agent_mailbox(mailbox)
        return AgentMailbox(
            agent_id=row[0],
            pending_messages=[
                AgentMessage.model_validate(item)
                for item in (
                    row[1] if isinstance(row[1], list) else json.loads(row[1]) if row[1] else []
                )
            ],
            history=[
                AgentMessage.model_validate(item)
                for item in (
                    row[2] if isinstance(row[2], list) else json.loads(row[2]) if row[2] else []
                )
            ],
        )

    def update_agent_mailbox(self, mailbox: AgentMailbox) -> AgentMailbox:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_agent_mailboxes (agent_id, pending_messages, history)
                VALUES (:agent_id, :pending_messages, :history)
                ON CONFLICT (agent_id)
                DO UPDATE SET pending_messages = :pending_messages, history = :history
                """),
                {
                    "agent_id": mailbox.agent_id,
                    "pending_messages": json.dumps(
                        [message.model_dump(mode="json") for message in mailbox.pending_messages]
                    ),
                    "history": json.dumps(
                        [message.model_dump(mode="json") for message in mailbox.history]
                    ),
                },
            )
            session.commit()
        return mailbox

    def create_agent_message(self, team_id: str, message: AgentMessage) -> AgentMessage:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_agent_messages (id, team_id, sender, receiver, timestamp, type, payload, correlation_id, reply_to)
                VALUES (:id, :team_id, :sender, :receiver, :timestamp, :type, :payload, :correlation_id, :reply_to)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": message.id,
                    "team_id": team_id,
                    "sender": message.sender,
                    "receiver": message.receiver,
                    "timestamp": message.timestamp,
                    "type": message.type.value,
                    "payload": json.dumps(message.payload, default=_json_value),
                    "correlation_id": message.correlation_id,
                    "reply_to": message.reply_to,
                },
            )
            session.commit()
        return message

    def list_agent_messages(self, team_id: str) -> list[AgentMessage]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT id, sender, receiver, timestamp, type, payload, correlation_id, reply_to
                FROM atlas_agent_messages
                WHERE team_id = :team_id
                ORDER BY timestamp ASC, id ASC
                """),
                {"team_id": team_id},
            ).fetchall()
        return [
            AgentMessage(
                id=row[0],
                sender=row[1],
                receiver=row[2],
                timestamp=row[3],
                type=AgentMessageType(row[4]),
                payload=(
                    row[5] if isinstance(row[5], dict) else json.loads(row[5]) if row[5] else {}
                ),
                correlation_id=row[6],
                reply_to=row[7],
            )
            for row in rows
        ]

    def create_agent_conversation(self, conversation: AgentConversation) -> AgentConversation:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_agent_conversations (id, team_id, participant_ids, message_ids, created_at)
                VALUES (:id, :team_id, :participant_ids, :message_ids, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": conversation.id,
                    "team_id": conversation.team_id,
                    "participant_ids": json.dumps(conversation.participant_ids),
                    "message_ids": json.dumps(conversation.message_ids),
                    "created_at": conversation.created_at,
                },
            )
            session.commit()
        return conversation

    def create_graph_node(self, node: KnowledgeNode) -> KnowledgeNode:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_graph_nodes (id, node_type, label, project_id, workspace_id, source_id, metadata, archived, created_at)
                VALUES (:id, :node_type, :label, :project_id, :workspace_id, :source_id, :metadata, :archived, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": node.id,
                    "node_type": node.node_type,
                    "label": node.label,
                    "project_id": node.project_id,
                    "workspace_id": node.workspace_id,
                    "source_id": node.source_id,
                    "metadata": json.dumps(node.metadata, default=_json_value),
                    "archived": node.archived,
                    "created_at": node.created_at,
                },
            )
            session.commit()
        return node

    def archive_graph_node(self, node_id: str) -> bool:
        with SessionLocal() as session:
            result = session.execute(
                text("UPDATE atlas_graph_nodes SET archived = TRUE WHERE id = :node_id"),
                {"node_id": node_id},
            )
            session.commit()
        return bool(getattr(result, "rowcount", 0) > 0)

    def create_graph_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_graph_edges (id, relationship, from_node, to_node, metadata, created_at)
                VALUES (:id, :relationship, :from_node, :to_node, :metadata, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": edge.id,
                    "relationship": edge.relationship.value,
                    "from_node": edge.from_node,
                    "to_node": edge.to_node,
                    "metadata": json.dumps(edge.metadata, default=_json_value),
                    "created_at": edge.created_at,
                },
            )
            session.commit()
        return edge

    def list_graph_nodes(self, project_id: str | None = None) -> list[KnowledgeNode]:
        with SessionLocal() as session:
            if project_id is None:
                rows = session.execute(
                    text(
                        "SELECT id, node_type, label, project_id, workspace_id, source_id, metadata, archived, created_at FROM atlas_graph_nodes ORDER BY created_at ASC"
                    )
                ).fetchall()
            else:
                rows = session.execute(
                    text(
                        "SELECT id, node_type, label, project_id, workspace_id, source_id, metadata, archived, created_at FROM atlas_graph_nodes WHERE project_id = :project_id ORDER BY created_at ASC"
                    ),
                    {"project_id": project_id},
                ).fetchall()
        return [
            KnowledgeNode(
                id=row[0],
                node_type=row[1],
                label=row[2],
                project_id=row[3],
                workspace_id=row[4],
                source_id=row[5],
                metadata=(
                    row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {}
                ),
                archived=bool(row[7]),
                created_at=row[8],
            )
            for row in rows
        ]

    def get_graph_node(self, node_id: str) -> KnowledgeNode | None:
        with SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT id, node_type, label, project_id, workspace_id, source_id, metadata, archived, created_at FROM atlas_graph_nodes WHERE id = :node_id"
                ),
                {"node_id": node_id},
            ).fetchone()
        if row is None:
            return None
        return KnowledgeNode(
            id=row[0],
            node_type=row[1],
            label=row[2],
            project_id=row[3],
            workspace_id=row[4],
            source_id=row[5],
            metadata=row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {},
            archived=bool(row[7]),
            created_at=row[8],
        )

    def list_graph_edges(self) -> list[KnowledgeEdge]:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT id, relationship, from_node, to_node, metadata, created_at FROM atlas_graph_edges ORDER BY created_at ASC"
                )
            ).fetchall()
        return [
            KnowledgeEdge(
                id=row[0],
                relationship=RelationshipType(row[1]),
                from_node=row[2],
                to_node=row[3],
                metadata=(
                    row[4] if isinstance(row[4], dict) else json.loads(row[4]) if row[4] else {}
                ),
                created_at=row[5],
            )
            for row in rows
        ]

    def create_graph_snapshot(self, snapshot: GraphSnapshot) -> GraphSnapshot:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_graph_snapshots (id, scope_type, scope_id, node_ids, edge_ids, created_at)
                VALUES (:id, :scope_type, :scope_id, :node_ids, :edge_ids, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": snapshot.id,
                    "scope_type": snapshot.scope_type,
                    "scope_id": snapshot.scope_id,
                    "node_ids": json.dumps(snapshot.node_ids),
                    "edge_ids": json.dumps(snapshot.edge_ids),
                    "created_at": snapshot.created_at,
                },
            )
            session.commit()
        return snapshot

    def create_schedule(self, schedule: ExecutionSchedule) -> ExecutionSchedule:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_schedules (
                    schedule_id, plan_id, agent_id, created_at, priority,
                    estimated_finish_time, queue_entries, blocked_entries,
                    parallel_groups, resume_tokens, queue_metadata, updated_at
                )
                VALUES (
                    :schedule_id, :plan_id, :agent_id, :created_at, :priority,
                    :estimated_finish_time, :queue_entries, :blocked_entries,
                    :parallel_groups, :resume_tokens, :queue_metadata, :updated_at
                )
                ON CONFLICT (schedule_id) DO NOTHING
                """),
                {
                    "schedule_id": schedule.schedule_id,
                    "plan_id": schedule.plan_id,
                    "agent_id": schedule.agent_id,
                    "created_at": schedule.created_at,
                    "priority": schedule.priority.value,
                    "estimated_finish_time": schedule.estimated_finish_time,
                    "queue_entries": json.dumps(
                        [entry.model_dump(mode="json") for entry in schedule.queue_entries]
                    ),
                    "blocked_entries": json.dumps(schedule.blocked_entries),
                    "parallel_groups": json.dumps(schedule.parallel_groups),
                    "resume_tokens": json.dumps(
                        [token.model_dump(mode="json") for token in schedule.resume_tokens]
                    ),
                    "queue_metadata": json.dumps(schedule.queue_metadata, default=_json_value),
                    "updated_at": schedule.created_at,
                },
            )
            session.commit()
        return schedule

    def get_schedule(self, schedule_id: str) -> ExecutionSchedule | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                    SELECT schedule_id, plan_id, agent_id, created_at, priority,
                           estimated_finish_time, queue_entries, blocked_entries,
                           parallel_groups, resume_tokens, queue_metadata
                    FROM atlas_schedules
                    WHERE schedule_id = :schedule_id
                    """),
                {"schedule_id": schedule_id},
            ).fetchone()
        if row is None:
            return None
        queue_entries_raw = (
            row[6] if isinstance(row[6], list) else json.loads(row[6]) if row[6] else []
        )
        blocked_entries_raw = (
            row[7] if isinstance(row[7], list) else json.loads(row[7]) if row[7] else []
        )
        parallel_groups_raw = (
            row[8] if isinstance(row[8], list) else json.loads(row[8]) if row[8] else []
        )
        resume_tokens_raw = (
            row[9] if isinstance(row[9], list) else json.loads(row[9]) if row[9] else []
        )
        metadata_raw = (
            row[10] if isinstance(row[10], dict) else json.loads(row[10]) if row[10] else {}
        )
        return ExecutionSchedule(
            schedule_id=row[0],
            plan_id=row[1],
            agent_id=row[2],
            created_at=row[3],
            priority=SchedulerPriority(row[4]),
            estimated_finish_time=row[5],
            queue_entries=[ScheduleQueueEntry.model_validate(item) for item in queue_entries_raw],
            blocked_entries=[str(item) for item in blocked_entries_raw],
            parallel_groups=[[str(node) for node in group] for group in parallel_groups_raw],
            resume_tokens=[ResumeToken.model_validate(item) for item in resume_tokens_raw],
            queue_metadata=metadata_raw,
        )

    def list_schedules(self, agent_id: str | None = None) -> list[ExecutionSchedule]:
        with SessionLocal() as session:
            if agent_id is None:
                rows = session.execute(
                    text("""
                        SELECT schedule_id
                        FROM atlas_schedules
                        ORDER BY created_at DESC
                        """)
                ).fetchall()
            else:
                rows = session.execute(
                    text("""
                        SELECT schedule_id
                        FROM atlas_schedules
                        WHERE agent_id = :agent_id
                        ORDER BY created_at DESC
                        """),
                    {"agent_id": agent_id},
                ).fetchall()
        result: list[ExecutionSchedule] = []
        for row in rows:
            schedule = self.get_schedule(row[0])
            if schedule is not None:
                result.append(schedule)
        return result

    def update_schedule(self, schedule: ExecutionSchedule) -> ExecutionSchedule:
        with SessionLocal() as session:
            session.execute(
                text("""
                    UPDATE atlas_schedules
                    SET priority = :priority,
                        estimated_finish_time = :estimated_finish_time,
                        queue_entries = :queue_entries,
                        blocked_entries = :blocked_entries,
                        parallel_groups = :parallel_groups,
                        resume_tokens = :resume_tokens,
                        queue_metadata = :queue_metadata,
                        updated_at = now()
                    WHERE schedule_id = :schedule_id
                    """),
                {
                    "schedule_id": schedule.schedule_id,
                    "priority": schedule.priority.value,
                    "estimated_finish_time": schedule.estimated_finish_time,
                    "queue_entries": json.dumps(
                        [entry.model_dump(mode="json") for entry in schedule.queue_entries]
                    ),
                    "blocked_entries": json.dumps(schedule.blocked_entries),
                    "parallel_groups": json.dumps(schedule.parallel_groups),
                    "resume_tokens": json.dumps(
                        [token.model_dump(mode="json") for token in schedule.resume_tokens]
                    ),
                    "queue_metadata": json.dumps(schedule.queue_metadata, default=_json_value),
                },
            )
            session.commit()
        return schedule

    def create_runtime_execution(self, execution: RuntimeExecutionRecord) -> RuntimeExecutionRecord:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_runtime_executions (
                    execution_id, schedule_id, entry_id, agent_id, plan_id, action,
                    payload, status, attempts, retry_policy, created_at, updated_at,
                    started_at, heartbeat_at, deadline_at, completed_at, timeout_reason,
                    error, provider_name, run_id, job_id, asset_id, approval_id,
                    worker_id, lease_id, reservation_id, placement_reason, output,
                    cancellation_requested, timeline
                )
                VALUES (
                    :execution_id, :schedule_id, :entry_id, :agent_id, :plan_id, :action,
                    :payload, :status, :attempts, :retry_policy, :created_at, :updated_at,
                    :started_at, :heartbeat_at, :deadline_at, :completed_at, :timeout_reason,
                    :error, :provider_name, :run_id, :job_id, :asset_id, :approval_id,
                    :worker_id, :lease_id, :reservation_id, :placement_reason, :output,
                    :cancellation_requested, :timeline
                )
                ON CONFLICT (execution_id) DO NOTHING
                """),
                {
                    "execution_id": execution.execution_id,
                    "schedule_id": execution.schedule_id,
                    "entry_id": execution.entry_id,
                    "agent_id": execution.agent_id,
                    "plan_id": execution.plan_id,
                    "action": execution.action,
                    "payload": json.dumps(execution.payload, default=_json_value),
                    "status": execution.status.value,
                    "attempts": execution.attempts,
                    "retry_policy": json.dumps(execution.retry_policy.model_dump(mode="json")),
                    "created_at": execution.created_at,
                    "updated_at": execution.updated_at,
                    "started_at": execution.started_at,
                    "heartbeat_at": execution.heartbeat_at,
                    "deadline_at": execution.deadline_at,
                    "completed_at": execution.completed_at,
                    "timeout_reason": execution.timeout_reason,
                    "error": execution.error,
                    "provider_name": execution.provider_name,
                    "run_id": execution.run_id,
                    "job_id": execution.job_id,
                    "asset_id": execution.asset_id,
                    "approval_id": execution.approval_id,
                    "worker_id": execution.worker_id,
                    "lease_id": execution.lease_id,
                    "reservation_id": execution.reservation_id,
                    "placement_reason": execution.placement_reason,
                    "output": json.dumps(execution.output, default=_json_value),
                    "cancellation_requested": execution.cancellation_requested,
                    "timeline": json.dumps(execution.timeline, default=_json_value),
                },
            )
            session.commit()
        return execution

    def update_runtime_execution(self, execution: RuntimeExecutionRecord) -> RuntimeExecutionRecord:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_runtime_executions
                SET status = :status,
                    attempts = :attempts,
                    retry_policy = :retry_policy,
                    updated_at = :updated_at,
                    started_at = :started_at,
                    heartbeat_at = :heartbeat_at,
                    deadline_at = :deadline_at,
                    completed_at = :completed_at,
                    timeout_reason = :timeout_reason,
                    error = :error,
                    provider_name = :provider_name,
                    run_id = :run_id,
                    job_id = :job_id,
                    asset_id = :asset_id,
                    approval_id = :approval_id,
                    worker_id = :worker_id,
                    lease_id = :lease_id,
                    reservation_id = :reservation_id,
                    placement_reason = :placement_reason,
                    output = :output,
                    cancellation_requested = :cancellation_requested,
                    timeline = :timeline
                WHERE execution_id = :execution_id
                """),
                {
                    "execution_id": execution.execution_id,
                    "status": execution.status.value,
                    "attempts": execution.attempts,
                    "retry_policy": json.dumps(execution.retry_policy.model_dump(mode="json")),
                    "updated_at": execution.updated_at,
                    "started_at": execution.started_at,
                    "heartbeat_at": execution.heartbeat_at,
                    "deadline_at": execution.deadline_at,
                    "completed_at": execution.completed_at,
                    "timeout_reason": execution.timeout_reason,
                    "error": execution.error,
                    "provider_name": execution.provider_name,
                    "run_id": execution.run_id,
                    "job_id": execution.job_id,
                    "asset_id": execution.asset_id,
                    "approval_id": execution.approval_id,
                    "worker_id": execution.worker_id,
                    "lease_id": execution.lease_id,
                    "reservation_id": execution.reservation_id,
                    "placement_reason": execution.placement_reason,
                    "output": json.dumps(execution.output, default=_json_value),
                    "cancellation_requested": execution.cancellation_requested,
                    "timeline": json.dumps(execution.timeline, default=_json_value),
                },
            )
            session.commit()
        return execution

    def get_runtime_execution(self, execution_id: str) -> RuntimeExecutionRecord | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT execution_id, schedule_id, entry_id, agent_id, plan_id, action,
                       payload, status, attempts, retry_policy, created_at, updated_at,
                       started_at, heartbeat_at, deadline_at, completed_at, timeout_reason,
                       error, provider_name, run_id, job_id, asset_id, approval_id,
                       worker_id, lease_id, reservation_id, placement_reason, output,
                       cancellation_requested, timeline
                FROM atlas_runtime_executions
                WHERE execution_id = :execution_id
                """),
                {"execution_id": execution_id},
            ).fetchone()
        if row is None:
            return None
        return self._row_to_runtime_execution(row)

    def list_runtime_executions(self) -> list[RuntimeExecutionRecord]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT execution_id, schedule_id, entry_id, agent_id, plan_id, action,
                       payload, status, attempts, retry_policy, created_at, updated_at,
                       started_at, heartbeat_at, deadline_at, completed_at, timeout_reason,
                       error, provider_name, run_id, job_id, asset_id, approval_id,
                       worker_id, lease_id, reservation_id, placement_reason, output,
                       cancellation_requested, timeline
                FROM atlas_runtime_executions
                ORDER BY created_at DESC
                """)
            ).fetchall()
        return [self._row_to_runtime_execution(row) for row in rows]

    def list_running_runtime_executions(self) -> list[RuntimeExecutionRecord]:
        active = {
            RuntimeExecutionStatus.PENDING.value,
            RuntimeExecutionStatus.QUEUED.value,
            RuntimeExecutionStatus.PREPARING.value,
            RuntimeExecutionStatus.RUNNING.value,
        }
        return [item for item in self.list_runtime_executions() if item.status.value in active]

    def list_runtime_history(self) -> list[RuntimeExecutionRecord]:
        terminal = {
            RuntimeExecutionStatus.COMPLETED.value,
            RuntimeExecutionStatus.FAILED.value,
            RuntimeExecutionStatus.CANCELLED.value,
            RuntimeExecutionStatus.TIMED_OUT.value,
        }
        return [item for item in self.list_runtime_executions() if item.status.value in terminal]

    def list_agent_memory_references(self, agent_id: str) -> list[AgentMemoryReference]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT id, memory_id, agent_id, kind, asset_id, created_at
                FROM atlas_agent_memory_references
                WHERE agent_id = :agent_id
                ORDER BY created_at DESC
                """),
                {"agent_id": agent_id},
            ).fetchall()
        return [
            AgentMemoryReference(
                id=row[0],
                memory_id=row[1],
                agent_id=row[2],
                kind=row[3],
                asset_id=row[4],
                created_at=row[5],
            )
            for row in rows
        ]

    def get_execution_decision(self, decision_id: str) -> ExecutionDecision | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT decision_id, capability_id, recipe_id, executor_id, provider_id,
                       model_id, reason, confidence, timestamp
                FROM atlas_execution_decisions
                WHERE decision_id = :decision_id
                """),
                {"decision_id": decision_id},
            ).fetchone()
        if row is None:
            return None
        return ExecutionDecision(
            decision_id=row[0],
            capability_id=row[1],
            recipe_id=row[2],
            executor_id=row[3],
            provider_id=row[4],
            model_id=row[5],
            reason=row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {},
            confidence=row[7],
            timestamp=row[8],
        )

    def get_asset(self, asset_id: str) -> Asset | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT
                    id, project_id, workflow_id, run_id, job_id, parent_asset_id, version,
                    type, uri, mime_type, file_size, content_hash, metadata, tags,
                    source_asset_ids, thumbnail_uri, preview_uri, search_index,
                    vector_index, embeddings, ocr_text, transcript, ai_summary,
                    created_at, updated_at
                FROM atlas_assets
                WHERE id = :asset_id AND deleted_at IS NULL
                """),
                {"asset_id": asset_id},
            ).fetchone()
        if row is None:
            return None
        return self._row_to_asset(row)

    def list_assets(self, project_id: str | None = None) -> list[Asset]:
        with SessionLocal() as session:
            if project_id is None:
                rows = session.execute(
                    text("""
                    SELECT
                        id, project_id, workflow_id, run_id, job_id, parent_asset_id, version,
                        type, uri, mime_type, file_size, content_hash, metadata, tags,
                        source_asset_ids, thumbnail_uri, preview_uri, search_index,
                        vector_index, embeddings, ocr_text, transcript, ai_summary,
                        created_at, updated_at
                    FROM atlas_assets
                    WHERE deleted_at IS NULL
                    ORDER BY created_at DESC
                    """),
                ).fetchall()
            else:
                rows = session.execute(
                    text("""
                    SELECT
                        id, project_id, workflow_id, run_id, job_id, parent_asset_id, version,
                        type, uri, mime_type, file_size, content_hash, metadata, tags,
                        source_asset_ids, thumbnail_uri, preview_uri, search_index,
                        vector_index, embeddings, ocr_text, transcript, ai_summary,
                        created_at, updated_at
                    FROM atlas_assets
                    WHERE project_id = :project_id AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    """),
                    {"project_id": project_id},
                ).fetchall()
        return [self._row_to_asset(row) for row in rows]

    def list_child_assets(self, parent_asset_id: str) -> list[Asset]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT
                    id, project_id, workflow_id, run_id, job_id, parent_asset_id, version,
                    type, uri, mime_type, file_size, content_hash, metadata, tags,
                    source_asset_ids, thumbnail_uri, preview_uri, search_index,
                    vector_index, embeddings, ocr_text, transcript, ai_summary,
                    created_at, updated_at
                FROM atlas_assets
                WHERE parent_asset_id = :parent_asset_id AND deleted_at IS NULL
                ORDER BY created_at ASC
                """),
                {"parent_asset_id": parent_asset_id},
            ).fetchall()
        return [self._row_to_asset(row) for row in rows]

    def list_derived_assets(self, source_asset_id: str) -> list[Asset]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT
                    id, project_id, workflow_id, run_id, job_id, parent_asset_id, version,
                    type, uri, mime_type, file_size, content_hash, metadata, tags,
                    source_asset_ids, thumbnail_uri, preview_uri, search_index,
                    vector_index, embeddings, ocr_text, transcript, ai_summary,
                    created_at, updated_at
                FROM atlas_assets
                WHERE deleted_at IS NULL AND source_asset_ids @> :source_filter::jsonb
                ORDER BY created_at ASC
                """),
                {"source_filter": json.dumps([source_asset_id])},
            ).fetchall()
        return [self._row_to_asset(row) for row in rows]

    def list_assets_by_run(self, run_id: str) -> list[Asset]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT
                    id, project_id, workflow_id, run_id, job_id, parent_asset_id, version,
                    type, uri, mime_type, file_size, content_hash, metadata, tags,
                    source_asset_ids, thumbnail_uri, preview_uri, search_index,
                    vector_index, embeddings, ocr_text, transcript, ai_summary,
                    created_at, updated_at
                FROM atlas_assets
                WHERE run_id = :run_id AND deleted_at IS NULL
                ORDER BY created_at DESC
                """),
                {"run_id": run_id},
            ).fetchall()
        return [self._row_to_asset(row) for row in rows]

    def list_assets_by_job(self, job_id: str) -> list[Asset]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT
                    id, project_id, workflow_id, run_id, job_id, parent_asset_id, version,
                    type, uri, mime_type, file_size, content_hash, metadata, tags,
                    source_asset_ids, thumbnail_uri, preview_uri, search_index,
                    vector_index, embeddings, ocr_text, transcript, ai_summary,
                    created_at, updated_at
                FROM atlas_assets
                WHERE job_id = :job_id AND deleted_at IS NULL
                ORDER BY created_at DESC
                """),
                {"job_id": job_id},
            ).fetchall()
        return [self._row_to_asset(row) for row in rows]

    def update_asset(self, asset: Asset) -> Asset:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_assets
                SET
                    project_id = :project_id,
                    workflow_id = :workflow_id,
                    run_id = :run_id,
                    job_id = :job_id,
                    parent_asset_id = :parent_asset_id,
                    version = :version,
                    type = :type,
                    uri = :uri,
                    mime_type = :mime_type,
                    file_size = :file_size,
                    content_hash = :content_hash,
                    metadata = :metadata,
                    tags = :tags,
                    source_asset_ids = :source_asset_ids,
                    thumbnail_uri = :thumbnail_uri,
                    preview_uri = :preview_uri,
                    search_index = :search_index,
                    vector_index = :vector_index,
                    embeddings = :embeddings,
                    ocr_text = :ocr_text,
                    transcript = :transcript,
                    ai_summary = :ai_summary,
                    updated_at = :updated_at
                WHERE id = :id
                """),
                {
                    "id": asset.id,
                    "project_id": asset.project_id,
                    "workflow_id": asset.workflow_id,
                    "run_id": asset.run_id,
                    "job_id": asset.job_id,
                    "parent_asset_id": asset.parent_asset_id,
                    "version": asset.version,
                    "type": asset.type,
                    "uri": asset.uri,
                    "mime_type": asset.mime_type,
                    "file_size": asset.file_size,
                    "content_hash": asset.content_hash,
                    "metadata": json.dumps(asset.metadata),
                    "tags": json.dumps(asset.tags),
                    "source_asset_ids": json.dumps(asset.source_asset_ids),
                    "thumbnail_uri": asset.thumbnail_uri,
                    "preview_uri": asset.preview_uri,
                    "search_index": json.dumps(asset.search_index),
                    "vector_index": json.dumps(asset.vector_index),
                    "embeddings": json.dumps(asset.embeddings),
                    "ocr_text": asset.ocr_text,
                    "transcript": asset.transcript,
                    "ai_summary": asset.ai_summary,
                    "updated_at": asset.updated_at,
                },
            )
            session.commit()
        return asset

    def delete_asset(self, asset_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                text("UPDATE atlas_assets SET deleted_at = now() WHERE id = :asset_id"),
                {"asset_id": asset_id},
            )
            session.commit()

    def list_runs(self) -> list[Run]:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT id, title, description, studio, workspace_id, project_id, workflow_id, produced_asset_ids, status, created_at FROM atlas_runs ORDER BY created_at DESC"
                )
            ).fetchall()
        return [
            Run(
                id=row[0],
                title=row[1],
                description=row[2],
                studio=row[3],
                workspace_id=row[4],
                project_id=row[5],
                workflow_id=row[6],
                produced_asset_ids=(
                    row[7] if isinstance(row[7], list) else json.loads(row[7]) if row[7] else []
                ),
                status=JobStatus(row[8]),
                created_at=row[9],
            )
            for row in rows
        ]

    def get_run(self, run_id: str) -> Run | None:
        with SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT id, title, description, studio, workspace_id, project_id, workflow_id, produced_asset_ids, status, created_at FROM atlas_runs WHERE id = :run_id"
                ),
                {"run_id": run_id},
            ).fetchone()
        if row is None:
            return None
        return Run(
            id=row[0],
            title=row[1],
            description=row[2],
            studio=row[3],
            workspace_id=row[4],
            project_id=row[5],
            workflow_id=row[6],
            produced_asset_ids=(
                row[7] if isinstance(row[7], list) else json.loads(row[7]) if row[7] else []
            ),
            status=JobStatus(row[8]),
            created_at=row[9],
        )

    def list_jobs(self) -> list[Job]:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT id, run_id, action, payload, status, attempts, priority, capability_req, execution_decision_id, provider_name, output, produced_asset_ids, created_at FROM atlas_jobs ORDER BY created_at DESC"
                )
            ).fetchall()
        return [
            Job(
                id=row[0],
                run_id=row[1],
                action=row[2],
                payload=(
                    row[3] if isinstance(row[3], dict) else json.loads(row[3]) if row[3] else {}
                ),
                status=JobStatus(row[4]),
                attempts=row[5],
                priority=row[6],
                capability_req=normalize_capability_request(
                    row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {}
                ),
                execution_decision_id=row[8],
                provider_name=row[9],
                output=(
                    row[10] if isinstance(row[10], dict) else json.loads(row[10]) if row[10] else {}
                ),
                produced_asset_ids=(
                    row[11] if isinstance(row[11], list) else json.loads(row[11]) if row[11] else []
                ),
                created_at=row[12],
            )
            for row in rows
        ]

    def list_jobs_by_run(self, run_id: str) -> list[Job]:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT id, run_id, action, payload, status, attempts, priority, capability_req, execution_decision_id, provider_name, output, produced_asset_ids, created_at FROM atlas_jobs WHERE run_id = :run_id ORDER BY created_at DESC"
                ),
                {"run_id": run_id},
            ).fetchall()
        return [
            Job(
                id=row[0],
                run_id=row[1],
                action=row[2],
                payload=(
                    row[3] if isinstance(row[3], dict) else json.loads(row[3]) if row[3] else {}
                ),
                status=JobStatus(row[4]),
                attempts=row[5],
                priority=row[6],
                capability_req=normalize_capability_request(
                    row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {}
                ),
                execution_decision_id=row[8],
                provider_name=row[9],
                output=(
                    row[10] if isinstance(row[10], dict) else json.loads(row[10]) if row[10] else {}
                ),
                produced_asset_ids=(
                    row[11] if isinstance(row[11], list) else json.loads(row[11]) if row[11] else []
                ),
                created_at=row[12],
            )
            for row in rows
        ]

    def list_runs_by_project(self, project_id: str) -> list[Run]:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT id, title, description, studio, workspace_id, project_id, workflow_id, produced_asset_ids, status, created_at FROM atlas_runs WHERE project_id = :project_id ORDER BY created_at DESC"
                ),
                {"project_id": project_id},
            ).fetchall()
        return [
            Run(
                id=row[0],
                title=row[1],
                description=row[2],
                studio=row[3],
                workspace_id=row[4],
                project_id=row[5],
                workflow_id=row[6],
                produced_asset_ids=(
                    row[7] if isinstance(row[7], list) else json.loads(row[7]) if row[7] else []
                ),
                status=JobStatus(row[8]),
                created_at=row[9],
            )
            for row in rows
        ]

    def list_jobs_by_project(self, project_id: str) -> list[Job]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                    SELECT j.id, j.run_id, j.action, j.payload, j.status, j.attempts, j.priority,
                           j.capability_req, j.execution_decision_id, j.provider_name, j.output,
                           j.produced_asset_ids, j.created_at
                    FROM atlas_jobs j
                    JOIN atlas_runs r ON r.id = j.run_id
                    WHERE r.project_id = :project_id
                    ORDER BY j.created_at DESC
                    """),
                {"project_id": project_id},
            ).fetchall()
        return [
            Job(
                id=row[0],
                run_id=row[1],
                action=row[2],
                payload=(
                    row[3] if isinstance(row[3], dict) else json.loads(row[3]) if row[3] else {}
                ),
                status=JobStatus(row[4]),
                attempts=row[5],
                priority=row[6],
                capability_req=normalize_capability_request(
                    row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {}
                ),
                execution_decision_id=row[8],
                provider_name=row[9],
                output=(
                    row[10] if isinstance(row[10], dict) else json.loads(row[10]) if row[10] else {}
                ),
                produced_asset_ids=(
                    row[11] if isinstance(row[11], list) else json.loads(row[11]) if row[11] else []
                ),
                created_at=row[12],
            )
            for row in rows
        ]

    def add_asset_to_job(self, job_id: str, asset_id: str) -> None:
        with SessionLocal() as session:
            current = session.execute(
                text("SELECT produced_asset_ids FROM atlas_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            ).fetchone()
            current_ids = (
                current[0]
                if current and isinstance(current[0], list)
                else json.loads(current[0])
                if current and current[0]
                else []
            )
            if asset_id not in current_ids:
                current_ids.append(asset_id)
                session.execute(
                    text(
                        "UPDATE atlas_jobs SET produced_asset_ids = :asset_ids WHERE id = :job_id"
                    ),
                    {"asset_ids": json.dumps(current_ids), "job_id": job_id},
                )
                session.commit()

    def add_asset_to_run(self, run_id: str, asset_id: str) -> None:
        with SessionLocal() as session:
            current = session.execute(
                text("SELECT produced_asset_ids FROM atlas_runs WHERE id = :run_id"),
                {"run_id": run_id},
            ).fetchone()
            current_ids = (
                current[0]
                if current and isinstance(current[0], list)
                else json.loads(current[0])
                if current and current[0]
                else []
            )
            if asset_id not in current_ids:
                current_ids.append(asset_id)
                session.execute(
                    text(
                        "UPDATE atlas_runs SET produced_asset_ids = :asset_ids WHERE id = :run_id"
                    ),
                    {"asset_ids": json.dumps(current_ids), "run_id": run_id},
                )
                session.commit()

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        provider_name: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> None:
        with SessionLocal() as session:
            query = "UPDATE atlas_jobs SET status = :status"
            params = {"status": status.value, "job_id": job_id}
            if provider_name is not None:
                query += ", provider_name = :provider_name"
                params["provider_name"] = provider_name
            if output is not None:
                query += ", output = :output"
                params["output"] = json.dumps(output)
            query += " WHERE id = :job_id"
            session.execute(text(query), params)
            session.commit()

    def assign_execution_decision(self, job_id: str, decision: ExecutionDecision) -> None:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_jobs
                SET execution_decision_id = :decision_id,
                    provider_name = :provider_id
                WHERE id = :job_id
                """),
                {
                    "decision_id": decision.decision_id,
                    "provider_id": decision.provider_id,
                    "job_id": job_id,
                },
            )
            session.commit()

    def update_run_status(self, run_id: str, status: JobStatus) -> None:
        with SessionLocal() as session:
            session.execute(
                text("UPDATE atlas_runs SET status = :status WHERE id = :run_id"),
                {"status": status.value, "run_id": run_id},
            )
            session.commit()

    def _row_to_asset(self, row: Any) -> Asset:
        return Asset(
            id=row[0],
            project_id=row[1] or "project-unassigned",
            workflow_id=row[2],
            run_id=row[3],
            job_id=row[4],
            parent_asset_id=row[5],
            version=row[6] or 1,
            type=row[7],
            uri=row[8],
            mime_type=row[9],
            file_size=row[10],
            content_hash=row[11],
            metadata=(
                row[12] if isinstance(row[12], dict) else json.loads(row[12]) if row[12] else {}
            ),
            tags=row[13] if isinstance(row[13], list) else json.loads(row[13]) if row[13] else [],
            source_asset_ids=(
                row[14] if isinstance(row[14], list) else json.loads(row[14]) if row[14] else []
            ),
            thumbnail_uri=row[15],
            preview_uri=row[16],
            search_index=(
                row[17] if isinstance(row[17], dict) else json.loads(row[17]) if row[17] else None
            ),
            vector_index=(
                row[18] if isinstance(row[18], dict) else json.loads(row[18]) if row[18] else None
            ),
            embeddings=(
                row[19] if isinstance(row[19], list) else json.loads(row[19]) if row[19] else None
            ),
            ocr_text=row[20],
            transcript=row[21],
            ai_summary=row[22],
            created_at=row[23],
            updated_at=row[24] or row[23],
        )

    def _row_to_runtime_execution(self, row: Any) -> RuntimeExecutionRecord:
        return RuntimeExecutionRecord(
            execution_id=row[0],
            schedule_id=row[1],
            entry_id=row[2],
            agent_id=row[3],
            plan_id=row[4],
            action=row[5],
            payload=row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {},
            status=RuntimeExecutionStatus(row[7]),
            attempts=row[8],
            retry_policy=RuntimeRetryPolicy.model_validate(
                row[9] if isinstance(row[9], dict) else json.loads(row[9]) if row[9] else {}
            ),
            created_at=row[10],
            updated_at=row[11],
            started_at=row[12],
            heartbeat_at=row[13],
            deadline_at=row[14],
            completed_at=row[15],
            timeout_reason=row[16],
            error=row[17],
            provider_name=row[18],
            run_id=row[19],
            job_id=row[20],
            asset_id=row[21],
            approval_id=row[22],
            worker_id=row[23],
            lease_id=row[24],
            reservation_id=row[25],
            placement_reason=row[26],
            output=row[27] if isinstance(row[27], dict) else json.loads(row[27]) if row[27] else {},
            cancellation_requested=bool(row[28]),
            timeline=(
                row[29] if isinstance(row[29], list) else json.loads(row[29]) if row[29] else []
            ),
        )

    def _row_to_agent_assignment(self, row: Any) -> AgentAssignment:
        return AgentAssignment(
            id=row[0],
            team_id=row[1],
            agent_id=row[2],
            role=AgentRole(row[3]),
            title=row[4],
            status=AgentAssignmentStatus(row[5]),
            capabilities=(
                row[6] if isinstance(row[6], list) else json.loads(row[6]) if row[6] else []
            ),
            allowed_actions=(
                row[7] if isinstance(row[7], list) else json.loads(row[7]) if row[7] else []
            ),
            permissions=[
                AgentPermission(value)
                for value in (
                    row[8] if isinstance(row[8], list) else json.loads(row[8]) if row[8] else []
                )
            ],
            resource_limits=(
                row[9] if isinstance(row[9], dict) else json.loads(row[9]) if row[9] else {}
            ),
            action=row[10],
            payload=(
                row[11] if isinstance(row[11], dict) else json.loads(row[11]) if row[11] else {}
            ),
            dependencies=(
                row[12] if isinstance(row[12], list) else json.loads(row[12]) if row[12] else []
            ),
            mailbox_id=row[13],
            schedule_id=row[14],
            runtime_execution_id=row[15],
            result_asset_id=row[16],
            error=row[17],
            created_at=row[18],
            updated_at=row[19],
        )

    def create_automation_rule(self, rule: AutomationRule) -> AutomationRule:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_automation_rules
                (id, project_id, workspace_id, name, description, trigger, conditions, actions, schedule, priority, enabled, dry_run, created_at, updated_at)
                VALUES (:id, :project_id, :workspace_id, :name, :description, :trigger, :conditions, :actions, :schedule, :priority, :enabled, :dry_run, :created_at, :updated_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": rule.id,
                    "project_id": rule.project_id,
                    "workspace_id": rule.workspace_id,
                    "name": rule.name,
                    "description": rule.description,
                    "trigger": json.dumps(rule.trigger.model_dump()),
                    "conditions": json.dumps([c.model_dump() for c in rule.conditions]),
                    "actions": json.dumps([a.model_dump() for a in rule.actions]),
                    "schedule": json.dumps(rule.schedule) if rule.schedule else None,
                    "priority": rule.priority,
                    "enabled": rule.enabled,
                    "dry_run": rule.dry_run,
                    "created_at": rule.created_at,
                    "updated_at": rule.updated_at,
                },
            )
            session.commit()
        return rule

    def get_automation_rule(self, rule_id: str) -> AutomationRule | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT id, project_id, workspace_id, name, description, trigger, conditions, actions, schedule, priority, enabled, dry_run, created_at, updated_at, disabled_at
                FROM atlas_automation_rules WHERE id = :rule_id
                """),
                {"rule_id": rule_id},
            ).fetchone()
        if row is None:
            return None
        return self._row_to_automation_rule(row)

    def list_automation_rules(
        self, project_id: str | None = None, workspace_id: str | None = None
    ) -> list[AutomationRule]:
        with SessionLocal() as session:
            query = "SELECT id, project_id, workspace_id, name, description, trigger, conditions, actions, schedule, priority, enabled, dry_run, created_at, updated_at, disabled_at FROM atlas_automation_rules WHERE 1=1"
            params: dict[str, Any] = {}

            if project_id:
                query += " AND project_id = :project_id"
                params["project_id"] = project_id

            if workspace_id:
                query += " AND workspace_id = :workspace_id"
                params["workspace_id"] = workspace_id

            rows = session.execute(text(query), params).fetchall()
        return [self._row_to_automation_rule(row) for row in rows]

    def update_automation_rule(self, rule: AutomationRule) -> AutomationRule:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_automation_rules
                SET name = :name, description = :description, trigger = :trigger, conditions = :conditions,
                    actions = :actions, schedule = :schedule, priority = :priority, enabled = :enabled, dry_run = :dry_run,
                    updated_at = :updated_at, disabled_at = :disabled_at
                WHERE id = :id
                """),
                {
                    "id": rule.id,
                    "name": rule.name,
                    "description": rule.description,
                    "trigger": json.dumps(rule.trigger.model_dump()),
                    "conditions": json.dumps([c.model_dump() for c in rule.conditions]),
                    "actions": json.dumps([a.model_dump() for a in rule.actions]),
                    "schedule": json.dumps(rule.schedule) if rule.schedule else None,
                    "priority": rule.priority,
                    "enabled": rule.enabled,
                    "dry_run": rule.dry_run,
                    "updated_at": rule.updated_at,
                    "disabled_at": rule.disabled_at,
                },
            )
            session.commit()
        return rule

    def delete_automation_rule(self, rule_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM atlas_automation_rules WHERE id = :id"), {"id": rule_id}
            )
            session.commit()

    def create_automation_run(self, run: AutomationRun) -> AutomationRun:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_automation_runs
                (id, rule_id, triggered_by, status, start_time, end_time, duration_ms, trigger_data, outputs, error, retries, created_at)
                VALUES (:id, :rule_id, :triggered_by, :status, :start_time, :end_time, :duration_ms, :trigger_data, :outputs, :error, :retries, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": run.id,
                    "rule_id": run.rule_id,
                    "triggered_by": run.triggered_by,
                    "status": run.status.value,
                    "start_time": run.start_time,
                    "end_time": run.end_time,
                    "duration_ms": run.duration_ms,
                    "trigger_data": json.dumps(run.trigger_data),
                    "outputs": json.dumps(run.outputs),
                    "error": run.error,
                    "retries": run.retries,
                    "created_at": run.created_at,
                },
            )
            session.commit()
        return run

    def update_automation_run(self, run: AutomationRun) -> AutomationRun:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_automation_runs
                SET status = :status, end_time = :end_time, duration_ms = :duration_ms,
                    outputs = :outputs, error = :error, retries = :retries
                WHERE id = :id
                """),
                {
                    "id": run.id,
                    "status": run.status.value,
                    "end_time": run.end_time,
                    "duration_ms": run.duration_ms,
                    "outputs": json.dumps(run.outputs),
                    "error": run.error,
                    "retries": run.retries,
                },
            )
            session.commit()
        return run

    def list_automation_runs(self, rule_id: str | None = None) -> list[AutomationRun]:
        with SessionLocal() as session:
            query = "SELECT id, rule_id, triggered_by, status, start_time, end_time, duration_ms, trigger_data, outputs, error, retries, created_at FROM atlas_automation_runs WHERE 1=1"
            params: dict[str, Any] = {}

            if rule_id:
                query += " AND rule_id = :rule_id"
                params["rule_id"] = rule_id

            query += " ORDER BY start_time DESC, id DESC"
            rows = session.execute(text(query), params).fetchall()
        return [self._row_to_automation_run(row) for row in rows]

    def create_automation_log(self, log: AutomationLog) -> AutomationLog:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_automation_logs (id, run_id, rule_id, level, message, actor, context, created_at)
                VALUES (:id, :run_id, :rule_id, :level, :message, :actor, :context, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": log.id,
                    "run_id": log.run_id,
                    "rule_id": log.rule_id,
                    "level": log.level.value,
                    "message": log.message,
                    "actor": log.actor,
                    "context": json.dumps(log.context),
                    "created_at": log.created_at,
                },
            )
            session.commit()
        return log

    def list_automation_logs(
        self, run_id: str | None = None, rule_id: str | None = None
    ) -> list[AutomationLog]:
        with SessionLocal() as session:
            query = "SELECT id, run_id, rule_id, level, message, actor, context, created_at FROM atlas_automation_logs WHERE 1=1"
            params: dict[str, Any] = {}

            if run_id:
                query += " AND run_id = :run_id"
                params["run_id"] = run_id

            if rule_id:
                query += " AND rule_id = :rule_id"
                params["rule_id"] = rule_id

            query += " ORDER BY created_at DESC, id DESC"
            rows = session.execute(text(query), params).fetchall()
        return [self._row_to_automation_log(row) for row in rows]

    def upsert_automation_schedule(self, schedule: AutomationSchedule) -> AutomationSchedule:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_automation_schedules (id, rule_id, schedule_id, next_run, last_run, created_at, updated_at)
                VALUES (:id, :rule_id, :schedule_id, :next_run, :last_run, :created_at, :updated_at)
                ON CONFLICT (id) DO UPDATE SET
                    schedule_id = :schedule_id,
                    next_run = :next_run,
                    last_run = :last_run,
                    updated_at = :updated_at
                """),
                {
                    "id": schedule.id,
                    "rule_id": schedule.rule_id,
                    "schedule_id": schedule.schedule_id,
                    "next_run": schedule.next_run,
                    "last_run": schedule.last_run,
                    "created_at": schedule.created_at,
                    "updated_at": schedule.updated_at,
                },
            )
            session.commit()
        return schedule

    def get_automation_schedule_for_rule(self, rule_id: str) -> AutomationSchedule | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT id, rule_id, schedule_id, next_run, last_run, created_at, updated_at
                FROM atlas_automation_schedules WHERE rule_id = :rule_id ORDER BY created_at LIMIT 1
                """),
                {"rule_id": rule_id},
            ).fetchone()
        if row is None:
            return None
        return AutomationSchedule(
            id=row[0],
            rule_id=row[1],
            schedule_id=row[2],
            next_run=row[3],
            last_run=row[4],
            created_at=row[5],
            updated_at=row[6],
        )

    def delete_automation_schedules_for_rule(self, rule_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM atlas_automation_schedules WHERE rule_id = :rule_id"),
                {"rule_id": rule_id},
            )
            session.commit()

    def _row_to_automation_rule(self, row: Any) -> AutomationRule:
        trigger_data = row[5] if isinstance(row[5], dict) else json.loads(row[5]) if row[5] else {}
        conditions_data = (
            row[6] if isinstance(row[6], list) else json.loads(row[6]) if row[6] else []
        )
        actions_data = row[7] if isinstance(row[7], list) else json.loads(row[7]) if row[7] else []
        schedule_data = (
            row[8] if isinstance(row[8], dict) else json.loads(row[8]) if row[8] else None
        )

        return AutomationRule(
            id=row[0],
            project_id=row[1],
            workspace_id=row[2],
            name=row[3],
            description=row[4],
            trigger=AutomationTrigger.model_validate(trigger_data),
            conditions=[AutomationCondition.model_validate(c) for c in conditions_data],
            actions=[AutomationAction.model_validate(a) for a in actions_data],
            schedule=schedule_data,
            priority=row[9],
            enabled=bool(row[10]),
            dry_run=bool(row[11]),
            created_at=row[12],
            updated_at=row[13],
            disabled_at=row[14],
        )

    def _row_to_automation_run(self, row: Any) -> AutomationRun:
        trigger_data = row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {}
        outputs_data = row[8] if isinstance(row[8], dict) else json.loads(row[8]) if row[8] else {}

        return AutomationRun(
            id=row[0],
            rule_id=row[1],
            triggered_by=row[2],
            status=AutomationRunStatus(row[3]),
            start_time=row[4],
            end_time=row[5],
            duration_ms=row[6],
            trigger_data=trigger_data,
            outputs=outputs_data,
            error=row[9],
            retries=row[10],
            created_at=row[11],
        )

    def _row_to_automation_log(self, row: Any) -> AutomationLog:
        context_data = row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {}

        return AutomationLog(
            id=row[0],
            run_id=row[1],
            rule_id=row[2],
            level=AutomationLogLevel(row[3]),
            message=row[4],
            actor=row[5],
            context=context_data,
            created_at=row[7],
        )

    # ------------------------------------------------------------------
    # Organization (Milestone 010). Audit records are append-only: there is
    # deliberately no update or delete method for atlas_audit_records.
    # ------------------------------------------------------------------

    def upsert_organization(self, organization: Organization) -> Organization:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_organizations (
                    id, name, slug, description, tenant_id, workspace_ids, branding,
                    license, allow_shared_pool, active, metadata, created_at, updated_at
                )
                VALUES (
                    :id, :name, :slug, :description, :tenant_id, :workspace_ids, :branding,
                    :license, :allow_shared_pool, :active, :metadata, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = :name, slug = :slug, description = :description,
                    workspace_ids = :workspace_ids, branding = :branding, license = :license,
                    allow_shared_pool = :allow_shared_pool, active = :active,
                    metadata = :metadata, updated_at = :updated_at
                """),
                {
                    "id": organization.id,
                    "name": organization.name,
                    "slug": organization.slug,
                    "description": organization.description,
                    "tenant_id": organization.tenant_id,
                    "workspace_ids": json.dumps(organization.workspace_ids),
                    "branding": json.dumps(organization.branding.model_dump(mode="json")),
                    "license": json.dumps(organization.license.model_dump(mode="json")),
                    "allow_shared_pool": organization.allow_shared_pool,
                    "active": organization.active,
                    "metadata": json.dumps(organization.metadata, default=_json_value),
                    "created_at": organization.created_at,
                    "updated_at": organization.updated_at,
                },
            )
            session.commit()
        return organization

    def get_organization(self, organization_id: str) -> Organization | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_ORGANIZATION_COLUMNS} FROM atlas_organizations WHERE id = :id"),
                {"id": organization_id},
            ).fetchone()
        return self._row_to_organization(row) if row else None

    def get_organization_by_slug(self, slug: str) -> Organization | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_ORGANIZATION_COLUMNS} FROM atlas_organizations WHERE slug = :slug"),
                {"slug": slug},
            ).fetchone()
        return self._row_to_organization(row) if row else None

    def list_organizations(self) -> list[Organization]:
        with SessionLocal() as session:
            rows = session.execute(
                text(f"SELECT {_ORGANIZATION_COLUMNS} FROM atlas_organizations ORDER BY name, id")
            ).fetchall()
        return [self._row_to_organization(row) for row in rows]

    def delete_organization(self, organization_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM atlas_organizations WHERE id = :id"), {"id": organization_id}
            )
            session.commit()

    def upsert_team(self, team: Team) -> Team:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_teams (
                    id, organization_id, name, kind, description, project_ids, studio_ids,
                    worker_ids, automation_rule_ids, metadata, created_at, updated_at
                )
                VALUES (
                    :id, :organization_id, :name, :kind, :description, :project_ids, :studio_ids,
                    :worker_ids, :automation_rule_ids, :metadata, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = :name, kind = :kind, description = :description,
                    project_ids = :project_ids, studio_ids = :studio_ids,
                    worker_ids = :worker_ids, automation_rule_ids = :automation_rule_ids,
                    metadata = :metadata, updated_at = :updated_at
                """),
                {
                    "id": team.id,
                    "organization_id": team.organization_id,
                    "name": team.name,
                    "kind": team.kind.value,
                    "description": team.description,
                    "project_ids": json.dumps(team.project_ids),
                    "studio_ids": json.dumps(team.studio_ids),
                    "worker_ids": json.dumps(team.worker_ids),
                    "automation_rule_ids": json.dumps(team.automation_rule_ids),
                    "metadata": json.dumps(team.metadata, default=_json_value),
                    "created_at": team.created_at,
                    "updated_at": team.updated_at,
                },
            )
            session.commit()
        return team

    def get_team(self, team_id: str) -> Team | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_TEAM_COLUMNS} FROM atlas_teams WHERE id = :id"),
                {"id": team_id},
            ).fetchone()
        return self._row_to_team(row) if row else None

    def list_teams(self, organization_id: str | None = None) -> list[Team]:
        query = f"SELECT {_TEAM_COLUMNS} FROM atlas_teams WHERE 1=1"
        params: dict[str, Any] = {}
        if organization_id is not None:
            query += " AND organization_id = :organization_id"
            params["organization_id"] = organization_id
        query += " ORDER BY name, id"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).fetchall()
        return [self._row_to_team(row) for row in rows]

    def upsert_role(self, role: Role) -> Role:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_roles (
                    id, name, description, permissions, organization_id, builtin,
                    metadata, created_at, updated_at
                )
                VALUES (
                    :id, :name, :description, :permissions, :organization_id, :builtin,
                    :metadata, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = :name, description = :description, permissions = :permissions,
                    builtin = :builtin, metadata = :metadata, updated_at = :updated_at
                """),
                {
                    "id": role.id,
                    "name": role.name,
                    "description": role.description,
                    "permissions": json.dumps([p.value for p in role.permissions]),
                    "organization_id": role.organization_id,
                    "builtin": role.builtin,
                    "metadata": json.dumps(role.metadata, default=_json_value),
                    "created_at": role.created_at,
                    "updated_at": role.updated_at,
                },
            )
            session.commit()
        return role

    def get_role(self, role_id: str) -> Role | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_ROLE_COLUMNS} FROM atlas_roles WHERE id = :id"),
                {"id": role_id},
            ).fetchone()
        return self._row_to_role(row) if row else None

    def list_roles(self) -> list[Role]:
        with SessionLocal() as session:
            rows = session.execute(
                text(f"SELECT {_ROLE_COLUMNS} FROM atlas_roles ORDER BY name, id")
            ).fetchall()
        return [self._row_to_role(row) for row in rows]

    def delete_role(self, role_id: str) -> None:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM atlas_roles WHERE id = :id"), {"id": role_id})
            session.commit()

    def upsert_identity(self, identity: Identity) -> Identity:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_identities (
                    id, subject, display_name, email, provider, provider_subject,
                    active, metadata, created_at, last_login_at
                )
                VALUES (
                    :id, :subject, :display_name, :email, :provider, :provider_subject,
                    :active, :metadata, :created_at, :last_login_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    display_name = :display_name, email = :email, provider = :provider,
                    provider_subject = :provider_subject, active = :active,
                    metadata = :metadata, last_login_at = :last_login_at
                """),
                {
                    "id": identity.id,
                    "subject": identity.subject,
                    "display_name": identity.display_name,
                    "email": identity.email,
                    "provider": identity.provider.value,
                    "provider_subject": identity.provider_subject,
                    "active": identity.active,
                    "metadata": json.dumps(identity.metadata, default=_json_value),
                    "created_at": identity.created_at,
                    "last_login_at": identity.last_login_at,
                },
            )
            session.commit()
        return identity

    def get_identity(self, identity_id: str) -> Identity | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_IDENTITY_COLUMNS} FROM atlas_identities WHERE id = :id"),
                {"id": identity_id},
            ).fetchone()
        return self._row_to_identity(row) if row else None

    def get_identity_by_subject(self, subject: str) -> Identity | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_IDENTITY_COLUMNS} FROM atlas_identities WHERE subject = :subject"),
                {"subject": subject},
            ).fetchone()
        return self._row_to_identity(row) if row else None

    def list_identities(self) -> list[Identity]:
        with SessionLocal() as session:
            rows = session.execute(
                text(f"SELECT {_IDENTITY_COLUMNS} FROM atlas_identities ORDER BY display_name, id")
            ).fetchall()
        return [self._row_to_identity(row) for row in rows]

    def upsert_membership(self, membership: Membership) -> Membership:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_memberships (
                    id, identity_id, organization_id, scope, scope_id, role_ids, team_ids,
                    active, expires_at, metadata, created_at, updated_at
                )
                VALUES (
                    :id, :identity_id, :organization_id, :scope, :scope_id, :role_ids, :team_ids,
                    :active, :expires_at, :metadata, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    scope = :scope, scope_id = :scope_id, role_ids = :role_ids,
                    team_ids = :team_ids, active = :active, expires_at = :expires_at,
                    metadata = :metadata, updated_at = :updated_at
                """),
                {
                    "id": membership.id,
                    "identity_id": membership.identity_id,
                    "organization_id": membership.organization_id,
                    "scope": membership.scope.value,
                    "scope_id": membership.scope_id,
                    "role_ids": json.dumps(membership.role_ids),
                    "team_ids": json.dumps(membership.team_ids),
                    "active": membership.active,
                    "expires_at": membership.expires_at,
                    "metadata": json.dumps(membership.metadata, default=_json_value),
                    "created_at": membership.created_at,
                    "updated_at": membership.updated_at,
                },
            )
            session.commit()
        return membership

    def get_membership(self, membership_id: str) -> Membership | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_MEMBERSHIP_COLUMNS} FROM atlas_memberships WHERE id = :id"),
                {"id": membership_id},
            ).fetchone()
        return self._row_to_membership(row) if row else None

    def list_memberships(
        self, organization_id: str | None = None, identity_id: str | None = None
    ) -> list[Membership]:
        query = f"SELECT {_MEMBERSHIP_COLUMNS} FROM atlas_memberships WHERE 1=1"
        params: dict[str, Any] = {}
        if organization_id is not None:
            query += " AND organization_id = :organization_id"
            params["organization_id"] = organization_id
        if identity_id is not None:
            query += " AND identity_id = :identity_id"
            params["identity_id"] = identity_id
        query += " ORDER BY created_at, id"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).fetchall()
        return [self._row_to_membership(row) for row in rows]

    def delete_membership(self, membership_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM atlas_memberships WHERE id = :id"), {"id": membership_id}
            )
            session.commit()

    def upsert_policy_set(self, policy_set: PolicySet) -> PolicySet:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_policy_sets (
                    id, organization_id, scope, scope_id, domain, settings, locked_keys,
                    enabled, metadata, created_at, updated_at
                )
                VALUES (
                    :id, :organization_id, :scope, :scope_id, :domain, :settings, :locked_keys,
                    :enabled, :metadata, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    scope = :scope, scope_id = :scope_id, domain = :domain,
                    settings = :settings, locked_keys = :locked_keys, enabled = :enabled,
                    metadata = :metadata, updated_at = :updated_at
                """),
                {
                    "id": policy_set.id,
                    "organization_id": policy_set.organization_id,
                    "scope": policy_set.scope.value,
                    "scope_id": policy_set.scope_id,
                    "domain": policy_set.domain.value,
                    "settings": json.dumps(policy_set.settings, default=_json_value),
                    "locked_keys": json.dumps(policy_set.locked_keys),
                    "enabled": policy_set.enabled,
                    "metadata": json.dumps(policy_set.metadata, default=_json_value),
                    "created_at": policy_set.created_at,
                    "updated_at": policy_set.updated_at,
                },
            )
            session.commit()
        return policy_set

    def get_policy_set(self, policy_set_id: str) -> PolicySet | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_POLICY_SET_COLUMNS} FROM atlas_policy_sets WHERE id = :id"),
                {"id": policy_set_id},
            ).fetchone()
        return self._row_to_policy_set(row) if row else None

    def list_policy_sets(
        self, organization_id: str | None = None, domain: PolicyDomain | None = None
    ) -> list[PolicySet]:
        query = f"SELECT {_POLICY_SET_COLUMNS} FROM atlas_policy_sets WHERE 1=1"
        params: dict[str, Any] = {}
        if organization_id is not None:
            query += " AND organization_id = :organization_id"
            params["organization_id"] = organization_id
        if domain is not None:
            query += " AND domain = :domain"
            params["domain"] = domain.value
        query += " ORDER BY created_at, id"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).fetchall()
        return [self._row_to_policy_set(row) for row in rows]

    def delete_policy_set(self, policy_set_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM atlas_policy_sets WHERE id = :id"), {"id": policy_set_id}
            )
            session.commit()

    def create_audit_record(self, record: AuditRecord) -> AuditRecord:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_audit_records (
                    id, organization_id, actor_id, actor_display, action, target_type,
                    target_id, summary, before, after, metadata, created_at
                )
                VALUES (
                    :id, :organization_id, :actor_id, :actor_display, :action, :target_type,
                    :target_id, :summary, :before, :after, :metadata, :created_at
                )
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": record.id,
                    "organization_id": record.organization_id,
                    "actor_id": record.actor_id,
                    "actor_display": record.actor_display,
                    "action": record.action.value,
                    "target_type": record.target_type,
                    "target_id": record.target_id,
                    "summary": record.summary,
                    "before": json.dumps(record.before, default=_json_value),
                    "after": json.dumps(record.after, default=_json_value),
                    "metadata": json.dumps(record.metadata, default=_json_value),
                    "created_at": record.created_at,
                },
            )
            session.commit()
        return record

    def get_audit_record(self, audit_id: str) -> AuditRecord | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_AUDIT_COLUMNS} FROM atlas_audit_records WHERE id = :id"),
                {"id": audit_id},
            ).fetchone()
        return self._row_to_audit_record(row) if row else None

    def list_audit_records(
        self,
        organization_id: str | None = None,
        action: AuditAction | None = None,
        actor_id: str | None = None,
        target_id: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[AuditRecord]:
        query = f"SELECT {_AUDIT_COLUMNS} FROM atlas_audit_records WHERE 1=1"
        params: dict[str, Any] = {}
        if organization_id is not None:
            query += " AND organization_id = :organization_id"
            params["organization_id"] = organization_id
        if action is not None:
            query += " AND action = :action"
            params["action"] = action.value
        if actor_id is not None:
            query += " AND actor_id = :actor_id"
            params["actor_id"] = actor_id
        if target_id is not None:
            query += " AND target_id = :target_id"
            params["target_id"] = target_id
        if since is not None:
            query += " AND created_at >= :since"
            params["since"] = since
        query += " ORDER BY created_at DESC, id DESC LIMIT :limit"
        params["limit"] = limit
        with SessionLocal() as session:
            rows = session.execute(text(query), params).fetchall()
        return [self._row_to_audit_record(row) for row in rows]

    def _row_to_organization(self, row: Any) -> Organization:
        return Organization(
            id=row[0],
            name=row[1],
            slug=row[2],
            description=row[3],
            tenant_id=row[4],
            workspace_ids=[str(w) for w in _as_list(row[5])],
            branding=Branding.model_validate(_as_dict(row[6])),
            license=License.model_validate(_as_dict(row[7])),
            allow_shared_pool=bool(row[8]),
            active=bool(row[9]),
            metadata=_as_dict(row[10]),
            created_at=row[11],
            updated_at=row[12],
        )

    def _row_to_team(self, row: Any) -> Team:
        return Team(
            id=row[0],
            organization_id=row[1],
            name=row[2],
            kind=TeamKind(row[3]),
            description=row[4],
            project_ids=[str(v) for v in _as_list(row[5])],
            studio_ids=[str(v) for v in _as_list(row[6])],
            worker_ids=[str(v) for v in _as_list(row[7])],
            automation_rule_ids=[str(v) for v in _as_list(row[8])],
            metadata=_as_dict(row[9]),
            created_at=row[10],
            updated_at=row[11],
        )

    def _row_to_role(self, row: Any) -> Role:
        return Role(
            id=row[0],
            name=row[1],
            description=row[2],
            permissions=[Permission(p) for p in _as_list(row[3])],
            organization_id=row[4],
            builtin=bool(row[5]),
            metadata=_as_dict(row[6]),
            created_at=row[7],
            updated_at=row[8],
        )

    def _row_to_identity(self, row: Any) -> Identity:
        return Identity(
            id=row[0],
            subject=row[1],
            display_name=row[2],
            email=row[3],
            provider=IdentityProviderKind(row[4]),
            provider_subject=row[5],
            active=bool(row[6]),
            metadata=_as_dict(row[7]),
            created_at=row[8],
            last_login_at=row[9],
        )

    def _row_to_membership(self, row: Any) -> Membership:
        return Membership(
            id=row[0],
            identity_id=row[1],
            organization_id=row[2],
            scope=MembershipScope(row[3]),
            scope_id=row[4],
            role_ids=[str(v) for v in _as_list(row[5])],
            team_ids=[str(v) for v in _as_list(row[6])],
            active=bool(row[7]),
            expires_at=row[8],
            metadata=_as_dict(row[9]),
            created_at=row[10],
            updated_at=row[11],
        )

    def _row_to_policy_set(self, row: Any) -> PolicySet:
        return PolicySet(
            id=row[0],
            organization_id=row[1],
            scope=PolicyScopeKind(row[2]),
            scope_id=row[3],
            domain=PolicyDomain(row[4]),
            settings=_as_dict(row[5]),
            locked_keys=[str(v) for v in _as_list(row[6])],
            enabled=bool(row[7]),
            metadata=_as_dict(row[8]),
            created_at=row[9],
            updated_at=row[10],
        )

    def _row_to_audit_record(self, row: Any) -> AuditRecord:
        return AuditRecord(
            id=row[0],
            organization_id=row[1],
            actor_id=row[2],
            actor_display=row[3],
            action=AuditAction(row[4]),
            target_type=row[5],
            target_id=row[6],
            summary=row[7],
            before=_as_dict(row[8]),
            after=_as_dict(row[9]),
            metadata=_as_dict(row[10]),
            created_at=row[11],
        )

    # ------------------------------------------------------------------
    # Cluster (Milestone 009): workers, heartbeats, reservations, leases.
    # ------------------------------------------------------------------

    def upsert_worker(self, worker: WorkerNode) -> WorkerNode:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_workers (
                    id, hostname, display_name, platform, resources, capabilities,
                    current_load, max_concurrency, status, version, tags, metrics,
                    metadata, last_heartbeat_at, registered_at, updated_at,
                    accepts_execution_dispatch
                )
                VALUES (
                    :id, :hostname, :display_name, :platform, :resources, :capabilities,
                    :current_load, :max_concurrency, :status, :version, :tags, :metrics,
                    :metadata, :last_heartbeat_at, :registered_at, :updated_at,
                    :accepts_execution_dispatch
                )
                ON CONFLICT (id) DO UPDATE SET
                    hostname = :hostname,
                    display_name = :display_name,
                    platform = :platform,
                    resources = :resources,
                    capabilities = :capabilities,
                    current_load = :current_load,
                    max_concurrency = :max_concurrency,
                    status = :status,
                    version = :version,
                    tags = :tags,
                    metrics = :metrics,
                    metadata = :metadata,
                    last_heartbeat_at = :last_heartbeat_at,
                    updated_at = :updated_at,
                    accepts_execution_dispatch = :accepts_execution_dispatch
                """),
                {
                    "id": worker.id,
                    "hostname": worker.hostname,
                    "display_name": worker.display_name,
                    "platform": worker.platform,
                    "resources": json.dumps(worker.resources.model_dump(mode="json")),
                    "capabilities": json.dumps(worker.capabilities),
                    "current_load": worker.current_load,
                    "max_concurrency": worker.max_concurrency,
                    "status": worker.status.value,
                    "version": worker.version,
                    "tags": json.dumps(worker.tags),
                    "metrics": json.dumps(worker.metrics.model_dump(mode="json")),
                    "metadata": json.dumps(worker.metadata, default=_json_value),
                    "last_heartbeat_at": worker.last_heartbeat_at,
                    "registered_at": worker.registered_at,
                    "updated_at": worker.updated_at,
                    "accepts_execution_dispatch": worker.accepts_execution_dispatch,
                },
            )
            session.commit()
        return worker

    def get_worker(self, worker_id: str) -> WorkerNode | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_WORKER_COLUMNS} FROM atlas_workers WHERE id = :id"),
                {"id": worker_id},
            ).fetchone()
        return self._row_to_worker(row) if row else None

    def get_worker_by_hostname(self, hostname: str) -> WorkerNode | None:
        with SessionLocal() as session:
            row = session.execute(
                text(
                    f"SELECT {_WORKER_COLUMNS} FROM atlas_workers WHERE hostname = :hostname "
                    "ORDER BY registered_at LIMIT 1"
                ),
                {"hostname": hostname},
            ).fetchone()
        return self._row_to_worker(row) if row else None

    def list_workers(self) -> list[WorkerNode]:
        with SessionLocal() as session:
            rows = session.execute(
                text(f"SELECT {_WORKER_COLUMNS} FROM atlas_workers ORDER BY display_name, id")
            ).fetchall()
        return [self._row_to_worker(row) for row in rows]

    def delete_worker(self, worker_id: str) -> None:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM atlas_workers WHERE id = :id"), {"id": worker_id})
            session.commit()

    def create_worker_heartbeat(self, heartbeat: WorkerHeartbeat) -> WorkerHeartbeat:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_worker_heartbeats (id, worker_id, status, current_load, metrics, created_at)
                VALUES (:id, :worker_id, :status, :current_load, :metrics, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": heartbeat.id,
                    "worker_id": heartbeat.worker_id,
                    "status": heartbeat.status.value,
                    "current_load": heartbeat.current_load,
                    "metrics": json.dumps(heartbeat.metrics.model_dump(mode="json")),
                    "created_at": heartbeat.created_at,
                },
            )
            session.commit()
        return heartbeat

    def list_worker_heartbeats(
        self, worker_id: str | None = None, limit: int = 50
    ) -> list[WorkerHeartbeat]:
        query = (
            "SELECT id, worker_id, status, current_load, metrics, created_at "
            "FROM atlas_worker_heartbeats WHERE 1=1"
        )
        params: dict[str, Any] = {}
        if worker_id is not None:
            query += " AND worker_id = :worker_id"
            params["worker_id"] = worker_id
        query += " ORDER BY created_at DESC, id DESC LIMIT :limit"
        params["limit"] = limit
        with SessionLocal() as session:
            rows = session.execute(text(query), params).fetchall()
        return [
            WorkerHeartbeat(
                id=row[0],
                worker_id=row[1],
                status=WorkerState(row[2]),
                current_load=row[3],
                metrics=WorkerMetrics.model_validate(_as_dict(row[4])),
                created_at=row[5],
            )
            for row in rows
        ]

    def create_reservation(self, reservation: ExecutionReservation) -> ExecutionReservation:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_reservations (
                    id, worker_id, schedule_id, entry_id, execution_id, capability,
                    priority, state, reason, metadata, created_at, released_at
                )
                VALUES (
                    :id, :worker_id, :schedule_id, :entry_id, :execution_id, :capability,
                    :priority, :state, :reason, :metadata, :created_at, :released_at
                )
                ON CONFLICT (id) DO NOTHING
                """),
                self._reservation_params(reservation),
            )
            session.commit()
        return reservation

    def update_reservation(self, reservation: ExecutionReservation) -> ExecutionReservation:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_reservations
                SET state = :state, reason = :reason, execution_id = :execution_id,
                    released_at = :released_at, metadata = :metadata
                WHERE id = :id
                """),
                self._reservation_params(reservation),
            )
            session.commit()
        return reservation

    def get_reservation(self, reservation_id: str) -> ExecutionReservation | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_RESERVATION_COLUMNS} FROM atlas_reservations WHERE id = :id"),
                {"id": reservation_id},
            ).fetchone()
        return self._row_to_reservation(row) if row else None

    def list_reservations(
        self, worker_id: str | None = None, execution_id: str | None = None
    ) -> list[ExecutionReservation]:
        query = f"SELECT {_RESERVATION_COLUMNS} FROM atlas_reservations WHERE 1=1"
        params: dict[str, Any] = {}
        if worker_id is not None:
            query += " AND worker_id = :worker_id"
            params["worker_id"] = worker_id
        if execution_id is not None:
            query += " AND execution_id = :execution_id"
            params["execution_id"] = execution_id
        query += " ORDER BY created_at DESC, id DESC"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).fetchall()
        return [self._row_to_reservation(row) for row in rows]

    def create_lease(self, lease: ExecutionLease) -> ExecutionLease:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_leases (
                    id, reservation_id, worker_id, execution_id, state, lease_seconds,
                    created_at, renewed_at, expires_at, released_at
                )
                VALUES (
                    :id, :reservation_id, :worker_id, :execution_id, :state, :lease_seconds,
                    :created_at, :renewed_at, :expires_at, :released_at
                )
                ON CONFLICT (id) DO NOTHING
                """),
                self._lease_params(lease),
            )
            session.commit()
        return lease

    def update_lease(self, lease: ExecutionLease) -> ExecutionLease:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_leases
                SET state = :state, lease_seconds = :lease_seconds, renewed_at = :renewed_at,
                    expires_at = :expires_at, released_at = :released_at
                WHERE id = :id
                """),
                self._lease_params(lease),
            )
            session.commit()
        return lease

    def get_lease(self, lease_id: str) -> ExecutionLease | None:
        with SessionLocal() as session:
            row = session.execute(
                text(f"SELECT {_LEASE_COLUMNS} FROM atlas_leases WHERE id = :id"),
                {"id": lease_id},
            ).fetchone()
        return self._row_to_lease(row) if row else None

    def list_leases(
        self, worker_id: str | None = None, execution_id: str | None = None
    ) -> list[ExecutionLease]:
        query = f"SELECT {_LEASE_COLUMNS} FROM atlas_leases WHERE 1=1"
        params: dict[str, Any] = {}
        if worker_id is not None:
            query += " AND worker_id = :worker_id"
            params["worker_id"] = worker_id
        if execution_id is not None:
            query += " AND execution_id = :execution_id"
            params["execution_id"] = execution_id
        query += " ORDER BY created_at DESC, id DESC"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).fetchall()
        return [self._row_to_lease(row) for row in rows]

    def list_executions_by_worker(self, worker_id: str) -> list[RuntimeExecutionRecord]:
        return [e for e in self.list_runtime_executions() if e.worker_id == worker_id]

    def _reservation_params(self, reservation: ExecutionReservation) -> dict[str, Any]:
        return {
            "id": reservation.id,
            "worker_id": reservation.worker_id,
            "schedule_id": reservation.schedule_id,
            "entry_id": reservation.entry_id,
            "execution_id": reservation.execution_id,
            "capability": reservation.capability,
            "priority": reservation.priority,
            "state": reservation.state.value,
            "reason": reservation.reason,
            "metadata": json.dumps(reservation.metadata, default=_json_value),
            "created_at": reservation.created_at,
            "released_at": reservation.released_at,
        }

    def _lease_params(self, lease: ExecutionLease) -> dict[str, Any]:
        return {
            "id": lease.id,
            "reservation_id": lease.reservation_id,
            "worker_id": lease.worker_id,
            "execution_id": lease.execution_id,
            "state": lease.state.value,
            "lease_seconds": lease.lease_seconds,
            "created_at": lease.created_at,
            "renewed_at": lease.renewed_at,
            "expires_at": lease.expires_at,
            "released_at": lease.released_at,
        }

    def _row_to_worker(self, row: Any) -> WorkerNode:
        return WorkerNode(
            id=row[0],
            hostname=row[1],
            display_name=row[2],
            platform=row[3],
            resources=WorkerResources.model_validate(_as_dict(row[4])),
            capabilities=[str(c) for c in _as_list(row[5])],
            current_load=row[6],
            max_concurrency=row[7],
            status=WorkerState(row[8]),
            version=row[9],
            tags=[str(t) for t in _as_list(row[10])],
            metrics=WorkerMetrics.model_validate(_as_dict(row[11])),
            metadata=_as_dict(row[12]),
            last_heartbeat_at=row[13],
            registered_at=row[14],
            updated_at=row[15],
            accepts_execution_dispatch=row[16],
        )

    def _row_to_reservation(self, row: Any) -> ExecutionReservation:
        return ExecutionReservation(
            id=row[0],
            worker_id=row[1],
            schedule_id=row[2],
            entry_id=row[3],
            execution_id=row[4],
            capability=row[5],
            priority=row[6],
            state=ReservationState(row[7]),
            reason=row[8],
            metadata=_as_dict(row[9]),
            created_at=row[10],
            released_at=row[11],
        )

    def _row_to_lease(self, row: Any) -> ExecutionLease:
        return ExecutionLease(
            id=row[0],
            reservation_id=row[1],
            worker_id=row[2],
            execution_id=row[3],
            state=LeaseState(row[4]),
            lease_seconds=row[5],
            created_at=row[6],
            renewed_at=row[7],
            expires_at=row[8],
            released_at=row[9],
        )

    # ------------------------------------------------------------------
    # Approvals (Milestone 008). History is append-only: there is deliberately
    # no update or delete method for atlas_approval_history.
    # ------------------------------------------------------------------

    def create_approval_request(self, request: ApprovalRequest) -> ApprovalRequest:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_approval_requests (
                    id, title, state, action, scopes, estimated_cost, reason, policy_id,
                    policy_name, required_approvers, approvals_required, decisions, viewed_by,
                    priority, project_id, workspace_id, agent_id, execution_id, schedule_id,
                    entry_id, run_id, job_id, asset_id, payload, metadata, requested_by,
                    created_at, updated_at, expires_at, decided_at
                )
                VALUES (
                    :id, :title, :state, :action, :scopes, :estimated_cost, :reason, :policy_id,
                    :policy_name, :required_approvers, :approvals_required, :decisions, :viewed_by,
                    :priority, :project_id, :workspace_id, :agent_id, :execution_id, :schedule_id,
                    :entry_id, :run_id, :job_id, :asset_id, :payload, :metadata, :requested_by,
                    :created_at, :updated_at, :expires_at, :decided_at
                )
                ON CONFLICT (id) DO NOTHING
                """),
                self._approval_request_params(request),
            )
            session.commit()
        return request

    def update_approval_request(self, request: ApprovalRequest) -> ApprovalRequest:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_approval_requests
                SET state = :state,
                    decisions = :decisions,
                    viewed_by = :viewed_by,
                    required_approvers = :required_approvers,
                    approvals_required = :approvals_required,
                    updated_at = :updated_at,
                    expires_at = :expires_at,
                    decided_at = :decided_at,
                    metadata = :metadata
                WHERE id = :id
                """),
                self._approval_request_params(request),
            )
            session.commit()
        return request

    def get_approval_request(self, approval_id: str) -> ApprovalRequest | None:
        with SessionLocal() as session:
            row = session.execute(
                text(
                    f"SELECT {_APPROVAL_REQUEST_COLUMNS} FROM atlas_approval_requests WHERE id = :id"
                ),
                {"id": approval_id},
            ).fetchone()
        return self._row_to_approval_request(row) if row else None

    def list_approval_requests(
        self,
        state: ApprovalState | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[ApprovalRequest]:
        query = f"SELECT {_APPROVAL_REQUEST_COLUMNS} FROM atlas_approval_requests WHERE 1=1"
        params: dict[str, Any] = {}
        if state is not None:
            query += " AND state = :state"
            params["state"] = state.value
        if project_id is not None:
            query += " AND project_id = :project_id"
            params["project_id"] = project_id
        if workspace_id is not None:
            query += " AND workspace_id = :workspace_id"
            params["workspace_id"] = workspace_id
        query += " ORDER BY priority DESC, created_at ASC, id ASC"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).fetchall()
        return [self._row_to_approval_request(row) for row in rows]

    def create_approval_history_event(self, event: ApprovalHistoryEvent) -> ApprovalHistoryEvent:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_approval_history
                (id, approval_id, event_type, actor, comment, from_state, to_state, metadata, created_at)
                VALUES (:id, :approval_id, :event_type, :actor, :comment, :from_state, :to_state, :metadata, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": event.id,
                    "approval_id": event.approval_id,
                    "event_type": event.event_type,
                    "actor": event.actor,
                    "comment": event.comment,
                    "from_state": event.from_state.value if event.from_state else None,
                    "to_state": event.to_state.value if event.to_state else None,
                    "metadata": json.dumps(event.metadata, default=_json_value),
                    "created_at": event.created_at,
                },
            )
            session.commit()
        return event

    def list_approval_history(self, approval_id: str | None = None) -> list[ApprovalHistoryEvent]:
        query = (
            "SELECT id, approval_id, event_type, actor, comment, from_state, to_state, metadata, created_at "
            "FROM atlas_approval_history WHERE 1=1"
        )
        params: dict[str, Any] = {}
        if approval_id is not None:
            query += " AND approval_id = :approval_id"
            params["approval_id"] = approval_id
        query += " ORDER BY created_at DESC, id DESC"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).fetchall()
        return [
            ApprovalHistoryEvent(
                id=row[0],
                approval_id=row[1],
                event_type=row[2],
                actor=row[3],
                comment=row[4],
                from_state=ApprovalState(row[5]) if row[5] else None,
                to_state=ApprovalState(row[6]) if row[6] else None,
                metadata=_as_dict(row[7]),
                created_at=row[8],
            )
            for row in rows
        ]

    def upsert_approval_policy(self, policy: ApprovalPolicy) -> ApprovalPolicy:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_approval_policies (
                    id, name, description, mode, scopes, cost_threshold, conditions,
                    required_approvers, approvals_required, expires_after_seconds,
                    project_id, workspace_id, priority, enabled, metadata, created_at, updated_at
                )
                VALUES (
                    :id, :name, :description, :mode, :scopes, :cost_threshold, :conditions,
                    :required_approvers, :approvals_required, :expires_after_seconds,
                    :project_id, :workspace_id, :priority, :enabled, :metadata, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = :name,
                    description = :description,
                    mode = :mode,
                    scopes = :scopes,
                    cost_threshold = :cost_threshold,
                    conditions = :conditions,
                    required_approvers = :required_approvers,
                    approvals_required = :approvals_required,
                    expires_after_seconds = :expires_after_seconds,
                    project_id = :project_id,
                    workspace_id = :workspace_id,
                    priority = :priority,
                    enabled = :enabled,
                    metadata = :metadata,
                    updated_at = :updated_at
                """),
                {
                    "id": policy.id,
                    "name": policy.name,
                    "description": policy.description,
                    "mode": policy.mode.value,
                    "scopes": json.dumps([s.value for s in policy.scopes]),
                    "cost_threshold": policy.cost_threshold,
                    "conditions": json.dumps(
                        [c.model_dump(mode="json") for c in policy.conditions]
                    ),
                    "required_approvers": json.dumps(policy.required_approvers),
                    "approvals_required": policy.approvals_required,
                    "expires_after_seconds": policy.expires_after_seconds,
                    "project_id": policy.project_id,
                    "workspace_id": policy.workspace_id,
                    "priority": policy.priority,
                    "enabled": policy.enabled,
                    "metadata": json.dumps(policy.metadata, default=_json_value),
                    "created_at": policy.created_at,
                    "updated_at": policy.updated_at,
                },
            )
            session.commit()
        return policy

    def list_approval_policies(self) -> list[ApprovalPolicy]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT id, name, description, mode, scopes, cost_threshold, conditions,
                       required_approvers, approvals_required, expires_after_seconds,
                       project_id, workspace_id, priority, enabled, metadata, created_at, updated_at
                FROM atlas_approval_policies
                ORDER BY priority DESC, created_at ASC, id ASC
                """)
            ).fetchall()
        return [
            ApprovalPolicy(
                id=row[0],
                name=row[1],
                description=row[2],
                mode=ApprovalPolicyMode(row[3]),
                scopes=[ApprovalScope(s) for s in _as_list(row[4])],
                cost_threshold=row[5],
                conditions=[ApprovalCondition.model_validate(c) for c in _as_list(row[6])],
                required_approvers=[str(a) for a in _as_list(row[7])],
                approvals_required=row[8],
                expires_after_seconds=row[9],
                project_id=row[10],
                workspace_id=row[11],
                priority=row[12],
                enabled=bool(row[13]),
                metadata=_as_dict(row[14]),
                created_at=row[15],
                updated_at=row[16],
            )
            for row in rows
        ]

    def delete_approval_policy(self, policy_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM atlas_approval_policies WHERE id = :id"), {"id": policy_id}
            )
            session.commit()

    def _approval_request_params(self, request: ApprovalRequest) -> dict[str, Any]:
        return {
            "id": request.id,
            "title": request.title,
            "state": request.state.value,
            "action": request.action,
            "scopes": json.dumps([s.value for s in request.scopes]),
            "estimated_cost": request.estimated_cost,
            "reason": request.reason,
            "policy_id": request.policy_id,
            "policy_name": request.policy_name,
            "required_approvers": json.dumps(request.required_approvers),
            "approvals_required": request.approvals_required,
            "decisions": json.dumps([d.model_dump(mode="json") for d in request.decisions]),
            "viewed_by": json.dumps(request.viewed_by),
            "priority": request.priority,
            "project_id": request.project_id,
            "workspace_id": request.workspace_id,
            "agent_id": request.agent_id,
            "execution_id": request.execution_id,
            "schedule_id": request.schedule_id,
            "entry_id": request.entry_id,
            "run_id": request.run_id,
            "job_id": request.job_id,
            "asset_id": request.asset_id,
            "payload": json.dumps(request.payload, default=_json_value),
            "metadata": json.dumps(request.metadata, default=_json_value),
            "requested_by": request.requested_by,
            "created_at": request.created_at,
            "updated_at": request.updated_at,
            "expires_at": request.expires_at,
            "decided_at": request.decided_at,
        }

    def _row_to_approval_request(self, row: Any) -> ApprovalRequest:
        return ApprovalRequest(
            id=row[0],
            title=row[1],
            state=ApprovalState(row[2]),
            action=row[3],
            scopes=[ApprovalScope(s) for s in _as_list(row[4])],
            estimated_cost=row[5],
            reason=row[6],
            policy_id=row[7],
            policy_name=row[8],
            required_approvers=[str(a) for a in _as_list(row[9])],
            approvals_required=row[10],
            decisions=[ApprovalDecision.model_validate(d) for d in _as_list(row[11])],
            viewed_by=[str(v) for v in _as_list(row[12])],
            priority=row[13],
            project_id=row[14],
            workspace_id=row[15],
            agent_id=row[16],
            execution_id=row[17],
            schedule_id=row[18],
            entry_id=row[19],
            run_id=row[20],
            job_id=row[21],
            asset_id=row[22],
            payload=_as_dict(row[23]),
            metadata=_as_dict(row[24]),
            requested_by=row[25],
            created_at=row[26],
            updated_at=row[27],
            expires_at=row[28],
            decided_at=row[29],
        )


_ORGANIZATION_COLUMNS = (
    "id, name, slug, description, tenant_id, workspace_ids, branding, license, "
    "allow_shared_pool, active, metadata, created_at, updated_at"
)

_TEAM_COLUMNS = (
    "id, organization_id, name, kind, description, project_ids, studio_ids, worker_ids, "
    "automation_rule_ids, metadata, created_at, updated_at"
)

_ROLE_COLUMNS = (
    "id, name, description, permissions, organization_id, builtin, metadata, created_at, updated_at"
)

_IDENTITY_COLUMNS = (
    "id, subject, display_name, email, provider, provider_subject, active, metadata, "
    "created_at, last_login_at"
)

_MEMBERSHIP_COLUMNS = (
    "id, identity_id, organization_id, scope, scope_id, role_ids, team_ids, active, "
    "expires_at, metadata, created_at, updated_at"
)

_POLICY_SET_COLUMNS = (
    "id, organization_id, scope, scope_id, domain, settings, locked_keys, enabled, "
    "metadata, created_at, updated_at"
)

_AUDIT_COLUMNS = (
    "id, organization_id, actor_id, actor_display, action, target_type, target_id, "
    "summary, before, after, metadata, created_at"
)

#: Appended to, never reordered: `_row_to_worker` reads these positionally, so
#: inserting a column in the middle silently shifts every field after it.
_WORKER_COLUMNS = (
    "id, hostname, display_name, platform, resources, capabilities, current_load, "
    "max_concurrency, status, version, tags, metrics, metadata, last_heartbeat_at, "
    "registered_at, updated_at, accepts_execution_dispatch"
)

_RESERVATION_COLUMNS = (
    "id, worker_id, schedule_id, entry_id, execution_id, capability, priority, state, "
    "reason, metadata, created_at, released_at"
)

_LEASE_COLUMNS = (
    "id, reservation_id, worker_id, execution_id, state, lease_seconds, created_at, "
    "renewed_at, expires_at, released_at"
)


_APPROVAL_REQUEST_COLUMNS = (
    "id, title, state, action, scopes, estimated_cost, reason, policy_id, policy_name, "
    "required_approvers, approvals_required, decisions, viewed_by, priority, project_id, "
    "workspace_id, agent_id, execution_id, schedule_id, entry_id, run_id, job_id, asset_id, "
    "payload, metadata, requested_by, created_at, updated_at, expires_at, decided_at"
)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value:
        return json.loads(value)
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value:
        return json.loads(value)
    return {}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")
