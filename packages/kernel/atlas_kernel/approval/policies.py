from __future__ import annotations

from typing import Any

from .models import (
    ApprovalCondition,
    ApprovalContext,
    ApprovalEvaluation,
    ApprovalPolicy,
    ApprovalPolicyMode,
    ApprovalScope,
)


class ApprovalPolicyEngine:
    """Evaluates declarative policies against a context.

    The engine contains no rule of its own. Every rule — which scopes require
    approval, which cost is too high, which project is exempt — arrives as
    policy data. Adding a rule never means editing this class.
    """

    def evaluate(
        self, policies: list[ApprovalPolicy], context: ApprovalContext
    ) -> ApprovalEvaluation:
        for policy in self._ordered(policies, context):
            if not self._policy_applies(policy, context):
                continue

            if policy.mode is ApprovalPolicyMode.NEVER:
                return ApprovalEvaluation(
                    required=False,
                    policy_id=policy.id,
                    policy_name=policy.name,
                    reason=f"Policy '{policy.name}' exempts this action",
                )

            if policy.mode is ApprovalPolicyMode.ALWAYS:
                return self._required(policy, context, "Policy requires approval for all actions")

            matched = self._matched_scopes(policy, context)
            over_threshold = (
                policy.cost_threshold is not None and context.estimated_cost > policy.cost_threshold
            )

            if matched:
                names = ", ".join(scope.value for scope in matched)
                return self._required(
                    policy, context, f"Action requires approval for: {names}", matched
                )

            if over_threshold:
                return self._required(
                    policy,
                    context,
                    f"Estimated cost {context.estimated_cost} exceeds threshold {policy.cost_threshold}",
                    [ApprovalScope.PROVIDER_COST],
                )

            # A scoped policy that matched its conditions but neither scope nor
            # threshold fired is a deliberate pass — stop here rather than
            # letting a lower-priority policy override it.
            if policy.conditions:
                return ApprovalEvaluation(
                    required=False,
                    policy_id=policy.id,
                    policy_name=policy.name,
                    reason=f"Policy '{policy.name}' matched but no scope or threshold applied",
                )

        return ApprovalEvaluation(required=False, reason="No policy required approval")

    def _ordered(
        self, policies: list[ApprovalPolicy], context: ApprovalContext
    ) -> list[ApprovalPolicy]:
        """Most specific first, then highest priority — a total order, so the
        same context always resolves to the same policy."""
        scoped = [p for p in policies if p.enabled]
        return sorted(
            scoped,
            key=lambda p: (
                -self._specificity(p),
                -p.priority,
                p.created_at,
                p.id,
            ),
        )

    def _specificity(self, policy: ApprovalPolicy) -> int:
        score = 0
        if policy.project_id:
            score += 2
        if policy.workspace_id:
            score += 1
        return score

    def _policy_applies(self, policy: ApprovalPolicy, context: ApprovalContext) -> bool:
        if policy.project_id and policy.project_id != context.project_id:
            return False
        if policy.workspace_id and policy.workspace_id != context.workspace_id:
            return False
        return all(self._condition_holds(c, context) for c in policy.conditions)

    def _matched_scopes(
        self, policy: ApprovalPolicy, context: ApprovalContext
    ) -> list[ApprovalScope]:
        policy_scopes = set(policy.scopes)
        return [scope for scope in context.scopes if scope in policy_scopes]

    def _required(
        self,
        policy: ApprovalPolicy,
        context: ApprovalContext,
        reason: str,
        matched: list[ApprovalScope] | None = None,
    ) -> ApprovalEvaluation:
        return ApprovalEvaluation(
            required=True,
            policy_id=policy.id,
            policy_name=policy.name,
            reason=reason,
            required_approvers=list(policy.required_approvers),
            approvals_required=max(1, policy.approvals_required),
            expires_after_seconds=policy.expires_after_seconds,
            matched_scopes=matched or list(context.scopes),
        )

    def _condition_holds(self, condition: ApprovalCondition, context: ApprovalContext) -> bool:
        actual = self._resolve(condition.field, context)
        operator = condition.operator
        expected = condition.value

        if operator == "equals":
            return actual == expected
        if operator == "not_equals":
            return actual != expected
        if operator == "in":
            return actual in (expected or [])
        if operator == "not_in":
            return actual not in (expected or [])
        if operator == "contains":
            return actual is not None and expected in actual
        if operator == "greater_than":
            return actual is not None and actual > expected
        if operator == "less_than":
            return actual is not None and actual < expected
        if operator == "exists":
            return actual is not None
        if operator == "not_exists":
            return actual is None
        raise ValueError(f"Unsupported approval condition operator: {operator}")

    def _resolve(self, field: str, context: ApprovalContext) -> Any:
        """Dotted lookup so policies can address payload and metadata without
        the engine knowing their shape."""
        if "." in field:
            head, _, tail = field.partition(".")
            container = getattr(context, head, None)
            if isinstance(container, dict):
                cursor: Any = container
                for part in tail.split("."):
                    if not isinstance(cursor, dict):
                        return None
                    cursor = cursor.get(part)
                return cursor
            return None
        if field == "scopes":
            return [scope.value for scope in context.scopes]
        return getattr(context, field, None)
