from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ..event_bus import EventBus
from ..repository import AtlasRepository
from .events import (
    AgentCreated,
    AgentDeleted,
    AgentStateChanged,
    AgentUpdated,
    AgentAssigned,
    AgentCompleted,
    AgentFailed,
    AgentMessageReceived,
    AgentMessageSent,
    AgentStarted,
    AgentWaiting,
    MemoryAttached,
    PermissionUpdated,
    TeamCompleted,
)
from .context_builder import PlannerContextBuilder
from .memory import AgentMemoryManager
from .models import (
    Agent,
    AgentAssignment,
    AgentAssignmentStatus,
    AgentCapabilitySet,
    AgentConversation,
    AgentCreate,
    AgentMailbox,
    AgentMemoryReference,
    AgentMessage,
    AgentMessageType,
    AgentPermission,
    AgentRole,
    AgentStatus,
    AgentTeam,
    AgentTeamStatus,
    AgentUpdate,
)
from .schedule_models import ExecutionSchedule, QueueUpdateResult, SchedulerPriority, SchedulerRequest
from .scheduler import AgentScheduler
from .planner import AgentPlanner
from .plan_models import ExecutionPlan, PlanStep
from .permissions import AgentPermissionSet
from .runtime import AgentRuntime


class AgentFoundation:
    def __init__(self, repository: AtlasRepository, event_bus: EventBus, worker: object | None = None, approval_gate: object | None = None) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self._context_builder = PlannerContextBuilder(repository)
        self._planner = AgentPlanner()
        self._scheduler = AgentScheduler(repository=repository, event_bus=event_bus)
        # The gate must reach this runtime too: every execution path has to be
        # gated, not just the one the composition root hands out.
        self._runtime = AgentRuntime(repository=repository, event_bus=event_bus, worker=worker, approval_gate=approval_gate)

    def create_agent(self, request: AgentCreate) -> Agent:
        memory_id = request.memory_id or f"agent-memory-{uuid4().hex[:12]}"
        agent = Agent(
            name=request.name,
            description=request.description,
            role=request.role,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            capabilities=list(request.capabilities),
            status=request.status,
            memory_id=memory_id,
            permission_set=AgentPermissionSet.normalize(request.permission_set),
        )
        created = self.repository.create_agent(agent)
        self.event_bus.publish(
            AgentCreated(
                agent_id=created.id,
                workspace_id=created.workspace_id,
                project_id=created.project_id,
            )
        )
        return created

    def list_agents(self, project_id: str | None = None) -> list[Agent]:
        return self.repository.list_agents(project_id=project_id)

    def get_agent(self, agent_id: str) -> Agent | None:
        return self.repository.get_agent(agent_id)

    def update_agent(self, agent_id: str, update: AgentUpdate) -> Agent | None:
        existing = self.repository.get_agent(agent_id)
        if existing is None:
            return None

        payload = update.model_dump(exclude_unset=True)
        if "permission_set" in payload and payload["permission_set"] is not None:
            payload["permission_set"] = AgentPermissionSet.normalize(payload["permission_set"])

        transitioned = existing
        if "status" in payload and payload["status"] is not None:
            next_status = AgentStatus(payload["status"])
            transitioned = AgentRuntime.transition(existing, next_status)

        updated = transitioned.model_copy(
            update={
                **payload,
                "updated_at": datetime.now(UTC),
            }
        )
        saved = self.repository.update_agent(updated)

        self.event_bus.publish(AgentUpdated(agent_id=saved.id))
        if existing.status != saved.status:
            self.event_bus.publish(
                AgentStateChanged(
                    agent_id=saved.id,
                    previous_status=existing.status,
                    current_status=saved.status,
                )
            )
        if "permission_set" in payload:
            self.event_bus.publish(PermissionUpdated(agent_id=saved.id))
        return saved

    def delete_agent(self, agent_id: str) -> bool:
        deleted = self.repository.delete_agent(agent_id)
        if deleted:
            self.event_bus.publish(AgentDeleted(agent_id=agent_id))
        return deleted

    def list_memory(self, agent_id: str) -> list[AgentMemoryReference]:
        return self.repository.list_agent_memory_references(agent_id)

    def attach_memory_reference(
        self,
        agent_id: str,
        kind: str,
        asset_id: str,
    ) -> AgentMemoryReference:
        agent = self.repository.get_agent(agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        asset = self.repository.get_asset(asset_id)
        if asset is None:
            raise ValueError("Asset not found")
        reference = AgentMemoryManager.create_reference(
            memory_id=agent.memory_id,
            agent_id=agent.id,
            kind=kind,
            asset_id=asset_id,
        )
        saved = self.repository.create_agent_memory_reference(reference)
        self.event_bus.publish(
            MemoryAttached(
                agent_id=agent.id,
                memory_id=agent.memory_id,
                reference_id=saved.id,
            )
        )
        return saved

    def get_permissions(self, agent_id: str) -> list[AgentPermission]:
        agent = self.repository.get_agent(agent_id)
        if agent is None:
            return []
        return agent.permission_set

    def generate_plan(self, agent_id: str, goal: str, workspace_intelligence: dict[str, object]) -> ExecutionPlan:
        agent = self.repository.get_agent(agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        normalized_goal = goal.strip()
        if not normalized_goal:
            raise ValueError("Goal is required")

        context = self._context_builder.build(
            goal=normalized_goal,
            project_id=agent.project_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            capabilities=list(agent.capabilities),
            workspace_intelligence=workspace_intelligence,
        )
        return self._planner.generate_plan(context)

    def create_schedule(
        self,
        *,
        agent_id: str,
        plan: ExecutionPlan,
        priority: SchedulerPriority,
        workspace_state: dict[str, object],
        available_executors: list[str],
        execution_policy: dict[str, object],
    ) -> ExecutionSchedule:
        agent = self.repository.get_agent(agent_id)
        if agent is None:
            raise ValueError("Agent not found")

        current_jobs = [job.model_dump(mode="json") for job in self.repository.list_jobs_by_project(agent.project_id)] if agent.project_id else [job.model_dump(mode="json") for job in self.repository.list_jobs()]
        running_workflows = [wf.model_dump(mode="json") for wf in self.repository.list_workflows(agent.project_id)]

        request = SchedulerRequest(
            plan_id=plan.plan_id,
            agent_id=agent.id,
            steps=list(plan.steps),
            priority=priority,
            workspace_state=workspace_state,
            current_jobs=current_jobs,
            running_workflows=running_workflows,
            available_executors=available_executors,
            execution_policy=execution_policy,
        )
        return self._scheduler.create_schedule(request)

    def get_schedule(self, schedule_id: str) -> ExecutionSchedule | None:
        return self._scheduler.get_schedule(schedule_id)

    def list_schedules(self, agent_id: str | None = None) -> list[ExecutionSchedule]:
        return self.repository.list_schedules(agent_id=agent_id)

    def get_schedule_queue(self, schedule_id: str) -> list[dict[str, object]]:
        queue = self._scheduler.get_queue(schedule_id)
        return [entry.model_dump(mode="json") for entry in queue]

    def pause_schedule(self, schedule_id: str) -> QueueUpdateResult:
        return self._scheduler.pause(schedule_id)

    def resume_schedule(self, schedule_id: str) -> QueueUpdateResult:
        return self._scheduler.resume(schedule_id)

    def cancel_schedule(self, schedule_id: str) -> QueueUpdateResult:
        return self._scheduler.cancel(schedule_id)

    def retry_schedule_entry(self, schedule_id: str, entry_id: str) -> QueueUpdateResult:
        return self._scheduler.retry_entry(schedule_id, entry_id)

    def start_runtime_for_schedule(self, schedule_id: str) -> list[dict[str, object]]:
        return [execution.model_dump(mode="json") for execution in self._runtime.start_schedule(schedule_id)]

    def list_runtime(self) -> list[dict[str, object]]:
        return [execution.model_dump(mode="json") for execution in self._runtime.list_runtime_executions()]

    def list_runtime_running(self) -> list[dict[str, object]]:
        return [execution.model_dump(mode="json") for execution in self._runtime.list_running()]

    def list_runtime_history(self) -> list[dict[str, object]]:
        return [execution.model_dump(mode="json") for execution in self._runtime.list_history()]

    def get_runtime_execution(self, execution_id: str) -> dict[str, object] | None:
        execution = self._runtime.get_runtime_execution(execution_id)
        return execution.model_dump(mode="json") if execution is not None else None

    def cancel_runtime_execution(self, execution_id: str) -> dict[str, object]:
        return self._runtime.cancel_execution(execution_id).model_dump(mode="json")

    def retry_runtime_execution(self, execution_id: str) -> dict[str, object]:
        return self._runtime.retry_execution(execution_id).model_dump(mode="json")

    def create_team(
        self,
        *,
        name: str,
        project_id: str | None,
        workspace_id: str | None,
        assignments: list[dict[str, object]],
    ) -> AgentTeam:
        team = AgentTeam(name=name, project_id=project_id, workspace_id=workspace_id, status=AgentTeamStatus.PENDING)
        self.repository.create_agent_team(team)

        for payload in assignments:
            agent_id = str(payload["agent_id"])
            agent = self.repository.get_agent(agent_id)
            if agent is None:
                raise ValueError("Agent not found")
            capability_set = self._capability_set_for_role(AgentRole(str(payload["role"])))
            mailbox = self.repository.get_agent_mailbox(agent_id)
            assignment = AgentAssignment(
                team_id=team.id,
                agent_id=agent_id,
                role=AgentRole(str(payload["role"])),
                title=str(payload.get("title") or f"{payload['role']} assignment"),
                status=AgentAssignmentStatus.PENDING,
                capabilities=list(capability_set.capabilities),
                allowed_actions=list(capability_set.allowed_actions),
                permissions=list(capability_set.permissions),
                resource_limits=dict(capability_set.resource_limits),
                action=str(payload["action"]),
                payload=dict(payload.get("payload") or {}),
                dependencies=[str(item) for item in payload.get("dependencies") or []],
                mailbox_id=mailbox.agent_id,
            )
            self.repository.create_agent_assignment(assignment)
            message = AgentMessage(
                sender="coordinator",
                receiver=agent_id,
                type=AgentMessageType.TASK_ASSIGNMENT,
                payload={
                    "assignment_id": assignment.id,
                    "team_id": team.id,
                    "action": assignment.action,
                    "payload": assignment.payload,
                    "dependencies": assignment.dependencies,
                },
                correlation_id=team.id,
            )
            self._enqueue_message(team.id, agent_id, message)
            self.event_bus.publish(AgentAssigned(team_id=team.id, assignment_id=assignment.id, agent_id=agent_id))

        created = self.repository.get_agent_team(team.id)
        assert created is not None
        return created

    def get_team(self, team_id: str) -> AgentTeam | None:
        return self.repository.get_agent_team(team_id)

    def list_team_messages(self, team_id: str) -> list[AgentMessage]:
        return self.repository.list_agent_messages(team_id)

    def get_team_status(self, team_id: str) -> dict[str, object]:
        team = self.repository.get_agent_team(team_id)
        if team is None:
            raise ValueError("Team not found")
        waiting = [item.id for item in team.assignments if item.status == AgentAssignmentStatus.WAITING]
        completed = [item.id for item in team.assignments if item.status == AgentAssignmentStatus.COMPLETED]
        running = [item.id for item in team.assignments if item.status == AgentAssignmentStatus.RUNNING]
        failed = [item.id for item in team.assignments if item.status == AgentAssignmentStatus.FAILED]
        return {
            "team_id": team.id,
            "status": team.status.value,
            "waiting": waiting,
            "running": running,
            "completed": completed,
            "failed": failed,
        }

    def cancel_team(self, team_id: str) -> AgentTeam:
        team = self.repository.get_agent_team(team_id)
        if team is None:
            raise ValueError("Team not found")
        updated_assignments: list[AgentAssignment] = []
        for assignment in team.assignments:
            if assignment.status not in {AgentAssignmentStatus.COMPLETED, AgentAssignmentStatus.FAILED, AgentAssignmentStatus.CANCELLED}:
                assignment = assignment.model_copy(update={"status": AgentAssignmentStatus.CANCELLED, "updated_at": datetime.now(UTC)})
                self.repository.update_agent_assignment(assignment)
                if assignment.runtime_execution_id:
                    self._runtime.cancel_execution(assignment.runtime_execution_id)
            updated_assignments.append(assignment)
        team = team.model_copy(update={"status": AgentTeamStatus.CANCELLED, "assignments": updated_assignments, "updated_at": datetime.now(UTC)})
        self.repository.update_agent_team(team)
        return team

    def execute_team(self, team_id: str) -> AgentTeam:
        team = self.repository.get_agent_team(team_id)
        if team is None:
            raise ValueError("Team not found")

        updated_assignments: list[AgentAssignment] = []
        any_running = False
        any_failed = False
        all_completed = True

        for assignment in team.assignments:
            if assignment.status == AgentAssignmentStatus.COMPLETED:
                updated_assignments.append(assignment)
                continue
            if assignment.status == AgentAssignmentStatus.CANCELLED:
                all_completed = False
                updated_assignments.append(assignment)
                continue

            if not self._dependencies_completed(team.assignments, assignment.dependencies):
                waiting_assignment = assignment.model_copy(update={"status": AgentAssignmentStatus.WAITING, "updated_at": datetime.now(UTC)})
                self.repository.update_agent_assignment(waiting_assignment)
                updated_assignments.append(waiting_assignment)
                self.event_bus.publish(AgentWaiting(team_id=team.id, assignment_id=waiting_assignment.id, agent_id=waiting_assignment.agent_id))
                all_completed = False
                continue

            started_assignment = assignment.model_copy(update={"status": AgentAssignmentStatus.RUNNING, "updated_at": datetime.now(UTC)})
            self.repository.update_agent_assignment(started_assignment)
            self.event_bus.publish(AgentStarted(team_id=team.id, assignment_id=started_assignment.id, agent_id=started_assignment.agent_id))

            schedule = self._create_assignment_schedule(started_assignment)
            executions = self._runtime.start_schedule(schedule.schedule_id)
            execution = executions[0] if executions else None
            update_payload: dict[str, object] = {"schedule_id": schedule.schedule_id, "updated_at": datetime.now(UTC)}
            if execution is not None:
                update_payload["runtime_execution_id"] = execution.execution_id
                if execution.status.value == "completed":
                    update_payload["status"] = AgentAssignmentStatus.COMPLETED
                    update_payload["result_asset_id"] = execution.asset_id
                    self.event_bus.publish(AgentCompleted(team_id=team.id, assignment_id=started_assignment.id, agent_id=started_assignment.agent_id))
                    completion_message = AgentMessage(
                        sender=started_assignment.agent_id,
                        receiver="coordinator",
                        type=AgentMessageType.COMPLETION,
                        payload={"assignment_id": started_assignment.id, "asset_id": execution.asset_id},
                        correlation_id=team.id,
                    )
                    self._record_team_message(team.id, completion_message)
                elif execution.status.value in {"failed", "timed_out"}:
                    update_payload["status"] = AgentAssignmentStatus.FAILED
                    update_payload["error"] = execution.error or execution.timeout_reason
                    any_failed = True
                    self.event_bus.publish(AgentFailed(team_id=team.id, assignment_id=started_assignment.id, agent_id=started_assignment.agent_id, reason=str(update_payload.get("error") or "execution failed")))
                    failure_message = AgentMessage(
                        sender=started_assignment.agent_id,
                        receiver="coordinator",
                        type=AgentMessageType.FAILURE,
                        payload={"assignment_id": started_assignment.id, "reason": update_payload.get("error")},
                        correlation_id=team.id,
                    )
                    self._record_team_message(team.id, failure_message)
                else:
                    update_payload["status"] = AgentAssignmentStatus.RUNNING
                    any_running = True
                    all_completed = False
            else:
                any_running = True
                all_completed = False
            updated_assignment = started_assignment.model_copy(update=update_payload)
            self.repository.update_agent_assignment(updated_assignment)
            updated_assignments.append(updated_assignment)
            if updated_assignment.status != AgentAssignmentStatus.COMPLETED:
                all_completed = False

        team_status = AgentTeamStatus.RUNNING
        if any_failed:
            team_status = AgentTeamStatus.FAILED
        elif all_completed and updated_assignments:
            team_status = AgentTeamStatus.COMPLETED
            self.event_bus.publish(TeamCompleted(team_id=team.id))
        elif any_running:
            team_status = AgentTeamStatus.RUNNING

        updated_team = team.model_copy(update={"assignments": updated_assignments, "status": team_status, "updated_at": datetime.now(UTC)})
        self.repository.update_agent_team(updated_team)
        return updated_team

    def _capability_set_for_role(self, role: AgentRole) -> AgentCapabilitySet:
        mapping: dict[AgentRole, AgentCapabilitySet] = {
            AgentRole.RESEARCH: AgentCapabilitySet(role=role, capabilities=["research"], allowed_actions=["text.generate"], permissions=[AgentPermission.READ_ASSETS], resource_limits={"max_cpu_jobs": 1}),
            AgentRole.PLANNER: AgentCapabilitySet(role=role, capabilities=["workflow"], allowed_actions=["text.generate"], permissions=[AgentPermission.READ_ASSETS], resource_limits={"max_cpu_jobs": 1}),
            AgentRole.WRITER: AgentCapabilitySet(role=role, capabilities=["text"], allowed_actions=["text.generate"], permissions=[AgentPermission.READ_ASSETS, AgentPermission.WRITE_ASSETS], resource_limits={"max_cpu_jobs": 1}),
            AgentRole.REVIEWER: AgentCapabilitySet(role=role, capabilities=["review"], allowed_actions=["text.generate"], permissions=[AgentPermission.READ_ASSETS, AgentPermission.REVIEW_ASSETS], resource_limits={"max_cpu_jobs": 1}),
            AgentRole.IMAGE: AgentCapabilitySet(role=role, capabilities=["image"], allowed_actions=["image.generate"], permissions=[AgentPermission.READ_ASSETS, AgentPermission.WRITE_ASSETS], resource_limits={"max_gpu_jobs": 1}),
            AgentRole.VIDEO: AgentCapabilitySet(role=role, capabilities=["video"], allowed_actions=["image.generate"], permissions=[AgentPermission.READ_ASSETS, AgentPermission.WRITE_ASSETS], resource_limits={"max_gpu_jobs": 1}),
            AgentRole.DEVELOPER: AgentCapabilitySet(role=role, capabilities=["code"], allowed_actions=["code.generate"], permissions=[AgentPermission.READ_ASSETS, AgentPermission.WRITE_ASSETS], resource_limits={"max_cpu_jobs": 1}),
            AgentRole.OPERATOR: AgentCapabilitySet(role=role, capabilities=["workflow"], allowed_actions=["text.generate"], permissions=[AgentPermission.READ_ASSETS, AgentPermission.MANAGE_AGENTS], resource_limits={"max_cpu_jobs": 1}),
        }
        return mapping[role]

    def _enqueue_message(self, team_id: str, agent_id: str, message: AgentMessage) -> None:
        mailbox = self.repository.get_agent_mailbox(agent_id)
        mailbox.pending_messages.append(message)
        mailbox.history.append(message)
        self.repository.update_agent_mailbox(mailbox)
        self.repository.create_agent_message(team_id, message)
        self.event_bus.publish(AgentMessageSent(team_id=team_id, message_id=message.id, sender=message.sender, receiver=message.receiver))
        self.event_bus.publish(AgentMessageReceived(team_id=team_id, message_id=message.id, sender=message.sender, receiver=message.receiver))

    def _record_team_message(self, team_id: str, message: AgentMessage) -> None:
        self.repository.create_agent_message(team_id, message)
        self.event_bus.publish(AgentMessageSent(team_id=team_id, message_id=message.id, sender=message.sender, receiver=message.receiver))

    def _dependencies_completed(self, assignments: list[AgentAssignment], dependency_ids: list[str]) -> bool:
        if not dependency_ids:
            return True
        status_by_id = {assignment.id: assignment.status for assignment in assignments}
        return all(status_by_id.get(dependency_id) == AgentAssignmentStatus.COMPLETED for dependency_id in dependency_ids)

    def _create_assignment_schedule(self, assignment: AgentAssignment) -> ExecutionSchedule:
        plan = ExecutionPlan(
            goal=assignment.title,
            confidence=1.0,
            estimated_duration_seconds=30,
            estimated_cost_usd=0.0,
            steps=[
                PlanStep(
                    description=assignment.title,
                    capability=assignment.capabilities[0] if assignment.capabilities else assignment.role.value,
                    action=assignment.action,
                    payload=assignment.payload,
                    expected_output=f"{assignment.role.value}-output",
                    dependencies=[],
                    estimated_time_seconds=30,
                    review_required=assignment.role == AgentRole.REVIEWER,
                )
            ],
            dependencies=[],
            capabilities_required=assignment.capabilities,
            assets_required=[],
            expected_outputs=[f"{assignment.role.value}-output"],
            review_required=assignment.role == AgentRole.REVIEWER,
            context_snapshot={"team_id": assignment.team_id, "assignment_id": assignment.id},
        )
        return self.create_schedule(
            agent_id=assignment.agent_id,
            plan=plan,
            priority=SchedulerPriority.NORMAL,
            workspace_state={"team_id": assignment.team_id},
            available_executors=["local"],
            execution_policy={},
        )
