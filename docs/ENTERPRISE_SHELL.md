# Atlas Enterprise Shell

## 1. Purpose

This document defines shell-level enterprise readiness concepts for multi-tenant, policy-governed environments.

This is the source of truth for enterprise shell semantics.

## 2. Enterprise Principles

1. Tenant context must always be visible.
2. Policy impact must be explainable at point of action.
3. Ownership and role boundaries must be explicit.
4. Audit visibility should be accessible without workflow disruption.
5. Branding and organization identity must not compromise core usability.

## 3. Tenant Awareness

### 3.1 Tenant Identity Surfaces

Tenant identity must be visible in:

- top-level shell identity zone
- workspace context summary
- high-impact action confirmations

### 3.2 Tenant Boundary Protection

Shell must prevent ambiguous cross-tenant actions by requiring explicit confirmation on boundary-crossing operations.

## 4. Policy Visibility

### 4.1 Policy Signals

Users must see policy impact when an action is:

- blocked
- modified
- audited
- elevated for approval

### 4.2 Policy Explainability

Every policy-constrained action exposes:

- governing policy category
- effect type (deny, restrict, require approval)
- remediation path if available

## 5. Workspace Ownership

Ownership layers:

- organization ownership
- team ownership
- project ownership
- personal working ownership

Shell must make current ownership context explicit before high-impact operations.

## 6. Organization Switching

Organization switching rules:

- organization identity always visible before switch commit
- active unsaved or risky contexts trigger confirmation
- post-switch state summary required to preserve orientation

## 7. Role Indicators

Role visibility must be present for:

- current user role scope
- elevated temporary roles
- delegated access sessions

Role changes should trigger non-disruptive but explicit state cues.

## 8. Audit Visibility

### 8.1 Audit Surface Requirements

Enterprise users need direct access to:

- action lineage
- policy decisions affecting outcomes
- actor and timestamp metadata

### 8.2 Integration

Audit visibility integrates with Activity and Logs surfaces, without duplicating source-of-truth semantics.

## 9. Enterprise Branding

Branding allowances:

- organization identity accents
- legal or compliance marks
- custom workspace naming overlays

Branding constraints:

- cannot alter command semantics
- cannot obscure policy or trust indicators
- cannot fragment shared shell interaction patterns

## 10. Enterprise Collaboration Semantics

Shell must support:

- presence visibility
- role-aware collaboration affordances
- policy-constrained sharing cues

Collaboration signals must remain distinguishable from personal state signals.

## 11. Enterprise Plugin Controls

Enterprise policy can enforce:

- plugin verification requirements
- permission restrictions
- allowlist/blocklist behavior
- forced quarantine actions

Plugin governance remains authoritative in PLUGIN_GOVERNANCE.md.

## 12. Anti-Ambiguity Rules

1. Tenant identity can never be hidden.
2. Policy-blocked actions must explain why.
3. Role scope must be visible before privileged actions.
4. Audit visibility must be one-step accessible from impacted actions.
5. Branding cannot reduce trust signal clarity.

## 13. Cross-References

- Shell integration points: DESKTOP_SHELL_V1.md
- Activity and audit propagation: ACTIVITY_MODEL.md
- Plugin controls: PLUGIN_GOVERNANCE.md
- Multi-window authority with enterprise roles: MULTI_WINDOW_MODEL.md
- Studio visibility and governance: STUDIO_TAXONOMY.md