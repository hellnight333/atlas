from __future__ import annotations

from .models import (
    POLICY_SCOPE_ORDER,
    PolicyDomain,
    PolicyScopeKind,
    PolicySet,
    ResolvedPolicy,
)


class PolicyResolver:
    """Resolves a policy domain down the inheritance chain.

        Organization -> Workspace -> Project -> Object

    A narrower scope overrides a broader one, key by key, except for keys a
    broader scope has locked. Locking is how an organization enforces something
    a project cannot opt out of.
    """

    def resolve(
        self,
        *,
        domain: PolicyDomain,
        organization_id: str,
        policy_sets: list[PolicySet],
        workspace_id: str | None = None,
        project_id: str | None = None,
        object_id: str | None = None,
    ) -> ResolvedPolicy:
        scope_ids: dict[PolicyScopeKind, str | None] = {
            PolicyScopeKind.ORGANIZATION: organization_id,
            PolicyScopeKind.WORKSPACE: workspace_id,
            PolicyScopeKind.PROJECT: project_id,
            PolicyScopeKind.OBJECT: object_id,
        }

        settings: dict[str, object] = {}
        sources: dict[str, str] = {}
        locked: dict[str, str] = {}
        chain: list[str] = []

        for scope in POLICY_SCOPE_ORDER:
            target_id = scope_ids[scope]
            if scope is not PolicyScopeKind.ORGANIZATION and target_id is None:
                continue

            for policy_set in self._matching(
                policy_sets, domain, organization_id, scope, target_id
            ):
                chain.append(policy_set.id)
                for key, value in policy_set.settings.items():
                    if key in locked and locked[key] != policy_set.id:
                        # A broader scope locked this key; the narrower scope
                        # may not override it.
                        continue
                    settings[key] = value
                    sources[key] = policy_set.id
                for key in policy_set.locked_keys:
                    locked.setdefault(key, policy_set.id)

        return ResolvedPolicy(
            domain=domain,
            organization_id=organization_id,
            settings=settings,
            sources=sources,
            locked_keys=sorted(locked),
            chain=chain,
        )

    def _matching(
        self,
        policy_sets: list[PolicySet],
        domain: PolicyDomain,
        organization_id: str,
        scope: PolicyScopeKind,
        scope_id: str | None,
    ) -> list[PolicySet]:
        matches = [
            policy_set
            for policy_set in policy_sets
            if policy_set.enabled
            and policy_set.domain is domain
            and policy_set.organization_id == organization_id
            and policy_set.scope is scope
            and (scope is PolicyScopeKind.ORGANIZATION or policy_set.scope_id == scope_id)
        ]
        # Deterministic order so the same inputs always resolve identically.
        return sorted(matches, key=lambda p: (p.created_at, p.id))
