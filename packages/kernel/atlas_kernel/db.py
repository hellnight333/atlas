from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import declarative_base, sessionmaker

from .db_safety import DEFAULT_DATABASE_URL
from .db_safety import check as _refuse_production_in_tests

DATABASE_URL = os.getenv("ATLAS_DATABASE_URL", DEFAULT_DATABASE_URL)

# Every caller reaches the database through this engine, so the boundary is
# here rather than in a conftest a caller may never load. See db_safety.
_refuse_production_in_tests(DATABASE_URL)

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_workspaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_projects (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_research_graphs (
            project_id TEXT PRIMARY KEY,
            nodes JSONB NOT NULL DEFAULT '[]',
            edges JSONB NOT NULL DEFAULT '[]',
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_review_comments (
            id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE
        )
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_steps (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            payload JSONB NOT NULL,
            depends_on JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_agent_memory_references (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_agent_mailboxes (
            agent_id TEXT PRIMARY KEY,
            pending_messages JSONB NOT NULL DEFAULT '[]',
            history JSONB NOT NULL DEFAULT '[]'
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_agent_conversations (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            participant_ids JSONB NOT NULL DEFAULT '[]',
            message_ids JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_graph_edges (
            id TEXT PRIMARY KEY,
            relationship TEXT NOT NULL,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_graph_snapshots (
            id TEXT PRIMARY KEY,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            node_ids JSONB NOT NULL DEFAULT '[]',
            edge_ids JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_automation_schedules (
            id TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL,
            schedule_id TEXT,
            next_run TIMESTAMP WITH TIME ZONE,
            last_run TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_worker_heartbeats (
            id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            status TEXT NOT NULL,
            current_load INTEGER NOT NULL DEFAULT 0,
            metrics JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL,
            workspace_ids JSONB NOT NULL DEFAULT '[]',
            branding JSONB NOT NULL DEFAULT '{}',
            license JSONB NOT NULL DEFAULT '{}',
            allow_shared_pool BOOLEAN NOT NULL DEFAULT TRUE,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_teams (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            project_ids JSONB NOT NULL DEFAULT '[]',
            studio_ids JSONB NOT NULL DEFAULT '[]',
            worker_ids JSONB NOT NULL DEFAULT '[]',
            automation_rule_ids JSONB NOT NULL DEFAULT '[]',
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_roles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            permissions JSONB NOT NULL DEFAULT '[]',
            organization_id TEXT,
            builtin BOOLEAN NOT NULL DEFAULT FALSE,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_identities (
            id TEXT PRIMARY KEY,
            subject TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            email TEXT,
            provider TEXT NOT NULL,
            provider_subject TEXT,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            last_login_at TIMESTAMP WITH TIME ZONE
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_memberships (
            id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            scope_id TEXT,
            role_ids JSONB NOT NULL DEFAULT '[]',
            team_ids JSONB NOT NULL DEFAULT '[]',
            active BOOLEAN NOT NULL DEFAULT TRUE,
            expires_at TIMESTAMP WITH TIME ZONE,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_policy_sets (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            scope_id TEXT,
            domain TEXT NOT NULL,
            settings JSONB NOT NULL DEFAULT '{}',
            locked_keys JSONB NOT NULL DEFAULT '[]',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_audit_records (
            id TEXT PRIMARY KEY,
            organization_id TEXT,
            actor_id TEXT NOT NULL DEFAULT 'system',
            actor_display TEXT NOT NULL DEFAULT 'system',
            action TEXT NOT NULL,
            target_type TEXT NOT NULL DEFAULT '',
            target_id TEXT,
            summary TEXT NOT NULL DEFAULT '',
            before JSONB NOT NULL DEFAULT '{}',
            after JSONB NOT NULL DEFAULT '{}',
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )

        # Installation-level settings. First-run state lives here rather than in
        # the browser: localStorage forgets on a cache clear and would show setup
        # again in a second window. One row per key; the onboarding row is the
        # only one today.
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_app_settings (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )

        # -- Media Factory (M013) ------------------------------------------
        #
        # Two layers, and the boundary is deliberate. The content tables
        # (series, episodes, scripts, scenes) carry no media columns at all,
        # so a future blog or podcast renderer never inherits a field that only
        # video needed. See docs/VIDEO_FACTORY.md.
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_series (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            default_channel TEXT,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        # M013 pre-release rename: Campaign became Series, because Atlas runs
        # media properties for years and a campaign is by definition something
        # that ends. Neither shape was ever released, so this only has to fix
        # development databases created earlier the same day. `CREATE TABLE IF
        # NOT EXISTS` cannot reshape an existing table, hence the explicit
        # rename. Safe to delete once no such database remains.
        conn.execute(text("DROP TABLE IF EXISTS atlas_campaigns"))
        conn.execute(
            text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'atlas_episodes' AND column_name = 'campaign_id'
            ) THEN
                ALTER TABLE atlas_episodes RENAME COLUMN campaign_id TO series_id;
            END IF;
        END $$;
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_episodes (
            id TEXT PRIMARY KEY,
            series_id TEXT NOT NULL,
            brief TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_scripts (
            id TEXT PRIMARY KEY,
            episode_id TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            authored_by TEXT NOT NULL DEFAULT 'human',
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            UNIQUE (episode_id, version)
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_scenes (
            id TEXT PRIMARY KEY,
            script_id TEXT NOT NULL,
            index_in_script INTEGER NOT NULL,
            heading TEXT NOT NULL DEFAULT '',
            narration TEXT NOT NULL DEFAULT '',
            visual_direction TEXT NOT NULL DEFAULT '',
            target_seconds DOUBLE PRECISION NOT NULL DEFAULT 5.0,
            metadata JSONB NOT NULL DEFAULT '{}',
            UNIQUE (script_id, index_in_script)
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_renditions (
            id TEXT PRIMARY KEY,
            episode_id TEXT NOT NULL,
            script_id TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'video/1080p',
            status TEXT NOT NULL DEFAULT 'pending',
            asset_id TEXT,
            scene_fingerprint TEXT NOT NULL DEFAULT '',
            build_metadata JSONB NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_scene_renders (
            id TEXT PRIMARY KEY,
            rendition_id TEXT NOT NULL,
            scene_id TEXT NOT NULL,
            index_in_script INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            provider TEXT,
            recipe_id TEXT,
            media_asset_id TEXT,
            audio_asset_id TEXT,
            duration_seconds DOUBLE PRECISION,
            source_fingerprint TEXT NOT NULL DEFAULT '',
            job_id TEXT,
            -- The provider's own job reference. Persisted rather than held in
            -- memory so a poll can happen on a different worker than the
            -- submit: Atlas must never assume one GPU or one process.
            provider_handle TEXT,
            -- Everything needed to reproduce this exact render, years later.
            -- One column rather than a dozen because the fields a provider
            -- needs differ per provider, and the kernel must not grow a column
            -- every time a new one appears. Shape is enforced by
            -- media.provenance.RenderProvenance, not by the schema.
            provenance JSONB NOT NULL DEFAULT '{}',
            render_ms INTEGER,
            cost_usd DOUBLE PRECISION,
            error TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            UNIQUE (rendition_id, scene_id)
        )
        """)
        )
        # Provenance arrived after the first M013 tables, so databases created
        # before it need the columns added. Additive, hence ADD COLUMN IF NOT
        # EXISTS rather than a guarded block.
        #
        # It must sit *after* the CREATE above, and previously did not. On any
        # database that already had the table this was invisible; on a fresh one
        # it aborted the whole of init_db() -- a single transaction -- leaving
        # zero tables. Nobody noticed because nobody had built this schema from
        # nothing in a long time, which is exactly the class of bug that waits
        # for a new machine or a new contributor.
        conn.execute(
            text("""
        ALTER TABLE atlas_scene_renders
        ADD COLUMN IF NOT EXISTS provider_handle TEXT,
        ADD COLUMN IF NOT EXISTS provenance JSONB NOT NULL DEFAULT '{}',
        ADD COLUMN IF NOT EXISTS render_ms INTEGER,
        ADD COLUMN IF NOT EXISTS cost_usd DOUBLE PRECISION
        """)
        )
        # Generic, and deliberately so. The kernel records "this node was last
        # built with this effective fingerprint" and knows nothing about what a
        # node is. Video uses it today; a podcast, a blog post or a listing will
        # use the same table without a migration.
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_dependency_fingerprints (
            scope TEXT NOT NULL,
            node_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (scope, node_id)
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_publications (
            id TEXT PRIMARY KEY,
            rendition_id TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'youtube',
            approval_id TEXT,
            visibility TEXT NOT NULL DEFAULT 'private',
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]',
            thumbnail_asset_id TEXT,
            remote_id TEXT,
            remote_url TEXT,
            status TEXT NOT NULL DEFAULT 'pending_approval',
            error TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        # -- Opportunity Factory (M014) ------------------------------------
        #
        # Business is the permanent customer record: one row per company, for
        # the life of the relationship. Websites, listings, media, projects,
        # deployments and support history will each reference business_id and
        # own their own state — no factory keeps its own copy of the customer.
        #
        # Same layering discipline as the Media Factory: businesses and findings
        # are facts about the world and carry no channel, proposal or send state.
        # See docs/OPPORTUNITY_FACTORY.md.
        #
        # Pre-release rename: atlas_prospects became atlas_businesses, because
        # "prospect" is a role a company plays in one pipeline and naming the
        # permanent record after one role is how every factory ends up with its
        # own duplicate of the same customer. Nothing was ever released, so this
        # only has to fix development databases created the same day. Safe to
        # delete once none remain.
        conn.execute(
            text("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_name = 'atlas_prospects')
               AND NOT EXISTS (SELECT 1 FROM information_schema.tables
                               WHERE table_name = 'atlas_businesses') THEN
                ALTER TABLE atlas_prospects RENAME TO atlas_businesses;
            END IF;
        END $$;
        """)
        )
        conn.execute(
            text("""
        DO $$
        DECLARE t text;
        BEGIN
            FOREACH t IN ARRAY ARRAY['atlas_findings', 'atlas_opportunities',
                                     'atlas_proposals', 'atlas_outreach_messages',
                                     'atlas_pipeline_events'] LOOP
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name = t AND column_name = 'prospect_id') THEN
                    EXECUTE format('ALTER TABLE %I RENAME COLUMN prospect_id TO business_id', t);
                END IF;
            END LOOP;
        END $$;
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_businesses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            geography TEXT NOT NULL DEFAULT '',
            website TEXT,
            email TEXT,
            phone TEXT,
            identity_keys JSONB NOT NULL DEFAULT '[]',
            sources JSONB NOT NULL DEFAULT '[]',
            metadata JSONB NOT NULL DEFAULT '{}',
            first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
            last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        # Every sighting, not just the current state of the business.
        #
        # A separate table rather than columns on `atlas_businesses`, because a
        # business has one identity and many sightings: the same clinic seen by
        # Places in August and by Overpass in September is two observations of
        # one company, and collapsing them into "last source" throws away the
        # thing discovery is for. `first_seen_at` on the business answers "how
        # long have we known"; this answers "how did we come to know, and what
        # did the source actually say".
        #
        # `state` is the discovery state at the moment of the sighting and is
        # never recomputed: a sighting that was DISCOVERED_BY_QEVIK in August
        # stays that, even though the business is KNOWN by September. Rewriting
        # it would make the history agree with the present, which is the one
        # thing a history must not do.
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_sightings (
            id BIGSERIAL PRIMARY KEY,
            business_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            country TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            origin TEXT NOT NULL DEFAULT 'scan',
            state TEXT NOT NULL,
            because TEXT NOT NULL DEFAULT '',
            claims_about_the_world BOOLEAN NOT NULL DEFAULT FALSE,
            novelty JSONB,
            evidence JSONB NOT NULL DEFAULT '[]',
            observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
            recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """)
        )
        # Detected signals — observation, evidence, inference, action.
        #
        # **Not** `atlas_opportunities`, which already exists and holds the
        # findings-based funnel Opportunity (niche, stage, finding_ids). Those
        # are different things: a funnel Opportunity is a scored bundle of
        # confirmed website defects moving through a sales pipeline, and a
        # Signal is something noticed with a reading attached. Forcing one into
        # the other's table was the first attempt here, and `CREATE TABLE IF
        # NOT EXISTS` silently did nothing while the index below failed on a
        # column the existing table has never had.
        #
        # Persisted rather than derived on read:
        # deriving would mean re-running the extractors over stored bodies every
        # time somebody opens the list, and would silently change history when a
        # detector is improved. What was detected on the day is what was
        # detected, and the fingerprints say what it rested on.
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_signals (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT '',
            business_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT '',
            payload JSONB NOT NULL,
            evidence_fingerprints JSONB NOT NULL DEFAULT '[]',
            score DOUBLE PRECISION,
            -- Nullable on purpose. A business nobody has valued is not one
            -- worth nothing, and a DEFAULT 0 here would be the whole
            -- cost_status rule undone by a column definition.
            value_amount DOUBLE PRECISION,
            value_status TEXT NOT NULL DEFAULT 'UNKNOWN',
            needs_approval BOOLEAN NOT NULL DEFAULT TRUE,
            state TEXT NOT NULL DEFAULT 'open',
            detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
            recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """)
        )
        conn.execute(
            text("""
        CREATE INDEX IF NOT EXISTS atlas_signals_open
            ON atlas_signals (state, score DESC, detected_at DESC)
        """)
        )
        # One open opportunity of one kind per business. A nightly scan that
        # re-detected the same thing would otherwise produce one row per night
        # for ever, and the operator's list would be the same business repeated.
        conn.execute(
            text("""
        CREATE UNIQUE INDEX IF NOT EXISTS atlas_signals_once
            ON atlas_signals (business_id, kind, source)
            WHERE business_id <> ''
        """)
        )
        conn.execute(
            text("""
        CREATE INDEX IF NOT EXISTS atlas_sightings_business
            ON atlas_sightings (business_id, observed_at)
        """)
        )
        # One row per (source, source_id) per business. The same scan run twice
        # must not double-count, and a unique index is the only place that can
        # be guaranteed — a check in the service races itself the moment two
        # workers scan the same market.
        conn.execute(
            text("""
        CREATE UNIQUE INDEX IF NOT EXISTS atlas_sightings_once
            ON atlas_sightings (business_id, source, source_id, observed_at)
        """)
        )

        # Additive columns for databases that predate identity resolution.
        conn.execute(
            text("""
        ALTER TABLE atlas_businesses
        ADD COLUMN IF NOT EXISTS identity_keys JSONB NOT NULL DEFAULT '[]',
        ADD COLUMN IF NOT EXISTS sources JSONB NOT NULL DEFAULT '[]',
        ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP WITH TIME ZONE
            NOT NULL DEFAULT now(),
        ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE
            NOT NULL DEFAULT now()
        """)
        )
        conn.execute(text("ALTER TABLE atlas_businesses DROP COLUMN IF EXISTS niche"))
        conn.execute(text("ALTER TABLE atlas_businesses DROP COLUMN IF EXISTS source"))
        conn.execute(text("ALTER TABLE atlas_businesses DROP COLUMN IF EXISTS discovered_at"))
        # GIN over the identity keys: resolution runs once per discovered
        # business, and a sequential scan per candidate is the difference
        # between discovery scaling and not.
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS atlas_businesses_identity_idx "
                "ON atlas_businesses USING GIN (identity_keys jsonb_path_ops)"
            )
        )
        # Evidence is NOT NULL and the application refuses an empty list. A
        # claim Atlas cannot substantiate must be impossible to store, not
        # merely discouraged. Confidence records how much the observation is
        # worth trusting -- not every detector is equally reliable.
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_findings (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            severity TEXT NOT NULL,
            statement TEXT NOT NULL,
            evidence JSONB NOT NULL,
            confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            detected_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text(
                "ALTER TABLE atlas_findings ADD COLUMN IF NOT EXISTS confidence "
                "DOUBLE PRECISION NOT NULL DEFAULT 1.0"
            )
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_opportunities (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            niche TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'discovered',
            score DOUBLE PRECISION NOT NULL DEFAULT 0,
            estimated_value DOUBLE PRECISION,
            currency TEXT NOT NULL DEFAULT 'AED',
            finding_ids JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_proposals (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            opportunity_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            claims JSONB NOT NULL,
            offer TEXT NOT NULL DEFAULT '',
            price DOUBLE PRECISION,
            currency TEXT NOT NULL DEFAULT 'AED',
            findings_fingerprint TEXT NOT NULL DEFAULT '',
            generator TEXT NOT NULL DEFAULT 'unknown',
            generated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_outreach_messages (
            id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            approval_id TEXT,
            approved_fingerprint TEXT,
            provider_message_id TEXT,
            detail TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            sent_at TIMESTAMP WITH TIME ZONE
        )
        """)
        )
        # Atlas's permanent memory of a company. Append-only, keyed on the
        # business, and **shared across factories**: outreach today; a website
        # deployed, a listing updated, a video published, a support ticket
        # answered, later. One company, one chronological history, whichever
        # part of Atlas caused the entry.
        #
        # `factory` namespaces `kind`, so a new factory adds its own vocabulary
        # without an enum spanning all of them and without editing the
        # opportunity package. `opportunity_id` is nullable because a company is
        # discovered before it has an opportunity, and a deployment is not one
        # at all.
        #
        # Pre-release rename from atlas_pipeline_events: "pipeline" named it
        # after the first factory to write to it. Safe to delete once no
        # development database created earlier remains.
        conn.execute(
            text("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_name = 'atlas_pipeline_events')
               AND NOT EXISTS (SELECT 1 FROM information_schema.tables
                               WHERE table_name = 'atlas_business_events') THEN
                ALTER TABLE atlas_pipeline_events RENAME TO atlas_business_events;
            END IF;
        END $$;
        """)
        )
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_business_events (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            factory TEXT NOT NULL DEFAULT 'opportunity',
            kind TEXT NOT NULL,
            opportunity_id TEXT,
            actor TEXT NOT NULL DEFAULT 'system',
            detail JSONB NOT NULL DEFAULT '{}',
            at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text(
                "ALTER TABLE atlas_business_events ADD COLUMN IF NOT EXISTS factory TEXT "
                "NOT NULL DEFAULT 'opportunity'"
            )
        )
        conn.execute(
            text("ALTER TABLE atlas_business_events ALTER COLUMN opportunity_id DROP NOT NULL")
        )
        # Reading one company's whole history is the common query, so the index
        # leads with the business and orders by time.
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS atlas_business_events_timeline_idx "
                "ON atlas_business_events (business_id, at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS atlas_business_events_factory_idx "
                "ON atlas_business_events (factory, kind)"
            )
        )
        # -- Website Factory (M015) ----------------------------------------
        #
        # Same layering as Media and Opportunity: a site is content and carries
        # no HTML, theme or host; a build is the rendered artifact; a deployment
        # is one build sent to one target. See M015.md.
        #
        # The artifact is STORED, not referenced. `files` holds the build byte
        # for byte, which is the literal mechanism behind "rebuild from Business
        # memory" and behind moving a customer between hosts without a
        # migration. A row pointing at a directory on somebody's laptop would
        # satisfy every type in the package and none of the invariants.
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_sites (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            name TEXT NOT NULL,
            domain TEXT,
            content JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        # `fingerprint` is written once and recomputed on read. The redundancy
        # is deliberate: it is what lets a rebuild be checked rather than
        # trusted, and it catches both an altered record and non-deterministic
        # rendering.
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_site_builds (
            id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            files JSONB NOT NULL,
            fingerprint TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ready',
            generator TEXT NOT NULL DEFAULT 'authored',
            provenance JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        # Atlas's record of what is live and where -- never read back from a
        # provider's API, which depends on an account that can be closed. One
        # build may have many deployments: the same artifact on Cloudflare and
        # on Hetzner is two rows, and moving a customer promotes a different one
        # rather than rebuilding anything.
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_site_deployments (
            id TEXT PRIMARY KEY,
            build_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            remote_id TEXT,
            preview_url TEXT,
            live_url TEXT,
            build_fingerprint TEXT NOT NULL DEFAULT '',
            gate_findings JSONB NOT NULL DEFAULT '[]',
            detail TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            promoted_at TIMESTAMP WITH TIME ZONE
        )
        """)
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS atlas_site_deployments_live_idx "
                "ON atlas_site_deployments (site_id, target, status)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS atlas_site_builds_site_idx "
                "ON atlas_site_builds (site_id, created_at)"
            )
        )
        # Durable so that "never contact me again" survives a restart. A
        # suppression list that lives only in memory is not a suppression list.
        conn.execute(
            text("""
        CREATE TABLE IF NOT EXISTS atlas_outreach_suppressions (
            entry TEXT PRIMARY KEY,
            reason TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_runtime_executions
        ADD COLUMN IF NOT EXISTS approval_id TEXT,
        ADD COLUMN IF NOT EXISTS worker_id TEXT,
        ADD COLUMN IF NOT EXISTS lease_id TEXT,
        ADD COLUMN IF NOT EXISTS reservation_id TEXT,
        ADD COLUMN IF NOT EXISTS placement_reason TEXT
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_runs
        ADD COLUMN IF NOT EXISTS workspace_id TEXT,
        ADD COLUMN IF NOT EXISTS project_id TEXT,
        ADD COLUMN IF NOT EXISTS workflow_id TEXT,
        ADD COLUMN IF NOT EXISTS produced_asset_ids JSONB NOT NULL DEFAULT '[]'
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_jobs
        ADD COLUMN IF NOT EXISTS execution_decision_id TEXT,
        ADD COLUMN IF NOT EXISTS provider_name TEXT,
        ADD COLUMN IF NOT EXISTS output JSONB NOT NULL DEFAULT '{}',
        ADD COLUMN IF NOT EXISTS produced_asset_ids JSONB NOT NULL DEFAULT '[]'
        """)
        )
        conn.execute(
            text("""
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
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_assets
        ALTER COLUMN run_id DROP NOT NULL,
        ALTER COLUMN job_id DROP NOT NULL
        """)
        )
        conn.execute(
            text("""
        UPDATE atlas_assets
        SET project_id = 'project-unassigned'
        WHERE project_id IS NULL
        """)
        )
        conn.execute(
            text("""
        UPDATE atlas_assets
        SET updated_at = created_at
        WHERE updated_at IS NULL
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_chat_conversations
        ALTER COLUMN project_id SET DEFAULT 'project-unassigned',
        ALTER COLUMN title SET DEFAULT 'Conversation',
        ALTER COLUMN pinned SET DEFAULT FALSE,
        ALTER COLUMN prompt_version SET DEFAULT 0,
        ALTER COLUMN response_version SET DEFAULT 0,
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_chat_messages
        ALTER COLUMN version SET DEFAULT 1,
        ALTER COLUMN role SET DEFAULT 'assistant',
        ALTER COLUMN content SET DEFAULT '',
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_research_sessions
        ALTER COLUMN status SET DEFAULT 'active',
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_review_sessions
        ALTER COLUMN status SET DEFAULT 'pending',
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_review_items
        ALTER COLUMN decision SET DEFAULT 'pending',
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_review_comments
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """)
        )
        conn.execute(
            text("""
        ALTER TABLE atlas_review_history
        ALTER COLUMN metadata SET DEFAULT '{}'::jsonb
        """)
        )
        _create_indexes(conn)


#: Every index covers a lookup the kernel performs on a hot path. Names are
#: explicit so a DBA can audit them, and IF NOT EXISTS keeps startup idempotent.
INDEX_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    # Media Factory (M013). Every one of these backs a read that happens on the
    # hot path of building or reviewing a video.
    ("idx_episodes_series", "atlas_episodes", "series_id"),
    ("idx_scripts_episode", "atlas_scripts", "episode_id"),
    ("idx_scenes_script", "atlas_scenes", "script_id"),
    ("idx_renditions_episode", "atlas_renditions", "episode_id"),
    ("idx_scene_renders_rendition", "atlas_scene_renders", "rendition_id"),
    ("idx_scene_renders_scene", "atlas_scene_renders", "scene_id"),
    ("idx_publications_rendition", "atlas_publications", "rendition_id"),
    ("idx_assets_project", "atlas_assets", "project_id"),
    ("idx_assets_run", "atlas_assets", "run_id"),
    ("idx_assets_job", "atlas_assets", "job_id"),
    ("idx_assets_parent", "atlas_assets", "parent_asset_id"),
    ("idx_jobs_run", "atlas_jobs", "run_id"),
    ("idx_jobs_status", "atlas_jobs", "status"),
    ("idx_runs_project", "atlas_runs", "project_id"),
    ("idx_steps_run", "atlas_steps", "run_id"),
    ("idx_chat_messages_conversation", "atlas_chat_messages", "conversation_id"),
    ("idx_chat_conversations_project", "atlas_chat_conversations", "project_id"),
    ("idx_research_sessions_project", "atlas_research_sessions", "project_id"),
    ("idx_review_items_review", "atlas_review_items", "review_id"),
    ("idx_review_history_review", "atlas_review_history", "review_id"),
    ("idx_graph_nodes_project", "atlas_graph_nodes", "project_id"),
    ("idx_graph_edges_from", "atlas_graph_edges", "from_node"),
    ("idx_graph_edges_to", "atlas_graph_edges", "to_node"),
    ("idx_agents_project", "atlas_agents", "project_id"),
    ("idx_schedules_agent", "atlas_schedules", "agent_id"),
    ("idx_runtime_executions_schedule", "atlas_runtime_executions", "schedule_id"),
    ("idx_runtime_executions_status", "atlas_runtime_executions", "status"),
    ("idx_runtime_executions_worker", "atlas_runtime_executions", "worker_id"),
    ("idx_automation_runs_rule", "atlas_automation_runs", "rule_id"),
    ("idx_automation_logs_run", "atlas_automation_logs", "run_id"),
    ("idx_automation_rules_project", "atlas_automation_rules", "project_id"),
    ("idx_approval_requests_state", "atlas_approval_requests", "state"),
    ("idx_approval_requests_execution", "atlas_approval_requests", "execution_id"),
    ("idx_approval_history_approval", "atlas_approval_history", "approval_id"),
    ("idx_workers_status", "atlas_workers", "status"),
    ("idx_worker_heartbeats_worker", "atlas_worker_heartbeats", "worker_id"),
    ("idx_reservations_worker", "atlas_reservations", "worker_id"),
    ("idx_leases_worker", "atlas_leases", "worker_id"),
    ("idx_leases_state", "atlas_leases", "state"),
    ("idx_memberships_organization", "atlas_memberships", "organization_id"),
    ("idx_memberships_identity", "atlas_memberships", "identity_id"),
    ("idx_policy_sets_organization", "atlas_policy_sets", "organization_id"),
    ("idx_audit_organization", "atlas_audit_records", "organization_id"),
    ("idx_audit_created", "atlas_audit_records", "created_at"),
    ("idx_teams_organization", "atlas_teams", "organization_id"),
)


def _create_indexes(conn: Connection) -> None:
    for name, table, column in INDEX_DEFINITIONS:
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))


def list_expected_tables() -> list[str]:
    """Tables init_db is responsible for creating."""
    return sorted({table for _, table, _ in INDEX_DEFINITIONS})


def verify_schema() -> dict[str, object]:
    """Startup validation. Reports rather than raises, so a degraded database is
    visible in diagnostics instead of preventing the process from booting."""
    expected_tables = list_expected_tables()
    expected_indexes = [name for name, _, _ in INDEX_DEFINITIONS]

    with engine.connect() as conn:
        present_tables = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
            )
        }
        present_indexes = {
            row[0]
            for row in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
            )
        }

    missing_tables = [t for t in expected_tables if t not in present_tables]
    missing_indexes = [i for i in expected_indexes if i not in present_indexes]
    return {
        "healthy": not missing_tables and not missing_indexes,
        "tables_expected": len(expected_tables),
        "tables_present": len(expected_tables) - len(missing_tables),
        "missing_tables": missing_tables,
        "indexes_expected": len(expected_indexes),
        "indexes_present": len(expected_indexes) - len(missing_indexes),
        "missing_indexes": missing_indexes,
    }


def check_integrity() -> dict[str, object]:
    """Referential spot-checks over the joins the kernel actually relies on.
    Reports orphans; it never deletes anything."""
    checks: list[tuple[str, str]] = [
        (
            "jobs_without_run",
            "SELECT COUNT(*) FROM atlas_jobs j "
            "LEFT JOIN atlas_runs r ON j.run_id = r.id WHERE r.id IS NULL",
        ),
        (
            "leases_without_reservation",
            "SELECT COUNT(*) FROM atlas_leases l "
            "LEFT JOIN atlas_reservations res ON l.reservation_id = res.id WHERE res.id IS NULL",
        ),
        (
            "memberships_without_organization",
            "SELECT COUNT(*) FROM atlas_memberships m "
            "LEFT JOIN atlas_organizations o ON m.organization_id = o.id WHERE o.id IS NULL",
        ),
        (
            "automation_runs_without_rule",
            "SELECT COUNT(*) FROM atlas_automation_runs ar "
            "LEFT JOIN atlas_automation_rules r ON ar.rule_id = r.id WHERE r.id IS NULL",
        ),
        (
            "scenes_without_script",
            "SELECT COUNT(*) FROM atlas_scenes s "
            "LEFT JOIN atlas_scripts sc ON s.script_id = sc.id WHERE sc.id IS NULL",
        ),
        (
            "scene_renders_without_rendition",
            "SELECT COUNT(*) FROM atlas_scene_renders sr "
            "LEFT JOIN atlas_renditions r ON sr.rendition_id = r.id WHERE r.id IS NULL",
        ),
        (
            "publications_without_rendition",
            "SELECT COUNT(*) FROM atlas_publications p "
            "LEFT JOIN atlas_renditions r ON p.rendition_id = r.id WHERE r.id IS NULL",
        ),
    ]

    findings: dict[str, int] = {}
    with engine.connect() as conn:
        for name, sql in checks:
            findings[name] = int(conn.execute(text(sql)).scalar() or 0)

    return {"healthy": all(count == 0 for count in findings.values()), "orphans": findings}
