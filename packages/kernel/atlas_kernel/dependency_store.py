"""What was last built, and with which inputs.

Separate from ``dependency`` so the graph itself stays pure: the algorithm has
no database, and the database has no opinion about what a node means.

``scope`` groups the fingerprints belonging to one piece of work -- a rendition,
today. Recording under a scope keeps the lookup to one indexed read and means a
scope can be dropped wholesale when the thing it described is deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from .db import SessionLocal


class DependencyStore:
    def recorded(self, scope: str) -> dict[str, str]:
        """Effective fingerprints from the last build of this scope.

        An empty result means nothing has been built, which the graph reads as
        "everything is stale" -- the correct answer for a first run.
        """
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT node_id, fingerprint FROM atlas_dependency_fingerprints "
                        "WHERE scope = :scope"
                    ),
                    {"scope": scope},
                )
                .mappings()
                .all()
            )
        return {row["node_id"]: row["fingerprint"] for row in rows}

    def record(self, scope: str, fingerprints: dict[str, str]) -> None:
        """Write down what was just built.

        Only for nodes that actually succeeded. Recording a fingerprint for
        work that failed would mark it fresh, and the next run would skip it --
        the failure would become permanent and invisible.
        """
        if not fingerprints:
            return
        now = datetime.now(UTC)
        with SessionLocal() as session:
            for node_id, fingerprint in fingerprints.items():
                session.execute(
                    text("""
                    INSERT INTO atlas_dependency_fingerprints
                        (scope, node_id, fingerprint, updated_at)
                    VALUES (:scope, :node_id, :fingerprint, :updated_at)
                    ON CONFLICT (scope, node_id)
                    DO UPDATE SET fingerprint = :fingerprint, updated_at = :updated_at
                    """),
                    {
                        "scope": scope,
                        "node_id": node_id,
                        "fingerprint": fingerprint,
                        "updated_at": now,
                    },
                )
            session.commit()

    def forget(self, scope: str, node_ids: list[str] | None = None) -> None:
        """Drop recorded fingerprints, forcing a rebuild.

        With no ``node_ids``, the whole scope goes -- which is what deleting a
        rendition should do, and what "rebuild everything" means when someone
        asks for it explicitly.
        """
        with SessionLocal() as session:
            if node_ids is None:
                session.execute(
                    text("DELETE FROM atlas_dependency_fingerprints WHERE scope = :scope"),
                    {"scope": scope},
                )
            else:
                for node_id in node_ids:
                    session.execute(
                        text(
                            "DELETE FROM atlas_dependency_fingerprints "
                            "WHERE scope = :scope AND node_id = :node_id"
                        ),
                        {"scope": scope, "node_id": node_id},
                    )
            session.commit()
