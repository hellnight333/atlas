from __future__ import annotations

from typing import Any

from ..repository import AtlasRepository
from .plan_models import PlannerContext


class PlannerContextBuilder:
    """Build planner context only from existing Atlas services and repository data."""

    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def build(
        self,
        *,
        goal: str,
        project_id: str | None,
        workspace_id: str | None,
        agent_id: str,
        capabilities: list[str],
        workspace_intelligence: dict[str, Any],
    ) -> PlannerContext:
        assets = self.repository.list_assets(project_id=project_id) if project_id else self.repository.list_assets()[:50]
        chats = self.repository.list_chat_conversations(project_id) if project_id else []
        research = self.repository.list_research_sessions(project_id) if project_id else []
        reviews = self.repository.list_review_sessions(project_id) if project_id else []
        open_workflows = self.repository.list_workflows(project_id)

        if project_id:
            running_jobs = [
                job.model_dump()
                for job in self.repository.list_jobs_by_project(project_id)
                if job.status.value in {"queued", "running", "blocked"}
            ]
            recent_runs = [run.model_dump() for run in self.repository.list_runs_by_project(project_id)[:10]]
            knowledge_graph = self.repository.get_research_graph(project_id).model_dump()
        else:
            running_jobs = [
                job.model_dump()
                for job in self.repository.list_jobs()
                if job.status.value in {"queued", "running", "blocked"}
            ][:25]
            recent_runs = [run.model_dump() for run in self.repository.list_runs()[:10]]
            knowledge_graph = {"nodes": [], "edges": []}

        context = PlannerContext(
            goal=goal,
            workspace_id=workspace_id,
            project_id=project_id,
            agent_id=agent_id,
            workspace_intelligence=workspace_intelligence,
            capabilities=capabilities,
            assets=[asset.model_dump() for asset in assets[:50]],
            research=[item.model_dump() for item in research[:25]],
            chats=[item.model_dump() for item in chats[:25]],
            reviews=[item.model_dump() for item in reviews[:25]],
            open_workflows=[item.model_dump() for item in open_workflows[:25]],
            running_jobs=running_jobs,
            project_summary=workspace_intelligence.get("project_summary", {}),
            recent_work=[
                *workspace_intelligence.get("recent_activity", [])[:20],
                *recent_runs,
            ][:25],
            knowledge_graph=knowledge_graph,
        )
        return context
