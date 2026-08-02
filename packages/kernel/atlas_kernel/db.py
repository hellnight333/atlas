from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "ATLAS_DATABASE_URL", "postgresql+psycopg://atlas:atlas@localhost:5432/atlas"
)

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_workspaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_projects (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_chat_conversations (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            pinned BOOLEAN NOT NULL DEFAULT FALSE,
            prompt_version INTEGER NOT NULL DEFAULT 0,
            response_version INTEGER NOT NULL DEFAULT 0,
            provider_name TEXT,
            execution_time_ms INTEGER,
            tokens INTEGER,
            workflow_id TEXT,
            parent_conversation_id TEXT,
            prompt_asset_id TEXT,
            response_asset_id TEXT,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_chat_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            asset_id TEXT,
            prompt_asset_id TEXT,
            response_asset_id TEXT,
            provider_name TEXT,
            execution_time_ms INTEGER,
            tokens INTEGER,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_research_sessions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            question TEXT NOT NULL,
            status TEXT NOT NULL,
            conversation_id TEXT,
            collection_asset_id TEXT,
            report_asset_id TEXT,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_research_graphs (
            project_id TEXT PRIMARY KEY,
            nodes JSONB NOT NULL DEFAULT '[]',
            edges JSONB NOT NULL DEFAULT '[]',
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_review_sessions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            asset_id TEXT,
            published_asset_id TEXT,
            workflow_id TEXT,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_review_items (
            id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            comment TEXT,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_review_comments (
            id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_review_history (
            id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'system',
            comment TEXT,
            from_status TEXT,
            to_status TEXT,
            asset_id TEXT,
            published_asset_id TEXT,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_workflows (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            studio TEXT NOT NULL,
            default_action TEXT,
            capability_req JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_runs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            studio TEXT NOT NULL,
            workspace_id TEXT,
            project_id TEXT,
            workflow_id TEXT,
            produced_asset_ids JSONB NOT NULL DEFAULT '[]',
            status TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_steps (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            payload JSONB NOT NULL,
            depends_on JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_jobs (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            action TEXT NOT NULL,
            payload JSONB NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            priority INTEGER NOT NULL DEFAULT 0,
            capability_req JSONB NOT NULL,
            execution_decision_id TEXT,
            provider_name TEXT,
            output JSONB NOT NULL DEFAULT '{}',
            produced_asset_ids JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_execution_decisions (
            decision_id TEXT PRIMARY KEY,
            capability_id TEXT NOT NULL,
            recipe_id TEXT,
            executor_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            model_id TEXT,
            reason JSONB NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            role TEXT NOT NULL,
            workspace_id TEXT,
            project_id TEXT,
            capabilities JSONB NOT NULL DEFAULT '[]',
            status TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            permission_set JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_agent_memory_references (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_schedules (
            schedule_id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            priority TEXT NOT NULL,
            estimated_finish_time TIMESTAMP WITH TIME ZONE,
            queue_entries JSONB NOT NULL DEFAULT '[]',
            blocked_entries JSONB NOT NULL DEFAULT '[]',
            parallel_groups JSONB NOT NULL DEFAULT '[]',
            resume_tokens JSONB NOT NULL DEFAULT '[]',
            queue_metadata JSONB NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_runtime_executions (
            execution_id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            action TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            retry_policy JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            started_at TIMESTAMP WITH TIME ZONE,
            heartbeat_at TIMESTAMP WITH TIME ZONE,
            deadline_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            timeout_reason TEXT,
            error TEXT,
            provider_name TEXT,
            run_id TEXT,
            job_id TEXT,
            asset_id TEXT,
            output JSONB NOT NULL DEFAULT '{}',
            cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE,
            timeline JSONB NOT NULL DEFAULT '[]'
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_agent_teams (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            project_id TEXT,
            workspace_id TEXT,
            status TEXT NOT NULL,
            conversation_ids JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_agent_assignments (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            role TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            capabilities JSONB NOT NULL DEFAULT '[]',
            allowed_actions JSONB NOT NULL DEFAULT '[]',
            permissions JSONB NOT NULL DEFAULT '[]',
            resource_limits JSONB NOT NULL DEFAULT '{}',
            action TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            dependencies JSONB NOT NULL DEFAULT '[]',
            mailbox_id TEXT NOT NULL,
            schedule_id TEXT,
            runtime_execution_id TEXT,
            result_asset_id TEXT,
            error TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_agent_mailboxes (
            agent_id TEXT PRIMARY KEY,
            pending_messages JSONB NOT NULL DEFAULT '[]',
            history JSONB NOT NULL DEFAULT '[]'
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_agent_conversations (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            participant_ids JSONB NOT NULL DEFAULT '[]',
            message_ids JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_agent_messages (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            correlation_id TEXT,
            reply_to TEXT
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_graph_nodes (
            id TEXT PRIMARY KEY,
            node_type TEXT NOT NULL,
            label TEXT NOT NULL,
            project_id TEXT,
            workspace_id TEXT,
            source_id TEXT,
            metadata JSONB NOT NULL DEFAULT '{}',
            archived BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_graph_edges (
            id TEXT PRIMARY KEY,
            relationship TEXT NOT NULL,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_graph_snapshots (
            id TEXT PRIMARY KEY,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            node_ids JSONB NOT NULL DEFAULT '[]',
            edge_ids JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_assets (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            workflow_id TEXT,
            run_id TEXT,
            job_id TEXT,
            parent_asset_id TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            type TEXT NOT NULL,
            uri TEXT NOT NULL,
            mime_type TEXT,
            file_size BIGINT,
            content_hash TEXT,
            metadata JSONB NOT NULL,
            tags JSONB NOT NULL DEFAULT '[]',
            source_asset_ids JSONB NOT NULL DEFAULT '[]',
            thumbnail_uri TEXT,
            preview_uri TEXT,
            search_index JSONB,
            vector_index JSONB,
            embeddings JSONB,
            ocr_text TEXT,
            transcript TEXT,
            ai_summary TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_automation_rules (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            workspace_id TEXT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            trigger JSONB NOT NULL,
            conditions JSONB NOT NULL DEFAULT '[]',
            actions JSONB NOT NULL DEFAULT '[]',
            schedule JSONB,
            priority INTEGER NOT NULL DEFAULT 0,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            dry_run BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            disabled_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_automation_runs (
            id TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL,
            triggered_by TEXT NOT NULL,
            status TEXT NOT NULL,
            start_time TIMESTAMP WITH TIME ZONE NOT NULL,
            end_time TIMESTAMP WITH TIME ZONE,
            duration_ms INTEGER,
            trigger_data JSONB NOT NULL DEFAULT '{}',
            outputs JSONB NOT NULL DEFAULT '{}',
            error TEXT,
            retries INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_automation_logs (
            id TEXT PRIMARY KEY,
            run_id TEXT,
            rule_id TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'system',
            context JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_automation_schedules (
            id TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL,
            schedule_id TEXT,
            next_run TIMESTAMP WITH TIME ZONE,
            last_run TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_approval_requests (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            state TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT '',
            scopes JSONB NOT NULL DEFAULT '[]',
            estimated_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '',
            policy_id TEXT,
            policy_name TEXT,
            required_approvers JSONB NOT NULL DEFAULT '[]',
            approvals_required INTEGER NOT NULL DEFAULT 1,
            decisions JSONB NOT NULL DEFAULT '[]',
            viewed_by JSONB NOT NULL DEFAULT '[]',
            priority INTEGER NOT NULL DEFAULT 0,
            project_id TEXT,
            workspace_id TEXT,
            agent_id TEXT,
            execution_id TEXT,
            schedule_id TEXT,
            entry_id TEXT,
            run_id TEXT,
            job_id TEXT,
            asset_id TEXT,
            payload JSONB NOT NULL DEFAULT '{}',
            metadata JSONB NOT NULL DEFAULT '{}',
            requested_by TEXT NOT NULL DEFAULT 'system',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE,
            decided_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_approval_history (
            id TEXT PRIMARY KEY,
            approval_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'system',
            comment TEXT,
            from_state TEXT,
            to_state TEXT,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_approval_policies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL,
            scopes JSONB NOT NULL DEFAULT '[]',
            cost_threshold DOUBLE PRECISION,
            conditions JSONB NOT NULL DEFAULT '[]',
            required_approvers JSONB NOT NULL DEFAULT '[]',
            approvals_required INTEGER NOT NULL DEFAULT 1,
            expires_after_seconds INTEGER,
            project_id TEXT,
            workspace_id TEXT,
            priority INTEGER NOT NULL DEFAULT 0,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_workers (
            id TEXT PRIMARY KEY,
            hostname TEXT NOT NULL,
            display_name TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'unknown',
            resources JSONB NOT NULL DEFAULT '{}',
            capabilities JSONB NOT NULL DEFAULT '[]',
            current_load INTEGER NOT NULL DEFAULT 0,
            max_concurrency INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT '0.0.0',
            tags JSONB NOT NULL DEFAULT '[]',
            metrics JSONB NOT NULL DEFAULT '{}',
            metadata JSONB NOT NULL DEFAULT '{}',
            last_heartbeat_at TIMESTAMP WITH TIME ZONE,
            registered_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_worker_heartbeats (
            id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            status TEXT NOT NULL,
            current_load INTEGER NOT NULL DEFAULT 0,
            metrics JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_reservations (
            id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            schedule_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            execution_id TEXT,
            capability TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            released_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS atlas_leases (
            id TEXT PRIMARY KEY,
            reservation_id TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            execution_id TEXT NOT NULL,
            state TEXT NOT NULL,
            lease_seconds INTEGER NOT NULL DEFAULT 120,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            renewed_at TIMESTAMP WITH TIME ZONE,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            released_at TIMESTAMP WITH TIME ZONE
        )
        """))
        conn.execute(text("""
        ALTER TABLE atlas_runtime_executions
        ADD COLUMN IF NOT EXISTS approval_id TEXT,
        ADD COLUMN IF NOT EXISTS worker_id TEXT,
        ADD COLUMN IF NOT EXISTS lease_id TEXT,
        ADD COLUMN IF NOT EXISTS reservation_id TEXT,
        ADD COLUMN IF NOT EXISTS placement_reason TEXT
        """))
        conn.execute(text("""
        ALTER TABLE atlas_runs
        ADD COLUMN IF NOT EXISTS workspace_id TEXT,
        ADD COLUMN IF NOT EXISTS project_id TEXT,
        ADD COLUMN IF NOT EXISTS workflow_id TEXT,
        ADD COLUMN IF NOT EXISTS produced_asset_ids JSONB NOT NULL DEFAULT '[]'
        """))
        conn.execute(text("""
        ALTER TABLE atlas_jobs
        ADD COLUMN IF NOT EXISTS execution_decision_id TEXT,
        ADD COLUMN IF NOT EXISTS provider_name TEXT,
        ADD COLUMN IF NOT EXISTS output JSONB NOT NULL DEFAULT '{}',
        ADD COLUMN IF NOT EXISTS produced_asset_ids JSONB NOT NULL DEFAULT '[]'
        """))
        conn.execute(text("""
        ALTER TABLE atlas_assets
        ADD COLUMN IF NOT EXISTS project_id TEXT DEFAULT 'project-unassigned',
        ADD COLUMN IF NOT EXISTS workflow_id TEXT,
        ADD COLUMN IF NOT EXISTS parent_asset_id TEXT,
        ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
        ADD COLUMN IF NOT EXISTS mime_type TEXT,
        ADD COLUMN IF NOT EXISTS file_size BIGINT,
        ADD COLUMN IF NOT EXISTS content_hash TEXT,
        ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]',
        ADD COLUMN IF NOT EXISTS source_asset_ids JSONB NOT NULL DEFAULT '[]',
        ADD COLUMN IF NOT EXISTS thumbnail_uri TEXT,
        ADD COLUMN IF NOT EXISTS preview_uri TEXT,
        ADD COLUMN IF NOT EXISTS search_index JSONB,
        ADD COLUMN IF NOT EXISTS vector_index JSONB,
        ADD COLUMN IF NOT EXISTS embeddings JSONB,
        ADD COLUMN IF NOT EXISTS ocr_text TEXT,
        ADD COLUMN IF NOT EXISTS transcript TEXT,
        ADD COLUMN IF NOT EXISTS ai_summary TEXT,
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE,
        ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE
        """))
        conn.execute(text("""
        ALTER TABLE atlas_assets
        ALTER COLUMN run_id DROP NOT NULL,
        ALTER COLUMN job_id DROP NOT NULL
        """))
        conn.execute(text("""
        UPDATE atlas_assets
        SET project_id = 'project-unassigned'
        WHERE project_id IS NULL
        """))
        conn.execute(text("""
        UPDATE atlas_assets
        SET updated_at = created_at
        WHERE updated_at IS NULL
        """))
        conn.execute(text("""
        ALTER TABLE atlas_chat_conversations
        ALTER COLUMN project_id SET DEFAULT 'project-unassigned',
        ALTER COLUMN title SET DEFAULT 'Conversation',
        ALTER COLUMN pinned SET DEFAULT FALSE,
        ALTER COLUMN prompt_version SET DEFAULT 0,
        ALTER COLUMN response_version SET DEFAULT 0,
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """))
        conn.execute(text("""
        ALTER TABLE atlas_chat_messages
        ALTER COLUMN version SET DEFAULT 1,
        ALTER COLUMN role SET DEFAULT 'assistant',
        ALTER COLUMN content SET DEFAULT '',
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """))
        conn.execute(text("""
        ALTER TABLE atlas_research_sessions
        ALTER COLUMN status SET DEFAULT 'active',
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """))
        conn.execute(text("""
        ALTER TABLE atlas_review_sessions
        ALTER COLUMN status SET DEFAULT 'pending',
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """))
        conn.execute(text("""
        ALTER TABLE atlas_review_items
        ALTER COLUMN decision SET DEFAULT 'pending',
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """))
        conn.execute(text("""
        ALTER TABLE atlas_review_comments
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """))
        conn.execute(text("""
        ALTER TABLE atlas_review_history
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """))
