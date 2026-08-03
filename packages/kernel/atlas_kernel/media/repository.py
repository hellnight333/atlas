"""Persistence for the Media Factory.

Its own repository rather than more methods on ``AtlasRepository``, which is
already long enough to be hard to navigate. Same conventions throughout:
parameterised ``text()`` SQL, one ``SessionLocal`` per operation, Pydantic
models in and out.

The layering rule from ``docs/VIDEO_FACTORY.md`` is enforced by the schema, not
by convention: content tables have no media columns to write to.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from ..db import SessionLocal
from .models import (
    Campaign,
    Episode,
    Publication,
    PublicationStatus,
    Rendition,
    RenditionKind,
    Scene,
    SceneRender,
    Script,
    Visibility,
    WorkStatus,
)


def _now() -> datetime:
    return datetime.now(UTC)


class MediaRepository:
    # -- content layer ----------------------------------------------------

    def create_campaign(self, campaign: Campaign) -> Campaign:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_campaigns
                    (id, name, description, default_channel, metadata, created_at)
                VALUES (:id, :name, :description, :default_channel, :metadata, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": campaign.id,
                    "name": campaign.name,
                    "description": campaign.description,
                    "default_channel": campaign.default_channel,
                    "metadata": json.dumps(campaign.metadata),
                    "created_at": campaign.created_at,
                },
            )
            session.commit()
        return campaign

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_campaigns WHERE id = :id"), {"id": campaign_id}
                )
                .mappings()
                .first()
            )
        return Campaign(**dict(row)) if row else None

    def list_campaigns(self) -> list[Campaign]:
        with SessionLocal() as session:
            rows = (
                session.execute(text("SELECT * FROM atlas_campaigns ORDER BY created_at"))
                .mappings()
                .all()
            )
        return [Campaign(**dict(row)) for row in rows]

    def create_episode(self, episode: Episode) -> Episode:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_episodes
                    (id, campaign_id, brief, title, summary, status, metadata,
                     created_at, updated_at)
                VALUES (:id, :campaign_id, :brief, :title, :summary, :status, :metadata,
                        :created_at, :updated_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": episode.id,
                    "campaign_id": episode.campaign_id,
                    "brief": episode.brief,
                    "title": episode.title,
                    "summary": episode.summary,
                    "status": episode.status.value,
                    "metadata": json.dumps(episode.metadata),
                    "created_at": episode.created_at,
                    "updated_at": episode.updated_at,
                },
            )
            session.commit()
        return episode

    def get_episode(self, episode_id: str) -> Episode | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_episodes WHERE id = :id"), {"id": episode_id}
                )
                .mappings()
                .first()
            )
        return Episode(**dict(row)) if row else None

    def list_episodes(self, campaign_id: str | None = None) -> list[Episode]:
        sql = "SELECT * FROM atlas_episodes"
        params: dict[str, Any] = {}
        if campaign_id is not None:
            sql += " WHERE campaign_id = :campaign_id"
            params["campaign_id"] = campaign_id
        sql += " ORDER BY created_at"
        with SessionLocal() as session:
            rows = session.execute(text(sql), params).mappings().all()
        return [Episode(**dict(row)) for row in rows]

    def update_episode(self, episode_id: str, **fields: Any) -> Episode | None:
        allowed = {"title", "summary", "status", "brief"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_episode(episode_id)
        if isinstance(updates.get("status"), WorkStatus):
            updates["status"] = updates["status"].value
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        with SessionLocal() as session:
            session.execute(
                text(
                    f"UPDATE atlas_episodes SET {assignments}, updated_at = :updated_at "
                    "WHERE id = :id"
                ),
                {**updates, "id": episode_id, "updated_at": _now()},
            )
            session.commit()
        return self.get_episode(episode_id)

    def create_script(self, script: Script) -> Script:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_scripts (id, episode_id, version, authored_by, notes, created_at)
                VALUES (:id, :episode_id, :version, :authored_by, :notes, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": script.id,
                    "episode_id": script.episode_id,
                    "version": script.version,
                    "authored_by": script.authored_by,
                    "notes": script.notes,
                    "created_at": script.created_at,
                },
            )
            session.commit()
        return script

    def next_script_version(self, episode_id: str) -> int:
        """The version a new script for this episode should take.

        Scripts are never overwritten -- a rewrite is a new version, so a
        rendition built from version 1 keeps meaning something after version 2
        exists.
        """
        with SessionLocal() as session:
            current = session.execute(
                text("SELECT MAX(version) FROM atlas_scripts WHERE episode_id = :episode_id"),
                {"episode_id": episode_id},
            ).scalar()
        return int(current or 0) + 1

    def get_script(self, script_id: str) -> Script | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_scripts WHERE id = :id"), {"id": script_id}
                )
                .mappings()
                .first()
            )
        return Script(**dict(row)) if row else None

    def latest_script(self, episode_id: str) -> Script | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text(
                        "SELECT * FROM atlas_scripts WHERE episode_id = :episode_id "
                        "ORDER BY version DESC LIMIT 1"
                    ),
                    {"episode_id": episode_id},
                )
                .mappings()
                .first()
            )
        return Script(**dict(row)) if row else None

    def replace_scenes(self, script_id: str, scenes: list[Scene]) -> list[Scene]:
        """Write the scenes of a script as one set.

        Scenes are meaningful only as an ordered whole, so they are written
        together. Editing a single scene goes through ``update_scene``.
        """
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM atlas_scenes WHERE script_id = :script_id"),
                {"script_id": script_id},
            )
            for scene in scenes:
                session.execute(
                    text("""
                    INSERT INTO atlas_scenes
                        (id, script_id, index_in_script, heading, narration,
                         visual_direction, target_seconds, metadata)
                    VALUES (:id, :script_id, :index_in_script, :heading, :narration,
                            :visual_direction, :target_seconds, :metadata)
                    """),
                    {
                        "id": scene.id,
                        "script_id": script_id,
                        "index_in_script": scene.index,
                        "heading": scene.heading,
                        "narration": scene.narration,
                        "visual_direction": scene.visual_direction,
                        "target_seconds": scene.target_seconds,
                        "metadata": json.dumps(scene.metadata),
                    },
                )
            session.commit()
        return self.list_scenes(script_id)

    def list_scenes(self, script_id: str) -> list[Scene]:
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT * FROM atlas_scenes WHERE script_id = :script_id "
                        "ORDER BY index_in_script"
                    ),
                    {"script_id": script_id},
                )
                .mappings()
                .all()
            )
        return [_scene_from_row(row) for row in rows]

    def get_scene(self, scene_id: str) -> Scene | None:
        with SessionLocal() as session:
            row = (
                session.execute(text("SELECT * FROM atlas_scenes WHERE id = :id"), {"id": scene_id})
                .mappings()
                .first()
            )
        return _scene_from_row(row) if row else None

    def update_scene(self, scene_id: str, **fields: Any) -> Scene | None:
        allowed = {"heading", "narration", "visual_direction", "target_seconds"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_scene(scene_id)
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        with SessionLocal() as session:
            session.execute(
                text(f"UPDATE atlas_scenes SET {assignments} WHERE id = :id"),
                {**updates, "id": scene_id},
            )
            session.commit()
        return self.get_scene(scene_id)

    # -- rendering layer --------------------------------------------------

    def create_rendition(self, rendition: Rendition) -> Rendition:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_renditions
                    (id, episode_id, script_id, kind, status, asset_id, scene_fingerprint,
                     build_metadata, error, created_at, updated_at)
                VALUES (:id, :episode_id, :script_id, :kind, :status, :asset_id,
                        :scene_fingerprint, :build_metadata, :error, :created_at, :updated_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": rendition.id,
                    "episode_id": rendition.episode_id,
                    "script_id": rendition.script_id,
                    "kind": rendition.kind.value,
                    "status": rendition.status.value,
                    "asset_id": rendition.asset_id,
                    "scene_fingerprint": rendition.scene_fingerprint,
                    "build_metadata": json.dumps(rendition.build_metadata),
                    "error": rendition.error,
                    "created_at": rendition.created_at,
                    "updated_at": rendition.updated_at,
                },
            )
            session.commit()
        return rendition

    def get_rendition(self, rendition_id: str) -> Rendition | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_renditions WHERE id = :id"), {"id": rendition_id}
                )
                .mappings()
                .first()
            )
        return _rendition_from_row(row) if row else None

    def list_renditions(self, episode_id: str) -> list[Rendition]:
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT * FROM atlas_renditions WHERE episode_id = :episode_id "
                        "ORDER BY created_at"
                    ),
                    {"episode_id": episode_id},
                )
                .mappings()
                .all()
            )
        return [_rendition_from_row(row) for row in rows]

    def update_rendition(self, rendition_id: str, **fields: Any) -> Rendition | None:
        allowed = {"status", "asset_id", "scene_fingerprint", "build_metadata", "error"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_rendition(rendition_id)
        if isinstance(updates.get("status"), WorkStatus):
            updates["status"] = updates["status"].value
        if "build_metadata" in updates:
            updates["build_metadata"] = json.dumps(updates["build_metadata"])
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        with SessionLocal() as session:
            session.execute(
                text(
                    f"UPDATE atlas_renditions SET {assignments}, updated_at = :updated_at "
                    "WHERE id = :id"
                ),
                {**updates, "id": rendition_id, "updated_at": _now()},
            )
            session.commit()
        return self.get_rendition(rendition_id)

    def create_scene_render(self, render: SceneRender) -> SceneRender:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_scene_renders
                    (id, rendition_id, scene_id, index_in_script, status, provider, recipe_id,
                     media_asset_id, audio_asset_id, duration_seconds, source_fingerprint,
                     job_id, error, created_at, updated_at)
                VALUES (:id, :rendition_id, :scene_id, :index_in_script, :status, :provider,
                        :recipe_id, :media_asset_id, :audio_asset_id, :duration_seconds,
                        :source_fingerprint, :job_id, :error, :created_at, :updated_at)
                ON CONFLICT (rendition_id, scene_id) DO NOTHING
                """),
                {
                    "id": render.id,
                    "rendition_id": render.rendition_id,
                    "scene_id": render.scene_id,
                    "index_in_script": render.index,
                    "status": render.status.value,
                    "provider": render.provider,
                    "recipe_id": render.recipe_id,
                    "media_asset_id": render.media_asset_id,
                    "audio_asset_id": render.audio_asset_id,
                    "duration_seconds": render.duration_seconds,
                    "source_fingerprint": render.source_fingerprint,
                    "job_id": render.job_id,
                    "error": render.error,
                    "created_at": render.created_at,
                    "updated_at": render.updated_at,
                },
            )
            session.commit()
        return render

    def get_scene_render(self, render_id: str) -> SceneRender | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_scene_renders WHERE id = :id"), {"id": render_id}
                )
                .mappings()
                .first()
            )
        return _scene_render_from_row(row) if row else None

    def list_scene_renders(self, rendition_id: str) -> list[SceneRender]:
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT * FROM atlas_scene_renders WHERE rendition_id = :rendition_id "
                        "ORDER BY index_in_script"
                    ),
                    {"rendition_id": rendition_id},
                )
                .mappings()
                .all()
            )
        return [_scene_render_from_row(row) for row in rows]

    def update_scene_render(self, render_id: str, **fields: Any) -> SceneRender | None:
        allowed = {
            "status",
            "provider",
            "recipe_id",
            "media_asset_id",
            "audio_asset_id",
            "duration_seconds",
            "source_fingerprint",
            "job_id",
            "error",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_scene_render(render_id)
        if isinstance(updates.get("status"), WorkStatus):
            updates["status"] = updates["status"].value
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        with SessionLocal() as session:
            session.execute(
                text(
                    f"UPDATE atlas_scene_renders SET {assignments}, updated_at = :updated_at "
                    "WHERE id = :id"
                ),
                {**updates, "id": render_id, "updated_at": _now()},
            )
            session.commit()
        return self.get_scene_render(render_id)

    # -- publishing -------------------------------------------------------

    def create_publication(self, publication: Publication) -> Publication:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_publications
                    (id, rendition_id, platform, approval_id, visibility, title, description,
                     tags, thumbnail_asset_id, remote_id, remote_url, status, error,
                     created_at, updated_at)
                VALUES (:id, :rendition_id, :platform, :approval_id, :visibility, :title,
                        :description, :tags, :thumbnail_asset_id, :remote_id, :remote_url,
                        :status, :error, :created_at, :updated_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": publication.id,
                    "rendition_id": publication.rendition_id,
                    "platform": publication.platform,
                    "approval_id": publication.approval_id,
                    "visibility": publication.visibility.value,
                    "title": publication.title,
                    "description": publication.description,
                    "tags": json.dumps(publication.tags),
                    "thumbnail_asset_id": publication.thumbnail_asset_id,
                    "remote_id": publication.remote_id,
                    "remote_url": publication.remote_url,
                    "status": publication.status.value,
                    "error": publication.error,
                    "created_at": publication.created_at,
                    "updated_at": publication.updated_at,
                },
            )
            session.commit()
        return publication

    def get_publication(self, publication_id: str) -> Publication | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_publications WHERE id = :id"), {"id": publication_id}
                )
                .mappings()
                .first()
            )
        return _publication_from_row(row) if row else None

    def list_publications(self, rendition_id: str) -> list[Publication]:
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT * FROM atlas_publications WHERE rendition_id = :rendition_id "
                        "ORDER BY created_at"
                    ),
                    {"rendition_id": rendition_id},
                )
                .mappings()
                .all()
            )
        return [_publication_from_row(row) for row in rows]

    def update_publication(self, publication_id: str, **fields: Any) -> Publication | None:
        allowed = {
            "approval_id",
            "visibility",
            "title",
            "description",
            "tags",
            "thumbnail_asset_id",
            "remote_id",
            "remote_url",
            "status",
            "error",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_publication(publication_id)
        if isinstance(updates.get("status"), PublicationStatus):
            updates["status"] = updates["status"].value
        if isinstance(updates.get("visibility"), Visibility):
            updates["visibility"] = updates["visibility"].value
        if "tags" in updates:
            updates["tags"] = json.dumps(updates["tags"])
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        with SessionLocal() as session:
            session.execute(
                text(
                    f"UPDATE atlas_publications SET {assignments}, updated_at = :updated_at "
                    "WHERE id = :id"
                ),
                {**updates, "id": publication_id, "updated_at": _now()},
            )
            session.commit()
        return self.get_publication(publication_id)


# -- row mapping ----------------------------------------------------------
#
# `index` and `index_in_script` differ because `index` is a builtin-ish name in
# SQL contexts; the column is explicit and the model field is not.


def _scene_from_row(row: Any) -> Scene:
    data = dict(row)
    data["index"] = data.pop("index_in_script")
    return Scene(**data)


def _rendition_from_row(row: Any) -> Rendition:
    data = dict(row)
    data["kind"] = RenditionKind(data["kind"])
    data["status"] = WorkStatus(data["status"])
    return Rendition(**data)


def _scene_render_from_row(row: Any) -> SceneRender:
    data = dict(row)
    data["index"] = data.pop("index_in_script")
    data["status"] = WorkStatus(data["status"])
    return SceneRender(**data)


def _publication_from_row(row: Any) -> Publication:
    data = dict(row)
    data["visibility"] = Visibility(data["visibility"])
    data["status"] = PublicationStatus(data["status"])
    return Publication(**data)
