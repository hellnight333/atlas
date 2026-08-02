# Atlas Plugin Governance

## 1. Purpose

This document defines governance architecture for plugins and marketplace extensions at the shell layer.

It resolves ambiguity around trust, permissions, failure isolation, compatibility, and lifecycle behavior.

This is the source of truth for plugin governance.

## 2. Governance Principles

1. Extensibility without shell fragmentation.
2. Least-privilege by default.
3. Explicit trust signals and verification status.
4. Failure containment and recoverability.
5. Predictable compatibility lifecycle.

## 3. Plugin Lifecycle

Lifecycle states:

1. `discovered`
2. `verified`
3. `installed`
4. `enabled`
5. `active`
6. `degraded`
7. `disabled`
8. `quarantined`
9. `retired`

State transition policy:

- unverifiable plugins cannot auto-transition to active trusted status
- degraded plugins must emit health telemetry and containment action

## 4. Trust Levels

Trust classes:

- `atlas_core_trusted`
- `marketplace_verified`
- `organization_verified`
- `unverified_limited`
- `quarantined`

Trust class drives:

- permission ceilings
- visibility defaults
- warning posture
- execution constraints

## 5. Sandboxing and Isolation

### 5.1 Isolation Domains

- UI extension surface isolation
- command execution isolation
- resource access isolation
- crash containment isolation

### 5.2 Isolation Guarantees

- plugin failures cannot crash core shell
- plugin stalls cannot block command system globally
- plugin state corruption cannot mutate core taxonomy definitions

## 6. Permission Model

Permission categories:

- workspace metadata access
- project content read
- project content write
- command registration
- network integration access
- activity/event observation

Permission rules:

- explicit user or organization grant required for elevated permissions
- runtime permission prompts must include impact summary
- permissions are revocable without uninstall requirement

## 7. Failure Isolation and Crash Containment

### 7.1 Failure Classes

- startup failure
- runtime exception
- performance degradation
- permission violation
- compatibility mismatch

### 7.2 Containment Actions

- isolate plugin process/surface
- disable plugin-specific commands
- preserve shell continuity
- route diagnostics to Activity Center

### 7.3 User Visibility

Users must see:

- impacted surfaces
- safe fallback behavior
- remediation options

## 8. Marketplace Verification

Verification signals include:

- publisher identity
- security review status
- compatibility certification
- maintenance recency
- enterprise policy compatibility

Unverified plugins receive limited default visibility and stronger caution signals.

## 9. Version Compatibility

### 9.1 Compatibility Dimensions

- shell interface version
- command contract version
- studio taxonomy compatibility
- enterprise policy compatibility

### 9.2 Compatibility States

- `compatible`
- `compatible_with_warnings`
- `blocked_incompatible`

Compatibility state must be visible before enablement.

## 10. Plugin Studios and Taxonomy

Plugins that introduce studios must:

- declare primary capability mapping
- follow studio naming and grouping rules
- avoid duplicate-purpose studio collisions

Governance of studio scaling remains in STUDIO_TAXONOMY.md.

## 11. Policy and Enterprise Controls

Organizations can enforce:

- allowlists/blocklists
- required verification class
- restricted permission sets
- forced disable/quarantine

These controls must be visible in enterprise shell indicators.

## 12. Anti-Ambiguity Rules

1. Plugin trust must be visible before activation.
2. Shell-critical surfaces cannot be overridden by unverified plugins.
3. Failed plugin state must never appear as core shell failure.
4. Permission escalation cannot be implicit.
5. Compatibility mismatch must block unsafe activation.

## 13. Cross-References

- Shell expansion model: DESKTOP_SHELL_V1.md
- Studio scaling and plugin studios: STUDIO_TAXONOMY.md
- Activity and failure propagation: ACTIVITY_MODEL.md
- Enterprise controls: ENTERPRISE_SHELL.md