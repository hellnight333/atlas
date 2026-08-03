"""First-run state.

Whether someone has been through setup belongs to the *installation*, not to a
browser. localStorage would forget on a cache clear and would re-run setup in a
second window, so this lives in the database beside everything else.

The record is deliberately small: which steps are done, what the user chose,
and when they finished. Provider credentials are not stored here -- this module
records that a provider was configured, never the key itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import text

from atlas_kernel.logging_setup import get_logger

logger = get_logger("onboarding")

#: One row, always. Setup state is a property of the installation.
SETTINGS_KEY = "onboarding"


class OnboardingStep(StrEnum):
    """The setup flow, in order."""

    WELCOME = "welcome"
    WORKSPACE = "workspace"
    DATA_LOCATION = "data_location"
    THEME = "theme"
    DIAGNOSTICS = "diagnostics"
    PROVIDERS = "providers"
    DEMOS = "demos"
    DONE = "done"


#: The order the UI walks. `DONE` is a terminal marker, not a screen.
STEP_ORDER: tuple[OnboardingStep, ...] = (
    OnboardingStep.WELCOME,
    OnboardingStep.WORKSPACE,
    OnboardingStep.DATA_LOCATION,
    OnboardingStep.THEME,
    OnboardingStep.DIAGNOSTICS,
    OnboardingStep.PROVIDERS,
    OnboardingStep.DEMOS,
)


class Theme(StrEnum):
    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"


@dataclass
class OnboardingState:
    """What the user has done and chosen."""

    completed: bool = False
    current_step: OnboardingStep = OnboardingStep.WELCOME
    completed_steps: list[str] = field(default_factory=list)
    workspace_id: str | None = None
    workspace_name: str | None = None
    theme: Theme = Theme.DARK
    data_directory: str | None = None
    #: Provider *names* only. Credentials never live here.
    configured_providers: list[str] = field(default_factory=list)
    installed_demos: list[str] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    #: Set when the user chooses "skip setup". Recorded rather than inferred so
    #: the difference between "finished" and "skipped" stays visible.
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "current_step": str(self.current_step),
            "completed_steps": self.completed_steps,
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "theme": str(self.theme),
            "data_directory": self.data_directory,
            "configured_providers": self.configured_providers,
            "installed_demos": self.installed_demos,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "skipped": self.skipped,
            "steps": [str(step) for step in STEP_ORDER],
            "progress": self.progress,
        }

    @property
    def progress(self) -> float:
        """0.0 to 1.0, for the progress indicator."""
        if self.completed:
            return 1.0
        done = len([s for s in self.completed_steps if s in {str(x) for x in STEP_ORDER}])
        return round(done / len(STEP_ORDER), 3)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OnboardingState:
        raw_step = payload.get("current_step", OnboardingStep.WELCOME.value)
        raw_theme = payload.get("theme", Theme.DARK.value)
        return cls(
            completed=bool(payload.get("completed", False)),
            current_step=(
                OnboardingStep(raw_step)
                if raw_step in {s.value for s in OnboardingStep}
                else OnboardingStep.WELCOME
            ),
            completed_steps=list(payload.get("completed_steps", [])),
            workspace_id=payload.get("workspace_id"),
            workspace_name=payload.get("workspace_name"),
            theme=(Theme(raw_theme) if raw_theme in {t.value for t in Theme} else Theme.DARK),
            data_directory=payload.get("data_directory"),
            configured_providers=list(payload.get("configured_providers", [])),
            installed_demos=list(payload.get("installed_demos", [])),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            skipped=bool(payload.get("skipped", False)),
        )


class OnboardingService:
    """Reads and writes the single onboarding record."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def _read(self) -> dict[str, Any] | None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text("SELECT value FROM atlas_app_settings WHERE key = :key"),
                {"key": SETTINGS_KEY},
            ).fetchone()
        if row is None:
            return None
        value = row[0]
        return json.loads(value) if isinstance(value, str) else dict(value)

    def _write(self, payload: dict[str, Any]) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO atlas_app_settings (key, value, updated_at)
                    VALUES (:key, CAST(:value AS JSONB), :updated_at)
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                    """),
                {
                    "key": SETTINGS_KEY,
                    "value": json.dumps(payload),
                    "updated_at": datetime.now(UTC),
                },
            )

    def state(self) -> OnboardingState:
        """Current state. A missing row means setup has never been started."""
        payload = self._read()
        if payload is None:
            return OnboardingState(started_at=datetime.now(UTC).isoformat())
        return OnboardingState.from_dict(payload)

    def save(self, state: OnboardingState) -> OnboardingState:
        if state.started_at is None:
            state.started_at = datetime.now(UTC).isoformat()
        self._write(state.to_dict())
        return state

    def complete_step(self, step: OnboardingStep, **changes: Any) -> OnboardingState:
        """Mark a step done, record what it produced, and advance.

        Completing a step twice is not an error -- a user can go back and change
        an answer, and the step should not appear twice in the record.
        """
        state = self.state()

        for key, value in changes.items():
            if value is None or not hasattr(state, key):
                continue
            setattr(state, key, value)

        if str(step) not in state.completed_steps:
            state.completed_steps.append(str(step))

        state.current_step = self._next_step(state)
        if state.current_step is OnboardingStep.DONE:
            state.completed = True
            state.completed_at = datetime.now(UTC).isoformat()

        logger.info(
            "onboarding step completed",
            extra={"step": str(step), "progress": state.progress},
        )
        return self.save(state)

    def _next_step(self, state: OnboardingState) -> OnboardingStep:
        done = set(state.completed_steps)
        for step in STEP_ORDER:
            if str(step) not in done:
                return step
        return OnboardingStep.DONE

    def skip(self) -> OnboardingState:
        """Leave setup early. Everything unanswered keeps its default."""
        state = self.state()
        state.completed = True
        state.skipped = True
        state.current_step = OnboardingStep.DONE
        state.completed_at = datetime.now(UTC).isoformat()
        logger.info("onboarding skipped", extra={"progress": state.progress})
        return self.save(state)

    def reset(self) -> OnboardingState:
        """Run setup again. Nothing the user created is touched."""
        fresh = OnboardingState(started_at=datetime.now(UTC).isoformat())
        logger.info("onboarding reset")
        return self.save(fresh)

    def record_demo(self, demo_id: str) -> OnboardingState:
        state = self.state()
        if demo_id not in state.installed_demos:
            state.installed_demos.append(demo_id)
        return self.save(state)
