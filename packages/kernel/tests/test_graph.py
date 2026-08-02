from __future__ import annotations

from fastapi.testclient import TestClient

from atlas_kernel.api import app, graph_service
from atlas_kernel.event_bus import ContextBundleGenerated, EdgeCreated, GraphSnapshotCreated, NodeCreated
from atlas_kernel.models import KnowledgeEdge, KnowledgeNode, RelationshipType


client = TestClient(app)


def _create_project() -> str:
    workspace = client.post("/workspaces", json={"name": "graph-ws", "description": "graph"})
    assert workspace.status_code == 200
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "graph-project",
            "description": "graph",
        },
    )
    assert project.status_code == 200
    return project.json()["project_id"]


def test_graph_node_creation_and_edge_creation() -> None:
    project_id = _create_project()
    project_node = graph_service.create_node(KnowledgeNode(id=project_id, node_type="Project", label="Graph Project", project_id=project_id, source_id=project_id))
    asset_node = graph_service.create_node(KnowledgeNode(node_type="Asset", label="Graph Asset", project_id=project_id, source_id="asset-graph-1"))
    edge = graph_service.create_edge(KnowledgeEdge(relationship=RelationshipType.BELONGS_TO, from_node=asset_node.id, to_node=project_node.id))

    assert project_node.id == project_id
    assert asset_node.project_id == project_id
    assert edge.relationship == RelationshipType.BELONGS_TO


def test_graph_neighbors_and_traversal() -> None:
    project_id = _create_project()
    project_node = graph_service.create_node(KnowledgeNode(node_type="Project", label="Project A", project_id=project_id, source_id=f"project-{project_id}"))
    chat_node = graph_service.create_node(KnowledgeNode(node_type="Chat", label="Chat A", project_id=project_id, source_id="chat-a"))
    asset_node = graph_service.create_node(KnowledgeNode(node_type="Asset", label="Asset A", project_id=project_id, source_id="asset-a"))
    graph_service.create_edge(KnowledgeEdge(relationship=RelationshipType.BELONGS_TO, from_node=chat_node.id, to_node=project_node.id))
    graph_service.create_edge(KnowledgeEdge(relationship=RelationshipType.REFERENCES, from_node=chat_node.id, to_node=asset_node.id))

    neighbors = graph_service.neighbors(chat_node.id)
    path = graph_service.shortest_path(project_node.id, asset_node.id)
    assert {node.id for node in neighbors} >= {project_node.id, asset_node.id}
    assert path[0] == project_node.id
    assert path[-1] == asset_node.id


def test_graph_context_bundle_and_snapshot() -> None:
    created_nodes: list[object] = []
    created_edges: list[object] = []
    created_snapshots: list[object] = []
    created_contexts: list[object] = []

    graph_service.event_bus.subscribe(NodeCreated, lambda event: created_nodes.append(event))
    graph_service.event_bus.subscribe(EdgeCreated, lambda event: created_edges.append(event))
    graph_service.event_bus.subscribe(GraphSnapshotCreated, lambda event: created_snapshots.append(event))
    graph_service.event_bus.subscribe(ContextBundleGenerated, lambda event: created_contexts.append(event))

    project_id = _create_project()
    asset = client.post(
        "/assets",
        json={
            "type": "document",
            "project_id": project_id,
            "uri": "atlas://graph/report",
            "metadata": {"title": "Graph Report"},
        },
    )
    assert asset.status_code == 200

    project_graph = client.get(f"/graph/project/{project_id}")
    assert project_graph.status_code == 200
    payload = project_graph.json()
    assert payload["graph"]["nodes"]
    assert payload["snapshot"]["id"]

    context = client.get(f"/graph/context/{project_id}")
    assert context.status_code == 200
    context_payload = context.json()
    assert "project" in context_payload
    assert "graph" in context_payload

    assert created_nodes
    assert created_edges
    assert created_snapshots
    assert created_contexts


def test_graph_lineage_and_history() -> None:
    project_id = _create_project()
    parent = client.post(
        "/assets",
        json={
            "type": "document",
            "project_id": project_id,
            "uri": "atlas://graph/parent",
            "metadata": {"title": "Parent"},
        },
    )
    assert parent.status_code == 200
    child = client.post(
        "/assets",
        json={
            "type": "image",
            "project_id": project_id,
            "parent_asset_id": parent.json()["id"],
            "source_asset_ids": [parent.json()["id"]],
            "uri": "atlas://graph/child",
            "metadata": {"title": "Child"},
        },
    )
    assert child.status_code == 200

    client.get(f"/graph/project/{project_id}")

    lineage = client.get(f"/graph/lineage/{child.json()['id']}")
    assert lineage.status_code == 200
    assert lineage.json()["nodes"]

    history = client.get(f"/graph/history/{child.json()['id']}")
    assert history.status_code == 200
    assert isinstance(history.json(), list)