from __future__ import annotations

from collections import deque

from .event_bus import ContextBundleGenerated, EdgeCreated, EventBus, GraphSnapshotCreated, NodeArchived, NodeCreated
from .models import ContextBundle, GraphSnapshot, KnowledgeEdge, KnowledgeGraph, KnowledgeNode, RelationshipType
from .repository import AtlasRepository


class GraphService:
    def __init__(self, repository: AtlasRepository, event_bus: EventBus) -> None:
        self.repository = repository
        self.event_bus = event_bus

    def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
        created = self.repository.create_graph_node(node)
        self.event_bus.publish(NodeCreated(node_id=created.id, node_type=created.node_type))
        return created

    def archive_node(self, node_id: str) -> bool:
        archived = self.repository.archive_graph_node(node_id)
        if archived:
            self.event_bus.publish(NodeArchived(node_id=node_id))
        return archived

    def create_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge:
        created = self.repository.create_graph_edge(edge)
        self.event_bus.publish(
            EdgeCreated(
                edge_id=created.id,
                relationship=created.relationship.value,
                from_node=created.from_node,
                to_node=created.to_node,
            )
        )
        return created

    def get_node(self, node_id: str) -> KnowledgeNode | None:
        return self.repository.get_graph_node(node_id)

    def neighbors(self, node_id: str) -> list[KnowledgeNode]:
        edges = self.repository.list_graph_edges()
        neighbor_ids = {edge.to_node for edge in edges if edge.from_node == node_id} | {edge.from_node for edge in edges if edge.to_node == node_id}
        return [node for node in (self.repository.get_graph_node(item) for item in neighbor_ids) if node is not None]

    def incoming_edges(self, node_id: str) -> list[KnowledgeEdge]:
        return [edge for edge in self.repository.list_graph_edges() if edge.to_node == node_id]

    def outgoing_edges(self, node_id: str) -> list[KnowledgeEdge]:
        return [edge for edge in self.repository.list_graph_edges() if edge.from_node == node_id]

    def shortest_path(self, start_node: str, end_node: str) -> list[str]:
        if start_node == end_node:
            return [start_node]
        adjacency: dict[str, set[str]] = {}
        for edge in self.repository.list_graph_edges():
            adjacency.setdefault(edge.from_node, set()).add(edge.to_node)
            adjacency.setdefault(edge.to_node, set()).add(edge.from_node)
        queue: deque[tuple[str, list[str]]] = deque([(start_node, [start_node])])
        visited = {start_node}
        while queue:
            node_id, path = queue.popleft()
            for neighbor in adjacency.get(node_id, set()):
                if neighbor in visited:
                    continue
                next_path = [*path, neighbor]
                if neighbor == end_node:
                    return next_path
                visited.add(neighbor)
                queue.append((neighbor, next_path))
        return []

    def node_history(self, node_id: str) -> list[dict[str, object]]:
        node = self.repository.get_graph_node(node_id)
        if node is None:
            return []
        return [
            {"type": "node_created", "node_id": node.id, "timestamp": node.created_at.isoformat()},
            *[
                {
                    "type": "edge_created",
                    "edge_id": edge.id,
                    "relationship": edge.relationship.value,
                    "timestamp": edge.created_at.isoformat(),
                }
                for edge in self.repository.list_graph_edges()
                if edge.from_node == node_id or edge.to_node == node_id
            ],
        ]

    def project_subgraph(self, project_id: str) -> KnowledgeGraph:
        nodes = self.repository.list_graph_nodes(project_id=project_id)
        node_ids = {node.id for node in nodes}
        edges = [edge for edge in self.repository.list_graph_edges() if edge.from_node in node_ids or edge.to_node in node_ids]
        return KnowledgeGraph(nodes=nodes, edges=edges)

    def asset_lineage(self, asset_id: str) -> KnowledgeGraph:
        nodes = [node for node in self.repository.list_graph_nodes() if node.source_id == asset_id or node.id == asset_id]
        node_ids = {node.id for node in nodes}
        edges = [edge for edge in self.repository.list_graph_edges() if edge.from_node in node_ids or edge.to_node in node_ids]
        return KnowledgeGraph(nodes=nodes, edges=edges)

    def context_bundle(self, project_id: str) -> ContextBundle:
        project = self.repository.get_project(project_id)
        bundle = ContextBundle(
            project=project.model_dump() if project is not None else {},
            recent_chats=[item.model_dump() for item in self.repository.list_chat_conversations(project_id)],
            related_assets=[item.model_dump() for item in self.repository.list_assets(project_id=project_id)],
            research_findings=[item.model_dump() for item in self.repository.list_research_sessions(project_id)],
            reviews=[item.model_dump() for item in self.repository.list_review_sessions(project_id)],
            agent_history=[item.model_dump() for item in self.repository.list_agents(project_id)],
            workflow_history=[item.model_dump() for item in self.repository.list_workflows(project_id)],
            execution_history=[item.model_dump(mode="json") for item in self.repository.list_runtime_executions()],
            referenced_images=[item.model_dump() for item in self.repository.list_assets(project_id=project_id) if item.type == "image"],
            referenced_reports=[item.model_dump() for item in self.repository.list_assets(project_id=project_id) if item.type == "document"],
            graph=self.project_subgraph(project_id),
        )
        self.event_bus.publish(ContextBundleGenerated(project_id=project_id))
        return bundle

    def create_snapshot(self, scope_type: str, scope_id: str) -> GraphSnapshot:
        graph = self.project_subgraph(scope_id) if scope_type == "project" else KnowledgeGraph(nodes=self.repository.list_graph_nodes(), edges=self.repository.list_graph_edges())
        snapshot = GraphSnapshot(scope_type=scope_type, scope_id=scope_id, node_ids=[node.id for node in graph.nodes], edge_ids=[edge.id for edge in graph.edges])
        self.repository.create_graph_snapshot(snapshot)
        self.event_bus.publish(GraphSnapshotCreated(snapshot_id=snapshot.id, scope_type=scope_type, scope_id=scope_id))
        return snapshot

    def materialize_project_graph(self, project_id: str) -> KnowledgeGraph:
        project = self.repository.get_project(project_id)
        if project is not None:
            self.create_node(KnowledgeNode(id=project.id, node_type="Project", label=project.name, project_id=project.id, source_id=project.id))

        assets = self.repository.list_assets(project_id=project_id)
        for asset in assets:
            self.create_node(KnowledgeNode(id=asset.id, node_type=asset.type.title(), label=asset.metadata.get("title") or asset.id, project_id=project_id, source_id=asset.id, metadata={"uri": asset.uri}))
            self.create_edge(KnowledgeEdge(relationship=RelationshipType.BELONGS_TO, from_node=asset.id, to_node=project_id))
            if asset.parent_asset_id:
                self.create_edge(KnowledgeEdge(relationship=RelationshipType.VERSION_OF, from_node=asset.id, to_node=asset.parent_asset_id))
            for source_asset_id in asset.source_asset_ids:
                self.create_edge(KnowledgeEdge(relationship=RelationshipType.DERIVED_FROM, from_node=asset.id, to_node=source_asset_id))

        chats = self.repository.list_chat_conversations(project_id)
        for chat in chats:
            self.create_node(KnowledgeNode(id=chat.id, node_type="Conversation", label=chat.title, project_id=project_id, source_id=chat.id))
            self.create_edge(KnowledgeEdge(relationship=RelationshipType.BELONGS_TO, from_node=chat.id, to_node=project_id))
            if chat.prompt_asset_id:
                self.create_edge(KnowledgeEdge(relationship=RelationshipType.REFERENCES, from_node=chat.id, to_node=chat.prompt_asset_id))
            if chat.response_asset_id:
                self.create_edge(KnowledgeEdge(relationship=RelationshipType.REFERENCES, from_node=chat.id, to_node=chat.response_asset_id))

        research_sessions = self.repository.list_research_sessions(project_id)
        for session in research_sessions:
            self.create_node(KnowledgeNode(id=session.id, node_type="ResearchSession", label=session.title, project_id=project_id, source_id=session.id))
            self.create_edge(KnowledgeEdge(relationship=RelationshipType.BELONGS_TO, from_node=session.id, to_node=project_id))

        reviews = self.repository.list_review_sessions(project_id)
        for review in reviews:
            self.create_node(KnowledgeNode(id=review.id, node_type="ReviewSession", label=review.title, project_id=project_id, source_id=review.id))
            self.create_edge(KnowledgeEdge(relationship=RelationshipType.BELONGS_TO, from_node=review.id, to_node=project_id))
            if review.asset_id:
                self.create_edge(KnowledgeEdge(relationship=RelationshipType.REVIEWED_BY, from_node=review.asset_id, to_node=review.id))

        workflows = self.repository.list_workflows(project_id)
        for workflow in workflows:
            self.create_node(KnowledgeNode(id=workflow.id, node_type="Workflow", label=workflow.name, project_id=project_id, source_id=workflow.id))
            self.create_edge(KnowledgeEdge(relationship=RelationshipType.BELONGS_TO, from_node=workflow.id, to_node=project_id))

        runs = self.repository.list_runs_by_project(project_id)
        for run in runs:
            self.create_node(KnowledgeNode(id=run.id, node_type="WorkflowRun", label=run.title, project_id=project_id, source_id=run.id))
            self.create_edge(KnowledgeEdge(relationship=RelationshipType.EXECUTED_BY, from_node=run.id, to_node=project_id))
            if run.workflow_id:
                self.create_edge(KnowledgeEdge(relationship=RelationshipType.GENERATED_FOR, from_node=run.id, to_node=run.workflow_id))

        return self.project_subgraph(project_id)