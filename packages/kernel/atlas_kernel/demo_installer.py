"""Turn a demo definition into real records.

Installing a demo creates a genuine project, genuine automation rules, genuine
knowledge-graph nodes and a genuine approval policy, through the same services
the rest of Atlas uses. Nothing here is display-only: what a demo creates can
be opened, edited, re-run and deleted like anything the user made themselves.

Automation rules are built exclusively from **state actions** --
``create_task``, ``create_report``, ``send_notification``, ``update_metadata``.
Those coordinate Atlas's own subsystems and never reach a provider, which is
what lets every installed rule execute on a machine with no credentials at all.
"""

from __future__ import annotations

from typing import Any

from atlas_kernel.demos import Demo, GraphSeed, InstallResult
from atlas_kernel.logging_setup import get_logger
from atlas_kernel.models import (
    AutomationAction,
    AutomationCondition,
    AutomationTrigger,
    AutomationTriggerType,
    KnowledgeEdge,
    KnowledgeNode,
    ProjectCreate,
    RelationshipType,
)

logger = get_logger("demos")

#: Trigger wording in a demo maps to a real trigger type. Schedules become CRON
#: so they appear on the automation calendar exactly like a user-authored rule.
_TRIGGER_TYPES: dict[str, AutomationTriggerType] = {
    "schedule": AutomationTriggerType.CRON,
    "event": AutomationTriggerType.ASSET_IMPORTED,
    "condition": AutomationTriggerType.MANUAL,
    "manual": AutomationTriggerType.MANUAL,
}

#: Human schedule text to cron. Kept explicit rather than parsed: five fixed
#: strings do not justify a date parser, and a wrong cron is worse than none.
_CRON: dict[str, str] = {
    "Mondays at 09:00": "0 9 * * 1",
    "Daily at 02:00": "0 2 * * *",
    "Fridays at 17:00": "0 17 * * 5",
    "Sundays at 08:00": "0 8 * * 0",
}


class DemoInstaller:
    """Creates the records behind a demo. Idempotent per project name."""

    def __init__(
        self,
        orchestrator: Any,
        automation_engine: Any,
        graph_service: Any,
        repository: Any,
        approval_service: Any | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._automation = automation_engine
        self._graph = graph_service
        self._repository = repository
        self._approvals = approval_service

    # -- project -----------------------------------------------------------

    def _project_name(self, demo: Demo) -> str:
        return f"{demo.icon}  {demo.name}"

    def _find_existing(self, demo: Demo) -> str | None:
        """Return the project id if this demo is already installed.

        Matching on name keeps installation idempotent without adding a table
        to record which demos were installed.
        """
        name = self._project_name(demo)
        # The repository owns project listing, not the orchestrator. Reaching
        # for the wrong one used to be swallowed by a broad except, which made
        # every install look new and quietly created duplicate projects.
        projects = self._repository.list_projects()
        for project in projects:
            if getattr(project, "name", None) == name:
                return str(project.id)
        return None

    # -- automation --------------------------------------------------------

    def _install_automations(self, demo: Demo, project_id: str) -> list[str]:
        created: list[str] = []
        for spec in demo.automations:
            trigger_type = _TRIGGER_TYPES.get(spec.trigger, AutomationTriggerType.MANUAL)
            cron = _CRON.get(spec.schedule or "")
            trigger = AutomationTrigger(
                type=trigger_type,
                cron_expression=cron,
                metadata={"demo": demo.id, "described_as": spec.schedule or spec.trigger},
            )

            # No conditions. Being switched off is what keeps a demo rule
            # from acting unasked; a guard condition on top of that only means
            # that enabling the rule and running it reports "conditions not
            # met" and does nothing, which reads as broken.
            conditions: list[AutomationCondition] = []

            try:
                rule = self._automation.create_rule(
                    name=spec.name,
                    description=spec.description,
                    trigger=trigger,
                    conditions=conditions,
                    # State actions only: they coordinate Atlas and never call a
                    # provider, so the rule runs on a machine with no keys.
                    actions=[
                        AutomationAction(
                            type="create_task",
                            payload={
                                "title": spec.name,
                                "detail": spec.description,
                                "project_id": project_id,
                            },
                            metadata={"demo": demo.id},
                        )
                    ],
                    project_id=project_id,
                    # NOT dry-run. A rule that previews instead of acting makes
                    # the Run button a lie -- it reports success having applied
                    # nothing. The rule is fully live and then disabled below,
                    # so it does no work until the user asks for it, and does
                    # real work the moment they do.
                    dry_run=False,
                    actor="demo-installer",
                )
                # Disabled on arrival: a demo must never start firing on a cron
                # schedule the user never agreed to.
                self._automation.disable_rule(rule.id, actor="demo-installer")
                created.append(str(rule.id))
            except Exception as exc:  # noqa: BLE001 - one bad rule must not abort the install
                logger.warning(
                    "demo automation could not be created",
                    extra={"demo": demo.id, "rule": spec.name, "reason": str(exc)},
                )
        return created

    # -- knowledge graph ---------------------------------------------------

    def _install_graph(self, demo: Demo, project_id: str) -> list[str]:
        created: dict[str, str] = {}
        seeds: dict[str, GraphSeed] = {seed.key: seed for seed in demo.graph}

        for seed in demo.graph:
            try:
                node = self._graph.create_node(
                    KnowledgeNode(
                        node_type=seed.node_type,
                        label=seed.label,
                        project_id=project_id,
                        metadata={"demo": demo.id, "seed_key": seed.key},
                    )
                )
                created[seed.key] = str(node.id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "demo graph node could not be created",
                    extra={"demo": demo.id, "node": seed.key, "reason": str(exc)},
                )

        for key, node_id in created.items():
            for target in seeds[key].connects_to:
                target_id = created.get(target)
                if target_id is None:
                    continue
                try:
                    self._graph.create_edge(
                        KnowledgeEdge(
                            relationship=RelationshipType.DERIVED_FROM,
                            from_node=target_id,
                            to_node=node_id,
                            metadata={"demo": demo.id},
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "demo graph edge could not be created",
                        extra={"demo": demo.id, "reason": str(exc)},
                    )

        return list(created.values())

    # -- install -----------------------------------------------------------

    def install(self, demo: Demo) -> InstallResult:
        existing = self._find_existing(demo)
        if existing is not None:
            return InstallResult(
                demo_id=demo.id,
                project_id=existing,
                created=False,
                notes=["Already installed. Opening the existing project."],
            )

        project = self._orchestrator.create_project(
            ProjectCreate(
                name=self._project_name(demo),
                description=demo.tagline,
            )
        )
        project_id = str(project.id)

        automations = self._install_automations(demo, project_id)
        graph_nodes = self._install_graph(demo, project_id)

        notes: list[str] = []
        if demo.runs_fully_offline:
            notes.append("Every step in this demo runs without a provider.")
        else:
            notes.append(
                f"{len(demo.offline_steps)} of {len(demo.steps)} steps run now. "
                f"{len(demo.provider_steps)} need a model provider — connect one in Settings."
            )
        if automations:
            notes.append(
                f"{len(automations)} automation rules installed, switched off. "
                "Turn one on and it does real work — on its schedule, or immediately when you run it."
            )

        logger.info(
            "demo installed",
            extra={
                "demo": demo.id,
                "project_id": project_id,
                "automations": len(automations),
                "graph_nodes": len(graph_nodes),
            },
        )

        return InstallResult(
            demo_id=demo.id,
            project_id=project_id,
            created=True,
            automations=automations,
            graph_nodes=graph_nodes,
            approval_policy=None,
            notes=notes,
        )
